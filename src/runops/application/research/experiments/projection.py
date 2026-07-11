"""Integrity checks and derived experiment readiness."""

from __future__ import annotations

import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from runops.application.analysis.artifacts import read_artifacts_index
from runops.application.research.experiments.models import (
    ExperimentIssue,
    ExperimentPhase,
    ExperimentProjection,
    ExperimentRecord,
    ExperimentStage,
)
from runops.application.research.experiments.schema import load_experiment_ledger
from runops.core.discovery import discover_runs
from runops.core.exceptions import ManifestError, SimctlError
from runops.core.manifest import read_manifest

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

_ACTIVE = frozenset({"submitted", "running"})
_KNOWN_STATES = frozenset(
    {
        "created",
        "submitted",
        "running",
        "completed",
        "failed",
        "cancelled",
        "archived",
        "purged",
    }
)


@dataclass(frozen=True)
class _Survey:
    path: Path
    stage: ExperimentStage
    aliases: frozenset[str]


def check_experiments(
    project_root: Path, experiment_id: str | None = None
) -> tuple[ExperimentIssue, ...]:
    """Return stable integrity findings for one or all experiments."""
    projections = (
        (project_experiment(project_root, experiment_id),)
        if experiment_id is not None
        else list_experiment_projections(project_root)
    )
    issues = [
        issue
        for projection in projections
        for issue in (*projection.blockers, *projection.warnings)
    ]
    return tuple(
        sorted(
            issues,
            key=lambda item: (
                item.path.as_posix() if item.path is not None else "",
                item.code,
                item.message,
            ),
        )
    )


def list_experiment_projections(project_root: Path) -> tuple[ExperimentProjection, ...]:
    """Project every experiment in stable ID order."""
    ledger = load_experiment_ledger(project_root)
    return tuple(
        _project_record(project_root.resolve(), record)
        for record in sorted(ledger.experiments, key=lambda item: item.id)
    )


def project_experiment(project_root: Path, experiment_id: str) -> ExperimentProjection:
    """Derive the current operational phase of one experiment."""
    ledger = load_experiment_ledger(project_root)
    matches = [record for record in ledger.experiments if record.id == experiment_id]
    if not matches:
        raise SimctlError(f"experiment not found: {experiment_id}")
    return _project_record(project_root.resolve(), matches[0])


def _project_record(
    project_root: Path, record: ExperimentRecord
) -> ExperimentProjection:
    blockers: list[ExperimentIssue] = []
    warnings: list[ExperimentIssue] = []
    proposal_path = project_root / record.proposal
    if not proposal_path.is_file():
        blockers.append(
            ExperimentIssue(
                "error",
                "proposal_missing",
                "Proposal attachment is missing.",
                proposal_path,
            )
        )
    if record.migration_blockers:
        blockers.append(
            ExperimentIssue(
                "error",
                "migration_incomplete",
                "Complete migrated fields: " + ", ".join(record.migration_blockers),
                record_path(project_root),
            )
        )

    surveys, survey_issues = _discover_surveys(project_root, record.id)
    blockers.extend(item for item in survey_issues if item.severity == "error")
    warnings.extend(item for item in survey_issues if item.severity == "warning")
    if record.review is not None and not (project_root / record.review).is_file():
        blockers.append(
            ExperimentIssue(
                "error",
                "review_missing",
                "Review attachment is missing.",
                project_root / record.review,
            )
        )

    full_scope_valid = _authorization_valid(project_root, record, surveys, blockers)
    counts: Counter[str] = Counter()
    stage_counts: dict[str, Counter[str]] = {"pilot": Counter(), "full": Counter()}
    required_artifacts = 0
    present_artifacts = 0
    for run_dir, stage, state in _discover_experiment_runs(
        project_root, surveys, warnings
    ):
        counts[state] += 1
        stage_counts[stage][state] += 1
        if state == "completed":
            required_artifacts += 1
            index = run_dir / "analysis" / "artifacts.toml"
            if index.is_file():
                try:
                    if read_artifacts_index(index):
                        present_artifacts += 1
                except (OSError, tomllib.TOMLDecodeError):
                    warnings.append(
                        ExperimentIssue(
                            "warning",
                            "artifact_index_invalid",
                            "Artifact index could not be read.",
                            index,
                        )
                    )

    phase = _phase(
        record,
        blockers,
        surveys,
        stage_counts,
        required_artifacts,
        present_artifacts,
        full_scope_valid,
    )
    next_actions, next_commands = _next_steps(record, phase, blockers)
    return ExperimentProjection(
        experiment=record,
        phase=phase,
        surveys=tuple(item.path for item in surveys),
        run_counts=dict(sorted(counts.items())),
        required_artifacts=required_artifacts,
        present_artifacts=present_artifacts,
        blockers=tuple(sorted(blockers, key=lambda item: (item.code, item.message))),
        warnings=tuple(sorted(warnings, key=lambda item: (item.code, item.message))),
        next_actions=next_actions,
        next_commands=next_commands,
    )


