"""Bounded Experiment definitions for the Execution Kernel.

An Experiment is deliberately a small, single-file admission and review unit.
It is not the removed proposal/review workflow ledger.  Candidate ideas remain
outside this module until they have a question, baseline, finite budget, and
exit criteria that can be parsed from one ``experiment.toml``-shaped file.
"""

from __future__ import annotations

import copy
import math
import os
import re
import stat
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, cast

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from runops.core.exceptions import ExperimentConfigError

ExperimentLifecycle = Literal["draft", "active", "closed"]
ExperimentIntent = Literal["explore", "confirm", "validate", "reproduce"]
ExperimentDecision = Literal["pending", "expand", "revise", "stop", "accept"]
ExperimentOutcome = Literal[
    "unknown",
    "supported",
    "refuted",
    "inconclusive",
    "invalid",
]

_EXPERIMENT_ID_RE = re.compile(r"^E\d{8}-\d{4}$")
_RUN_ID_RE = re.compile(r"^R\d{8}-\d{4}$")
_EXPERIMENT_FILE_RE = re.compile(
    r"^(?P<id>E\d{8}-\d{4})(?:--[a-z0-9][a-z0-9-]*)?\.toml$"
)
_LIFECYCLES = frozenset({"draft", "active", "closed"})
_INTENTS = frozenset({"explore", "confirm", "validate", "reproduce"})
_DECISIONS = frozenset({"pending", "expand", "revise", "stop", "accept"})
_OUTCOMES = frozenset({"unknown", "supported", "refuted", "inconclusive", "invalid"})


@dataclass(frozen=True)
class ExperimentBaseline:
    """Either concrete baseline runs or an explicit reason for having none."""

    run_ids: tuple[str, ...] = ()
    reason: str = ""


@dataclass(frozen=True)
class ExperimentBudget:
    """Finite resource envelope approved for one Experiment."""

    max_planned_points: int
    max_materialized_runs: int
    max_active_runs: int
    max_core_hours: float
    max_unreviewed_runs: int
    expires_at: str


@dataclass(frozen=True)
class ExperimentData:
    """Validated, immutable view of one Experiment definition."""

    id: str
    title: str
    question: str
    lifecycle: ExperimentLifecycle
    intent: ExperimentIntent
    decision: ExperimentDecision
    outcome: ExperimentOutcome
    baseline: ExperimentBaseline
    budget: ExperimentBudget
    exit_criteria: tuple[str, ...]
    review_due: str
    experiment_file: Path
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


