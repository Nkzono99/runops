"""Structured experiment selection and survey expansion gate."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from runops.core.exceptions import ProjectNotFoundError, SimctlError
from runops.core.project import find_project_root

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

ExperimentStage = Literal["pilot", "full"]
ExperimentDecision = Literal["WAIT", "EXPAND", "REVISE", "STOP"]
_DECISIONS = frozenset({"WAIT", "EXPAND", "REVISE", "STOP"})


@dataclass(frozen=True)
class ExperimentAuthorization:
    """Validated authorization attached to a survey bulk operation."""

    experiment_id: str
    stage: ExperimentStage
    decision: ExperimentDecision
    proposal_path: Path
    review_path: Path | None
    selected_candidate: str


def validate_bulk_experiment_gate(
    survey_dir: Path,
) -> ExperimentAuthorization | None:
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
    ledger_path = project_root / "research" / "experiments.toml"
    ledger = _read_toml(ledger_path)
    if ledger.get("schema_version") != 1:
        raise SimctlError("research/experiments.toml schema_version must be 1")
    raw_experiments = ledger.get("experiments")
    if not isinstance(raw_experiments, list):
        raise SimctlError("research/experiments.toml must define [[experiments]]")
    matches = [
        item
        for item in raw_experiments
        if isinstance(item, dict) and item.get("id") == experiment_id
    ]
    if len(matches) != 1:
        raise SimctlError(
            f"experiment {experiment_id!r} must appear exactly once in {ledger_path}"
        )
    experiment = matches[0]
    raw_decision = _required_string(
        experiment, "decision", f"experiment {experiment_id}"
    )
    if raw_decision not in _DECISIONS:
        raise SimctlError(
            f"experiment {experiment_id} decision must be WAIT/EXPAND/REVISE/STOP"
        )
    decision = cast("ExperimentDecision", raw_decision)

    candidates = experiment.get("candidates")
    if not isinstance(candidates, list) or len(candidates) < 2:
        raise SimctlError(
            f"experiment {experiment_id} requires at least two candidates"
        )
    candidate_ids: list[str] = []
    for index, candidate in enumerate(candidates, start=1):
        if not isinstance(candidate, dict):
            raise SimctlError(
                f"experiment {experiment_id} candidate #{index} must be a table"
            )
        candidate_id = _required_string(candidate, "id", f"candidate #{index}")
        for field in ("information_gain", "falsification", "operational_risk"):
            _required_string(candidate, field, f"candidate {candidate_id}")
        core_hours = candidate.get("estimated_core_hours")
        if (
            isinstance(core_hours, bool)
            or not isinstance(core_hours, (int, float))
            or core_hours < 0
        ):
            raise SimctlError(
                f"candidate {candidate_id} estimated_core_hours must be non-negative"
            )
        candidate_ids.append(candidate_id)
    if len(candidate_ids) != len(set(candidate_ids)):
        raise SimctlError(f"experiment {experiment_id} candidate ids must be unique")
    selected = _required_string(
        experiment, "selected_candidate", f"experiment {experiment_id}"
    )
    if selected not in candidate_ids:
        raise SimctlError(
            f"experiment {experiment_id} selected_candidate must name a candidate"
        )

    proposal = _project_file(
        project_root,
        _required_string(experiment, "proposal", f"experiment {experiment_id}"),
        field="proposal",
    )
    review: Path | None = None
    raw_review = str(experiment.get("review", "") or "").strip()
    if stage == "full":
        if decision != "EXPAND":
            raise SimctlError(
                f"full survey {survey_dir} requires decision EXPAND for {experiment_id}"
            )
        if not raw_review:
            raise SimctlError(f"experiment {experiment_id} EXPAND requires review path")
        review = _project_file(project_root, raw_review, field="review")
    elif raw_review:
        review = _project_file(project_root, raw_review, field="review")

    return ExperimentAuthorization(
        experiment_id=experiment_id,
        stage=stage,
        decision=decision,
        proposal_path=proposal,
        review_path=review,
        selected_candidate=selected,
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


def _project_file(project_root: Path, value: str, *, field: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        raise SimctlError(f"experiment {field} path must be project-relative")
    resolved = (project_root / path).resolve()
    try:
        resolved.relative_to(project_root.resolve())
    except ValueError as exc:
        raise SimctlError(f"experiment {field} path escapes project root") from exc
    if not resolved.is_file():
        raise SimctlError(f"experiment {field} file not found: {value}")
    return resolved