def _discover_surveys(
    project_root: Path, experiment_id: str
) -> tuple[list[_Survey], list[ExperimentIssue]]:
    surveys: list[_Survey] = []
    issues: list[ExperimentIssue] = []
    for path in sorted((project_root / "runs").rglob("survey.toml")):
        try:
            payload = _read_toml(path)
        except (OSError, tomllib.TOMLDecodeError):
            issues.append(
                ExperimentIssue(
                    "warning", "survey_invalid", "Survey TOML is invalid.", path
                )
            )
            continue
        research = payload.get("research")
        if (
            not isinstance(research, dict)
            or research.get("experiment_id") != experiment_id
        ):
            continue
        stage = research.get("stage")
        if stage not in {"pilot", "full"}:
            issues.append(
                ExperimentIssue(
                    "error",
                    "survey_stage_invalid",
                    "Survey research stage is invalid.",
                    path,
                )
            )
            continue
        survey_table = payload.get("survey")
        survey_id = survey_table.get("id") if isinstance(survey_table, dict) else None
        directory = path.parent.resolve()
        relative = directory.relative_to(project_root).as_posix()
        aliases = {relative, directory.name}
        if isinstance(survey_id, str) and survey_id.strip():
            aliases.add(survey_id.strip())
        surveys.append(
            _Survey(directory, cast("ExperimentStage", stage), frozenset(aliases))
        )
    return surveys, issues


def _discover_experiment_runs(
    project_root: Path,
    surveys: list[_Survey],
    warnings: list[ExperimentIssue],
) -> list[tuple[Path, ExperimentStage, str]]:
    alias_to_stage = {
        alias: survey.stage for survey in surveys for alias in survey.aliases
    }
    found: list[tuple[Path, ExperimentStage, str]] = []
    for run_dir in discover_runs(project_root / "runs"):
        try:
            manifest = read_manifest(run_dir)
        except ManifestError:
            warnings.append(
                ExperimentIssue(
                    "warning",
                    "manifest_invalid",
                    "Run manifest is invalid.",
                    run_dir / "manifest.toml",
                )
            )
            continue
        origin = str(manifest.origin.get("survey", "")).strip()
        stage = alias_to_stage.get(origin)
        if stage is None:
            continue
        state = str(manifest.run.get("status", "")).strip()
        if state not in _KNOWN_STATES:
            warnings.append(
                ExperimentIssue(
                    "warning",
                    "run_state_unknown",
                    f"Unknown run state: {state or '<empty>'}.",
                    run_dir / "manifest.toml",
                )
            )
        found.append((run_dir, stage, state))
    return found


def _authorization_valid(
    project_root: Path,
    record: ExperimentRecord,
    surveys: list[_Survey],
    blockers: list[ExperimentIssue],
) -> bool:
    if record.decision != "EXPAND":
        return False
    scope = record.authorization
    if scope is None:
        return False
    selected = next(
        item for item in record.candidates if item.id == record.selected_candidate
    )
    valid = (
        scope.stage == "full"
        and any(
            survey.stage == "full"
            and survey.path == (project_root / scope.survey).resolve()
            for survey in surveys
        )
        and record.review is not None
        and scope.review == record.review
        and record.cost_ceiling_core_hours is not None
        and selected.estimated_core_hours
        <= min(scope.max_core_hours, record.cost_ceiling_core_hours)
    )
    if not valid:
        blockers.append(
            ExperimentIssue(
                "error",
                "authorization_invalid",
                "Full-stage authorization is inconsistent.",
            )
        )
    return valid


def _phase(
    record: ExperimentRecord,
    blockers: list[ExperimentIssue],
    surveys: list[_Survey],
    counts: dict[str, Counter[str]],
    required_artifacts: int,
    present_artifacts: int,
    full_scope_valid: bool,
) -> ExperimentPhase:
    if blockers:
        return "blocked"
    if record.decision == "STOP":
        return "stopped"
    if record.decision == "REVISE":
        return "revising"
    full = counts["full"]
    pilot = counts["pilot"]
    if (
        full
        and sum(full.values()) == full.get("completed", 0)
        and required_artifacts == present_artifacts
    ):
        return "completed"
    if any(full.get(state, 0) for state in _ACTIVE):
        return "full-active"
    if record.decision == "EXPAND" and full_scope_valid:
        return "full-authorized"
    if pilot.get("completed", 0):
        return "review-pending"
    if any(pilot.get(state, 0) for state in _ACTIVE):
        return "pilot-active"
    if pilot:
        return "pilot-ready"
    if any(survey.stage == "pilot" for survey in surveys):
        return "pilot-planned"
    return "proposed"


def _next_steps(
    record: ExperimentRecord,
    phase: ExperimentPhase,
    blockers: list[ExperimentIssue],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if phase == "blocked":
        if any(issue.code == "proposal_missing" for issue in blockers):
            return ("Create the proposal attachment.",), ()
        return ("Resolve experiment integrity blockers.",), ()
    if phase == "full-authorized":
        return (), (f"runo experiment submit {record.id} --stage full --dry-run",)
    if phase == "proposed":
        return ("Prepare a pilot survey.",), ()
    if phase == "review-pending":
        return ("Review pilot evidence and record a decision.",), ()
    return (), ()


def record_path(project_root: Path) -> Path:
    return project_root / "research" / "experiments.toml"


def _read_toml(path: Path) -> dict[str, Any]:
    with open(path, "rb") as stream:
        return tomllib.load(stream)