def load_experiment(experiment_file: Path) -> ExperimentData:
    """Load one ``experiments/EYYYYMMDD-NNNN--slug.toml`` definition."""
    experiment_file = Path(os.path.abspath(experiment_file.expanduser()))
    _require_safe_experiment_file(experiment_file)
    experiment_file = experiment_file.resolve(strict=True)

    try:
        with experiment_file.open("rb") as stream:
            raw = tomllib.load(stream)
    except tomllib.TOMLDecodeError as exc:
        raise ExperimentConfigError(
            f"Invalid TOML in {experiment_file}: {exc}"
        ) from exc
    except UnicodeDecodeError as exc:
        raise ExperimentConfigError(
            f"Invalid encoding in {experiment_file}: {exc}"
        ) from exc
    except OSError as exc:
        raise ExperimentConfigError(f"Failed to read {experiment_file}: {exc}") from exc

    schema_version = raw.get("schema_version")
    if type(schema_version) is not int or schema_version != 1:
        raise ExperimentConfigError(
            f"schema_version must be integer 1 in {experiment_file}"
        )

    experiment = _required_table(raw, "experiment", experiment_file)
    experiment_id = _required_non_empty_string(
        experiment,
        "id",
        "experiment.id",
        experiment_file,
    )
    if _EXPERIMENT_ID_RE.fullmatch(experiment_id) is None:
        raise ExperimentConfigError(
            f"experiment.id must match EYYYYMMDD-NNNN in {experiment_file}"
        )
    filename_match = _EXPERIMENT_FILE_RE.fullmatch(experiment_file.name)
    if filename_match is None or filename_match.group("id") != experiment_id:
        raise ExperimentConfigError(
            "Experiment filename must start with its immutable experiment.id "
            f"({experiment_id}) in {experiment_file}"
        )

    lifecycle = _parse_enum(
        experiment,
        "lifecycle",
        "experiment.lifecycle",
        _LIFECYCLES,
        experiment_file,
    )
    intent = _parse_enum(
        experiment,
        "intent",
        "experiment.intent",
        _INTENTS,
        experiment_file,
    )
    decision = _parse_enum(
        experiment,
        "decision",
        "experiment.decision",
        _DECISIONS,
        experiment_file,
    )
    outcome = _parse_enum(
        experiment,
        "outcome",
        "experiment.outcome",
        _OUTCOMES,
        experiment_file,
    )
    title_value = experiment.get("title", "")
    if not isinstance(title_value, str):
        raise ExperimentConfigError(
            f"experiment.title must be a string in {experiment_file}"
        )

    question = _required_non_empty_string(
        experiment,
        "question",
        "experiment.question",
        experiment_file,
    )
    baseline = _parse_baseline(raw, experiment_file)
    budget = _parse_budget(raw, experiment_file)
    exit_section = _required_table(raw, "exit", experiment_file)
    exit_criteria = _required_non_empty_string_list(
        exit_section,
        "criteria",
        "exit.criteria",
        experiment_file,
    )
    raw_review_due = exit_section.get("review_due", "")
    if not isinstance(raw_review_due, str):
        raise ExperimentConfigError(
            f"exit.review_due must be a string in {experiment_file}"
        )
    review_due = raw_review_due.strip()

    return ExperimentData(
        id=experiment_id,
        title=title_value.strip(),
        question=question,
        lifecycle=cast("ExperimentLifecycle", lifecycle),
        intent=cast("ExperimentIntent", intent),
        decision=cast("ExperimentDecision", decision),
        outcome=cast("ExperimentOutcome", outcome),
        baseline=baseline,
        budget=budget,
        exit_criteria=exit_criteria,
        review_due=review_due,
        experiment_file=experiment_file,
        raw=copy.deepcopy(raw),
    )


def experiment_is_expired(
    experiment: ExperimentData,
    *,
    now: datetime | None = None,
) -> bool:
    """Return whether a validated Experiment has reached its admission deadline."""
    timestamp = now or datetime.now(tz=timezone.utc)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("Experiment expiry comparison requires a timezone-aware time")
    deadline = parse_experiment_timestamp(experiment.budget.expires_at)
    return timestamp.astimezone(timezone.utc) >= deadline.astimezone(timezone.utc)


def parse_experiment_timestamp(value: str) -> datetime:
    """Parse an ISO-8601 timestamp consistently on every supported Python."""
    normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(normalized)


