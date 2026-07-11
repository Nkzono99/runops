"""Experiment ledger and creation-spec parsing."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, cast

from runops.application.research.experiments.models import (
    ExperimentAuthorizationScope,
    ExperimentCandidate,
    ExperimentCreateSpec,
    ExperimentDecision,
    ExperimentLedger,
    ExperimentRecord,
    ExperimentStage,
)
from runops.core.exceptions import SimctlError

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

_DECISIONS = frozenset({"WAIT", "EXPAND", "REVISE", "STOP"})
_STAGES = frozenset({"pilot", "full"})


def load_experiment_ledger(project_root: Path) -> ExperimentLedger:
    """Load schema v1 or v2 into a typed in-memory ledger."""
    path = project_root.resolve() / "research" / "experiments.toml"
    payload = _read_toml(path)
    version = payload.get("schema_version")
    if isinstance(version, bool) or version not in {1, 2}:
        raise SimctlError("research/experiments.toml schema_version must be 1 or 2")
    raw_experiments = payload.get("experiments", [])
    if not isinstance(raw_experiments, list):
        raise SimctlError("research/experiments.toml must define [[experiments]]")
    records = tuple(
        _parse_record(item, index=index, schema_version=version)
        for index, item in enumerate(raw_experiments, start=1)
    )
    ids = [record.id for record in records]
    if len(ids) != len(set(ids)):
        raise SimctlError("experiment ids must be unique")
    stat = path.stat()
    return ExperimentLedger(
        path=path,
        schema_version=version,
        experiments=records,
        identity=(stat.st_dev, stat.st_ino, stat.st_mtime_ns),
    )


def read_experiment_spec(path: Path) -> ExperimentCreateSpec:
    """Read and validate a TOML or JSON experiment creation spec."""
    suffix = path.suffix.lower()
    if suffix == ".toml":
        payload = _read_toml(path)
    elif suffix == ".json":
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise SimctlError(f"Failed to read experiment spec {path}: {exc}") from exc
        if not isinstance(raw, dict):
            raise SimctlError("experiment spec must be an object")
        payload = cast("dict[str, Any]", raw)
    else:
        raise SimctlError("experiment spec must be TOML or JSON")

    candidates = _parse_candidates(payload.get("candidates"), "experiment spec")
    selected = _required_string(payload, "selected_candidate", "experiment spec")
    _validate_selected(selected, candidates, "experiment spec")
    return ExperimentCreateSpec(
        title=_required_string(payload, "title", "experiment spec"),
        question=_required_string(payload, "question", "experiment spec"),
        selected_candidate=selected,
        cost_ceiling_core_hours=_non_negative_number(
            payload.get("cost_ceiling_core_hours"),
            "experiment spec cost_ceiling_core_hours",
        ),
        candidates=candidates,
    )


def _parse_record(
    raw: object,
    *,
    index: int,
    schema_version: int,
) -> ExperimentRecord:
    if not isinstance(raw, dict):
        raise SimctlError(f"experiment #{index} must be a table")
    payload = cast("dict[str, Any]", raw)
    experiment_id = _required_string(payload, "id", f"experiment #{index}")
    context = f"experiment {experiment_id}"
    if schema_version == 2 and "phase" in payload:
        raise SimctlError(f"{context} phase is derived and must not be stored")
    decision = _decision(payload.get("decision"), context)
    candidates = _parse_candidates(payload.get("candidates"), context)
    selected = _required_string(payload, "selected_candidate", context)
    _validate_selected(selected, candidates, context)
    proposal = _relative_path_string(payload, "proposal", context)
    review = _optional_relative_path_string(payload, "review", context)

    blockers: list[str] = []
    if schema_version == 1:
        title = _optional_string(payload.get("title"))
        question = _optional_string(payload.get("question"))
        cost = _optional_non_negative_number(
            payload.get("cost_ceiling_core_hours"), context
        )
        if title is None:
            blockers.append("title")
        if question is None:
            blockers.append("question")
        if cost is None:
            blockers.append("cost_ceiling_core_hours")
    else:
        raw_blockers = payload.get("migration_blockers", [])
        if not isinstance(raw_blockers, list) or not all(
            isinstance(item, str) and item.strip() for item in raw_blockers
        ):
            raise SimctlError(f"{context} migration_blockers must be strings")
        if "migration_blockers" in payload and not raw_blockers:
            raise SimctlError(
                f"{context} migration_blockers must be omitted when empty"
            )
        blockers = [item.strip() for item in raw_blockers]
        title = _optional_string(payload.get("title"))
        question = _optional_string(payload.get("question"))
        cost = _optional_non_negative_number(
            payload.get("cost_ceiling_core_hours"), context
        )
        missing = [
            field
            for field, value in (
                ("title", title),
                ("question", question),
                ("cost_ceiling_core_hours", cost),
            )
            if value is None
        ]
        uncovered = [field for field in missing if field not in blockers]
        if uncovered:
            raise SimctlError(
                f"{context} requires {', '.join(uncovered)} "
                "or explicit migration blockers"
            )

    authorization = _parse_authorization(payload.get("authorization"), context)
    return ExperimentRecord(
        id=experiment_id,
        title=title,
        question=question,
        decision=decision,
        proposal=proposal,
        review=review,
        selected_candidate=selected,
        cost_ceiling_core_hours=cost,
        candidates=candidates,
        authorization=authorization,
        migration_blockers=tuple(blockers),
    )


def _parse_candidates(raw: object, context: str) -> tuple[ExperimentCandidate, ...]:
    if not isinstance(raw, list) or len(raw) < 2:
        raise SimctlError(f"{context} requires at least two candidates")
    candidates: list[ExperimentCandidate] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise SimctlError(f"{context} candidate #{index} must be a table")
        candidate = cast("dict[str, Any]", item)
        candidate_id = _required_string(candidate, "id", f"candidate #{index}")
        candidates.append(
            ExperimentCandidate(
                id=candidate_id,
                information_gain=_required_string(
                    candidate, "information_gain", f"candidate {candidate_id}"
                ),
                falsification=_required_string(
                    candidate, "falsification", f"candidate {candidate_id}"
                ),
                estimated_core_hours=_non_negative_number(
                    candidate.get("estimated_core_hours"),
                    f"candidate {candidate_id} estimated_core_hours",
                ),
                operational_risk=_required_string(
                    candidate, "operational_risk", f"candidate {candidate_id}"
                ),
            )
        )
    ids = [candidate.id for candidate in candidates]
    if len(ids) != len(set(ids)):
        raise SimctlError(f"{context} candidate ids must be unique")
    return tuple(candidates)


def _parse_authorization(
    raw: object, context: str
) -> ExperimentAuthorizationScope | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise SimctlError(f"{context} authorization must be a table")
    payload = cast("dict[str, Any]", raw)
    stage_value = _required_string(payload, "stage", f"{context} authorization")
    if stage_value not in _STAGES:
        raise SimctlError(f"{context} authorization stage must be pilot or full")
    return ExperimentAuthorizationScope(
        stage=cast("ExperimentStage", stage_value),
        survey=_relative_path_string(payload, "survey", f"{context} authorization"),
        review=_relative_path_string(payload, "review", f"{context} authorization"),
        max_core_hours=_non_negative_number(
            payload.get("max_core_hours"), f"{context} authorization max_core_hours"
        ),
    )


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with open(path, "rb") as stream:
            return tomllib.load(stream)
    except OSError as exc:
        raise SimctlError(f"Failed to read experiment TOML {path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise SimctlError(f"Invalid experiment TOML {path}: {exc}") from exc


def _required_string(payload: dict[str, Any], field: str, context: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise SimctlError(f"{context} requires non-empty {field}")
    return value.strip()


def _optional_string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _decision(value: object, context: str) -> ExperimentDecision:
    if value not in _DECISIONS:
        raise SimctlError(f"{context} decision must be WAIT/EXPAND/REVISE/STOP")
    return cast("ExperimentDecision", value)


def _non_negative_number(value: object, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise SimctlError(f"{context} must be non-negative")
    return float(value)


def _optional_non_negative_number(value: object, context: str) -> float | None:
    if value is None:
        return None
    return _non_negative_number(value, f"{context} cost_ceiling_core_hours")


def _relative_path_string(payload: dict[str, Any], field: str, context: str) -> Path:
    value = _required_string(payload, field, context)
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise SimctlError(f"{context} {field} path must be project-relative")
    return path


def _optional_relative_path_string(
    payload: dict[str, Any], field: str, context: str
) -> Path | None:
    value = _optional_string(payload.get(field))
    if value is None:
        return None
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise SimctlError(f"{context} {field} path must be project-relative")
    return path


def _validate_selected(
    selected: str, candidates: tuple[ExperimentCandidate, ...], context: str
) -> None:
    if selected not in {candidate.id for candidate in candidates}:
        raise SimctlError(f"{context} selected_candidate must name a candidate")
