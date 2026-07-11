"""Survey bulk-operation authorization backed by the experiment ledger."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, cast

from runops.application.research.experiments.models import (
    ExperimentAuthorization,
    ExperimentStage,
)
from runops.application.research.experiments.schema import load_experiment_ledger
from runops.core.exceptions import ProjectNotFoundError, SimctlError
from runops.core.project import find_project_root

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


def validate_bulk_experiment_gate(survey_dir: Path) -> ExperimentAuthorization | None:
    """Validate research authorization for a survey-backed bulk operation."""
    survey_path = survey_dir.resolve() / "survey.toml"
    if not survey_path.is_file():
        return None
    survey = _read_toml(survey_path)
    research = survey.get("research")
    if not isinstance(research, dict):
        raise SimctlError(
            f"survey bulk submission requires [research] in {survey_path}"
        )
    experiment_id = _required_string(research, "experiment_id", "survey research")
    raw_stage = _required_string(research, "stage", "survey research")
    if raw_stage not in {"pilot", "full"}:
        raise SimctlError("survey research.stage must be 'pilot' or 'full'")
    stage = cast("ExperimentStage", raw_stage)

    try:
        project_root = find_project_root(survey_dir)
    except ProjectNotFoundError as exc:
        raise SimctlError(str(exc)) from exc
    ledger = load_experiment_ledger(project_root)
    matches = [item for item in ledger.experiments if item.id == experiment_id]
    if len(matches) != 1:
        raise SimctlError(
            f"experiment {experiment_id!r} must appear exactly once in {ledger.path}"
        )
    experiment = matches[0]
    if ledger.schema_version == 2 and experiment.migration_blockers:
        raise SimctlError(
            f"experiment {experiment_id} has unresolved migration blockers: "
            + ", ".join(experiment.migration_blockers)
        )

    proposal = _project_file(project_root, experiment.proposal, field="proposal")
    review: Path | None = None
    if stage == "full":
        if experiment.decision != "EXPAND":
            raise SimctlError(
                f"full survey {survey_dir} requires decision EXPAND for {experiment_id}"
            )
        if not experiment.review:
            raise SimctlError(f"experiment {experiment_id} EXPAND requires review path")
        review = _project_file(project_root, experiment.review, field="review")
    elif experiment.review:
        review = _project_file(project_root, experiment.review, field="review")

    if ledger.schema_version == 2 and stage == "full":
        scope = experiment.authorization
        if scope is None:
            raise SimctlError(
                f"experiment {experiment_id} full stage requires authorization"
            )
        survey_relative = survey_dir.resolve().relative_to(project_root.resolve())
        if scope.stage != stage or scope.survey != survey_relative:
            raise SimctlError(
                f"experiment {experiment_id} authorization scope does not match survey"
            )
        if scope.review != experiment.review:
            raise SimctlError(
                f"experiment {experiment_id} authorization review does not match"
            )
        selected = next(
            candidate
            for candidate in experiment.candidates
            if candidate.id == experiment.selected_candidate
        )
        ceiling = experiment.cost_ceiling_core_hours
        if ceiling is None or selected.estimated_core_hours > min(
            ceiling, scope.max_core_hours
        ):
            raise SimctlError(
                f"experiment {experiment_id} exceeds authorized cost ceiling"
            )

    return ExperimentAuthorization(
        experiment_id=experiment_id,
        stage=stage,
        decision=experiment.decision,
        proposal_path=proposal,
        review_path=review,
        selected_candidate=experiment.selected_candidate,
    )


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with open(path, "rb") as stream:
            return tomllib.load(stream)
    except OSError as exc:
        raise SimctlError(f"Failed to read experiment gate TOML {path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise SimctlError(f"Invalid experiment gate TOML {path}: {exc}") from exc


def _required_string(payload: dict[str, Any], field: str, context: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise SimctlError(f"{context} requires non-empty {field}")
    return value.strip()


def _project_file(project_root: Path, path: Path, *, field: str) -> Path:
    if path.is_absolute():
        raise SimctlError(f"experiment {field} path must be project-relative")
    resolved = (project_root / path).resolve()
    try:
        resolved.relative_to(project_root.resolve())
    except ValueError as exc:
        raise SimctlError(f"experiment {field} path escapes project root") from exc
    if not resolved.is_file():
        raise SimctlError(f"experiment {field} file not found: {path}")
    return resolved