def discover_experiments(project_root: Path) -> tuple[ExperimentData, ...]:
    """Discover Experiment files below ``<project>/experiments``.

    The directory may be reorganized, but the ID embedded in each filename and
    file body remains immutable and unique within the project.
    """
    lexical_root = project_root.resolve() / "experiments"
    try:
        root_metadata = lexical_root.lstat()
    except FileNotFoundError:
        return ()
    except OSError as exc:
        raise ExperimentConfigError(
            f"Cannot inspect Experiment root {lexical_root}: {exc}"
        ) from exc
    if stat.S_ISLNK(root_metadata.st_mode) or not stat.S_ISDIR(root_metadata.st_mode):
        raise ExperimentConfigError(
            "Experiment root must be a real directory, not a symbolic link or "
            f"another file type: {lexical_root}"
        )
    experiments_root = lexical_root.resolve(strict=True)

    def raise_walk_error(error: OSError) -> None:
        raise ExperimentConfigError(
            f"Cannot safely walk Experiment definitions in {experiments_root}: {error}"
        ) from error

    discovered: list[ExperimentData] = []
    by_id: dict[str, Path] = {}
    for dirpath, dirnames, filenames in os.walk(
        experiments_root,
        topdown=True,
        onerror=raise_walk_error,
        followlinks=False,
    ):
        current = Path(dirpath)
        _require_safe_experiment_directory(current, experiments_root)
        dirnames[:] = sorted(dirnames)
        for dirname in dirnames:
            _require_safe_experiment_directory(
                current / dirname,
                experiments_root,
            )
        for filename in sorted(filenames):
            if not filename.endswith(".toml"):
                continue
            experiment_file = current / filename
            _require_safe_experiment_file(experiment_file)
            experiment = load_experiment(experiment_file)
            previous = by_id.get(experiment.id)
            if previous is not None:
                raise ExperimentConfigError(
                    f"Duplicate experiment id {experiment.id!r} found at "
                    f"{previous} and {experiment.experiment_file}"
                )
            by_id[experiment.id] = experiment.experiment_file
            discovered.append(experiment)
    return tuple(sorted(discovered, key=lambda item: str(item.experiment_file)))


def _require_safe_experiment_directory(path: Path, root: Path) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ExperimentConfigError(
            f"Cannot inspect Experiment namespace directory {path}: {exc}"
        ) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ExperimentConfigError(f"Unsafe directory in Experiment namespace: {path}")
    try:
        path.resolve(strict=True).relative_to(root)
    except (OSError, ValueError) as exc:
        raise ExperimentConfigError(
            f"Experiment namespace directory escapes its root: {path}"
        ) from exc


def _require_safe_experiment_file(path: Path) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise ExperimentConfigError(f"Experiment file not found: {path}") from exc
    except OSError as exc:
        raise ExperimentConfigError(
            f"Cannot inspect Experiment file {path}: {exc}"
        ) from exc
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise ExperimentConfigError(
            "Experiment definition must be a single-link regular file, not a "
            f"symbolic link or another file type: {path}"
        )


def _parse_baseline(raw: dict[str, Any], path: Path) -> ExperimentBaseline:
    section = _required_table(raw, "baseline", path)
    raw_run_ids = section.get("run_ids", [])
    raw_reason = section.get("reason", "")
    if not isinstance(raw_run_ids, list) or not all(
        isinstance(item, str) for item in raw_run_ids
    ):
        raise ExperimentConfigError(
            f"baseline.run_ids must be a string array in {path}"
        )
    if not isinstance(raw_reason, str):
        raise ExperimentConfigError(f"baseline.reason must be a string in {path}")
    has_run_ids = bool(raw_run_ids)
    has_reason = bool(raw_reason.strip())
    if has_run_ids == has_reason:
        raise ExperimentConfigError(
            "[baseline] must provide exactly one non-empty baseline source: "
            f"run_ids or reason in {path}"
        )
    if has_run_ids:
        run_ids = tuple(item.strip() for item in cast("list[str]", raw_run_ids))
        if any(_RUN_ID_RE.fullmatch(run_id) is None for run_id in run_ids):
            raise ExperimentConfigError(
                f"baseline.run_ids must contain RYYYYMMDD-NNNN IDs in {path}"
            )
        if len(set(run_ids)) != len(run_ids):
            raise ExperimentConfigError(
                f"baseline.run_ids must not contain duplicate IDs in {path}"
            )
        return ExperimentBaseline(run_ids=run_ids)
    return ExperimentBaseline(reason=raw_reason.strip())


def _parse_budget(raw: dict[str, Any], path: Path) -> ExperimentBudget:
    section = _required_table(raw, "budget", path)
    max_planned_points = _required_positive_int(
        section, "max_planned_points", "budget.max_planned_points", path
    )
    max_materialized_runs = _required_positive_int(
        section, "max_materialized_runs", "budget.max_materialized_runs", path
    )
    max_active_runs = _required_positive_int(
        section, "max_active_runs", "budget.max_active_runs", path
    )
    max_core_hours = _required_positive_number(
        section, "max_core_hours", "budget.max_core_hours", path
    )
    max_unreviewed_runs = _required_non_negative_int(
        section, "max_unreviewed_runs", "budget.max_unreviewed_runs", path
    )
    expires_at = _required_timezone_aware_timestamp(
        section,
        "expires_at",
        "budget.expires_at",
        path,
    )
    if max_materialized_runs > max_planned_points:
        raise ExperimentConfigError(
            f"budget.max_materialized_runs must not exceed max_planned_points in {path}"
        )
    if max_active_runs > max_materialized_runs:
        raise ExperimentConfigError(
            f"budget.max_active_runs must not exceed max_materialized_runs in {path}"
        )
    return ExperimentBudget(
        max_planned_points=max_planned_points,
        max_materialized_runs=max_materialized_runs,
        max_active_runs=max_active_runs,
        max_core_hours=max_core_hours,
        max_unreviewed_runs=max_unreviewed_runs,
        expires_at=expires_at,
    )


def _required_table(
    raw: dict[str, Any],
    name: str,
    path: Path,
) -> dict[str, Any]:
    value = raw.get(name)
    if not isinstance(value, dict):
        raise ExperimentConfigError(f"Missing or invalid [{name}] section in {path}")
    return value


def _required_non_empty_string(
    section: dict[str, Any],
    key: str,
    label: str,
    path: Path,
) -> str:
    value = section.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ExperimentConfigError(f"{label} must be a non-empty string in {path}")
    return value.strip()


def _required_timezone_aware_timestamp(
    section: dict[str, Any],
    key: str,
    label: str,
    path: Path,
) -> str:
    value = _required_non_empty_string(section, key, label, path)
    try:
        timestamp = parse_experiment_timestamp(value)
    except ValueError as exc:
        raise ExperimentConfigError(
            f"{label} must be an ISO-8601 timestamp in {path}"
        ) from exc
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ExperimentConfigError(f"{label} must include a UTC offset in {path}")
    return value


def _required_non_empty_string_list(
    section: dict[str, Any],
    key: str,
    label: str,
    path: Path,
) -> tuple[str, ...]:
    value = section.get(key)
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item.strip() for item in value)
    ):
        raise ExperimentConfigError(
            f"{label} must be a non-empty array of non-empty strings in {path}"
        )
    return tuple(item.strip() for item in cast("list[str]", value))


def _parse_enum(
    section: dict[str, Any],
    key: str,
    label: str,
    allowed: frozenset[str],
    path: Path,
) -> str:
    value = section.get(key)
    if not isinstance(value, str) or value not in allowed:
        raise ExperimentConfigError(
            f"{label} must be one of {sorted(allowed)} in {path}"
        )
    return value


def _required_positive_int(
    section: dict[str, Any],
    key: str,
    label: str,
    path: Path,
) -> int:
    value = section.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ExperimentConfigError(f"{label} must be a positive integer in {path}")
    return value


def _required_non_negative_int(
    section: dict[str, Any],
    key: str,
    label: str,
    path: Path,
) -> int:
    value = section.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ExperimentConfigError(f"{label} must be a non-negative integer in {path}")
    return value


def _required_positive_number(
    section: dict[str, Any],
    key: str,
    label: str,
    path: Path,
) -> float:
    value = section.get(key)
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ExperimentConfigError(f"{label} must be a positive number in {path}")
    return float(value)


__all__ = [
    "ExperimentBaseline",
    "ExperimentBudget",
    "ExperimentConfigError",
    "ExperimentData",
    "ExperimentDecision",
    "ExperimentIntent",
    "ExperimentLifecycle",
    "ExperimentOutcome",
    "discover_experiments",
    "experiment_is_expired",
    "load_experiment",
    "parse_experiment_timestamp",
]
