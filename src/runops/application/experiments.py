"""Minimal experiment admission, review, and closure services."""

from __future__ import annotations

import contextlib
import fcntl
import math
import os
import re
import stat
import sys
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import tomli_w

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from runops.application.run_discovery import resolve_project_run_strict
from runops.application.state_root import require_project_state_root
from runops.core.exceptions import SimctlError
from runops.core.experiment import (
    ExperimentData,
    discover_experiments,
    load_experiment,
    parse_experiment_timestamp,
)
from runops.core.project import load_project

_EXPERIMENT_ID = re.compile(r"^E(?P<date>\d{8})-(?P<sequence>\d{4})$")
_RUN_ID = re.compile(r"^R\d{8}-\d{4}$")
_VALID_INTENTS = frozenset({"explore", "confirm", "validate", "reproduce"})
_VALID_DECISIONS = frozenset({"pending", "expand", "revise", "stop", "accept"})
_VALID_OUTCOMES = frozenset(
    {"unknown", "supported", "refuted", "inconclusive", "invalid"}
)
_SEQUENCE_FILE = "experiment-id-sequence.toml"


class ExperimentWorkflowError(SimctlError):
    """Raised when an experiment workflow precondition is not satisfied."""


@dataclass(frozen=True)
class ExperimentMutation:
    """Result of one experiment mutation."""

    experiment: ExperimentData
    path: Path


def create_experiment(
    project_root: Path,
    *,
    title: str,
    question: str,
    intent: str,
    baseline_run_ids: tuple[str, ...] = (),
    baseline_reason: str = "",
    max_planned_points: int,
    max_materialized_runs: int,
    max_active_runs: int,
    max_core_hours: float,
    max_unreviewed_runs: int,
    expires_at: str,
    exit_criteria: tuple[str, ...],
    review_due: str = "",
    created_by: str = "human",
    now: datetime | None = None,
) -> ExperimentMutation:
    """Admit one bounded research question as an active Experiment.

    There is deliberately no CLI path that persists an unbounded idea or an
    empty draft.  Provisional ideas belong in ``.runops/work``.
    """
    root = project_root.resolve()
    project = load_project(root)
    clean_title = title.strip()
    clean_question = question.strip()
    clean_exit = tuple(item.strip() for item in exit_criteria if item.strip())
    clean_baseline_reason = baseline_reason.strip()
    clean_expires_at = expires_at.strip()
    timestamp = (now or datetime.now(tz=timezone.utc)).astimezone(timezone.utc)
    if not clean_title:
        raise ExperimentWorkflowError("experiment title must not be empty")
    if not clean_question:
        raise ExperimentWorkflowError("experiment question must not be empty")
    if intent not in _VALID_INTENTS:
        raise ExperimentWorkflowError(
            f"experiment intent must be one of {sorted(_VALID_INTENTS)}"
        )
    if bool(baseline_run_ids) == bool(clean_baseline_reason):
        raise ExperimentWorkflowError(
            "an experiment requires exactly one of baseline Run IDs or a "
            "baseline-not-required reason"
        )
    if not clean_exit:
        raise ExperimentWorkflowError(
            "an experiment requires at least one explicit exit criterion"
        )
    try:
        expiry = parse_experiment_timestamp(clean_expires_at)
    except ValueError as exc:
        raise ExperimentWorkflowError(
            "experiment expires_at must be an ISO-8601 timestamp"
        ) from exc
    if expiry.tzinfo is None or expiry.utcoffset() is None:
        raise ExperimentWorkflowError("experiment expires_at must include a UTC offset")
    if expiry.astimezone(timezone.utc) <= timestamp:
        raise ExperimentWorkflowError(
            "experiment expires_at must be later than its admission time"
        )
    if any(_RUN_ID.fullmatch(run_id) is None for run_id in baseline_run_ids):
        raise ExperimentWorkflowError("baseline Run IDs must match RYYYYMMDD-NNNN")
    if len(set(baseline_run_ids)) != len(baseline_run_ids):
        raise ExperimentWorkflowError("baseline Run IDs must be unique")
    for run_id in baseline_run_ids:
        try:
            _run_dir, manifest = resolve_project_run_strict(root, run_id)
            status = str(manifest.run.get("status", ""))
        except SimctlError as exc:
            raise ExperimentWorkflowError(
                f"baseline Run {run_id} is not resolvable: {exc}"
            ) from exc
        if status not in {"completed", "archived", "purged"}:
            raise ExperimentWorkflowError(
                f"baseline Run {run_id} must be completed-equivalent, found {status!r}"
            )
    _validate_budget(
        max_planned_points=max_planned_points,
        max_materialized_runs=max_materialized_runs,
        max_active_runs=max_active_runs,
        max_core_hours=max_core_hours,
        max_unreviewed_runs=max_unreviewed_runs,
    )

    with experiment_lock(root):
        existing = discover_experiments(root)
        active_count = sum(item.lifecycle == "active" for item in existing)
        if active_count >= project.experiment_policy.max_active_experiments:
            raise ExperimentWorkflowError(
                "active Experiment WIP limit reached: "
                f"{active_count}/{project.experiment_policy.max_active_experiments}"
            )
        experiment_id = _reserve_experiment_id(root, existing, timestamp)
        experiments_root = root / "experiments"
        experiments_root.mkdir(parents=True, exist_ok=True)
        destination = experiments_root / (
            f"{experiment_id}--{_slugify(clean_title)}.toml"
        )
        payload: dict[str, Any] = {
            "schema_version": 1,
            "experiment": {
                "id": experiment_id,
                "title": clean_title,
                "question": clean_question,
                "lifecycle": "active",
                "intent": intent,
                "decision": "pending",
                "outcome": "unknown",
                "created_at": timestamp.isoformat(),
                "created_by": created_by.strip() or "human",
            },
            "baseline": {
                "run_ids": list(baseline_run_ids),
                "reason": clean_baseline_reason,
            },
            "budget": {
                "max_planned_points": max_planned_points,
                "max_materialized_runs": max_materialized_runs,
                "max_active_runs": max_active_runs,
                "max_core_hours": float(max_core_hours),
                "max_unreviewed_runs": max_unreviewed_runs,
                "expires_at": clean_expires_at,
            },
            "exit": {
                "criteria": list(clean_exit),
                "review_due": review_due.strip(),
            },
            "review": {
                "reason": "",
                "reviewed_at": "",
                "successor": "",
            },
        }
        _write_new_toml(destination, payload)

    return ExperimentMutation(
        experiment=load_experiment(destination),
        path=destination,
    )


def review_experiment(
    project_root: Path,
    experiment: str,
    *,
    decision: str,
    reason: str,
    outcome: str = "unknown",
    successor: str = "",
    now: datetime | None = None,
) -> ExperimentMutation:
    """Record the latest structured decision without closing the Experiment."""
    clean_reason = reason.strip()
    if decision not in _VALID_DECISIONS - {"pending"}:
        raise ExperimentWorkflowError(f"invalid experiment decision: {decision!r}")
    if outcome not in _VALID_OUTCOMES:
        raise ExperimentWorkflowError(f"invalid experiment outcome: {outcome!r}")
    if not clean_reason:
        raise ExperimentWorkflowError("experiment review reason must not be empty")
    root = project_root.resolve()
    with experiment_lock(root):
        path = resolve_experiment(root, experiment)
        current = load_experiment(path)
        if current.lifecycle != "active":
            raise ExperimentWorkflowError(
                f"experiment {current.id} is {current.lifecycle!r}; expected 'active'"
            )
        payload = _updated_experiment_payload(
            current,
            decision=decision,
            outcome=outcome,
            reason=clean_reason,
            successor=successor.strip(),
            reviewed_at=(now or datetime.now(tz=timezone.utc)).isoformat(),
        )
        _replace_toml(path, payload)
    return ExperimentMutation(load_experiment(path), path)


def close_experiment(
    project_root: Path,
    experiment: str,
    *,
    decision: str,
    outcome: str,
    reason: str,
    successor: str = "",
    now: datetime | None = None,
) -> ExperimentMutation:
    """Close an Experiment as a research decision without moving Run files."""
    if decision not in _VALID_DECISIONS - {"pending", "expand"}:
        raise ExperimentWorkflowError(
            "closing decision must be revise, stop, or accept"
        )
    if outcome not in _VALID_OUTCOMES - {"unknown"}:
        raise ExperimentWorkflowError(
            "closing outcome must be supported, refuted, inconclusive, or invalid"
        )
    clean_reason = reason.strip()
    if not clean_reason:
        raise ExperimentWorkflowError("experiment close reason must not be empty")
    root = project_root.resolve()
    timestamp = (now or datetime.now(tz=timezone.utc)).isoformat()
    with experiment_lock(root):
        path = resolve_experiment(root, experiment)
        current = load_experiment(path)
        if current.lifecycle != "active":
            raise ExperimentWorkflowError(
                f"experiment {current.id} is {current.lifecycle!r}; expected 'active'"
            )
        payload = _updated_experiment_payload(
            current,
            decision=decision,
            outcome=outcome,
            reason=clean_reason,
            successor=successor.strip(),
            reviewed_at=timestamp,
        )
        experiment_section = payload.setdefault("experiment", {})
        experiment_section["lifecycle"] = "closed"
        experiment_section["closed_at"] = timestamp
        _replace_toml(path, payload)
    return ExperimentMutation(load_experiment(path), path)


def resolve_experiment(project_root: Path, identifier: str) -> Path:
    """Resolve an Experiment ID or an explicit file path without ambiguity."""
    root = project_root.resolve()
    raw_candidate = Path(identifier)
    candidate = raw_candidate if raw_candidate.is_absolute() else root / raw_candidate
    if candidate.exists():
        if candidate.is_symlink() or not candidate.is_file():
            raise ExperimentWorkflowError(f"unsafe experiment path: {candidate}")
        path = candidate.resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ExperimentWorkflowError(
                f"experiment path is outside the project: {path}"
            ) from exc
        return path
    matches = [
        item.experiment_file
        for item in discover_experiments(root)
        if item.id == identifier
    ]
    if not matches:
        raise ExperimentWorkflowError(f"experiment not found: {identifier}")
    if len(matches) > 1:
        raise ExperimentWorkflowError(f"duplicate experiment ID: {identifier}")
    return matches[0]


def _reserve_experiment_id(
    project_root: Path,
    existing: tuple[ExperimentData, ...],
    timestamp: datetime,
) -> str:
    """Reserve and durably burn a project-wide Experiment identity."""
    date_key = timestamp.strftime("%Y%m%d")
    maximum = 0
    for item in existing:
        match = _EXPERIMENT_ID.fullmatch(item.id)
        if match is None or match.group("date") != date_key:
            continue
        maximum = max(maximum, int(match.group("sequence")))
    sequence_path = project_root / ".runops" / _SEQUENCE_FILE
    ledger = _read_sequence_ledger(sequence_path)
    dates = ledger.setdefault("dates", {})
    if not isinstance(dates, dict):
        raise ExperimentWorkflowError(
            f"invalid dates table in Experiment identity ledger {sequence_path}"
        )
    stored = dates.get(date_key, 0)
    if isinstance(stored, bool) or not isinstance(stored, int) or stored < 0:
        raise ExperimentWorkflowError(
            f"invalid sequence for {date_key!r} in {sequence_path}"
        )
    sequence = max(maximum, stored) + 1
    if sequence > 9999:
        raise ExperimentWorkflowError(
            f"experiment sequence overflow for {date_key}: maximum 9999"
        )
    dates[date_key] = sequence
    _replace_toml(sequence_path, ledger)
    return f"E{date_key}-{sequence:04d}"


def _read_sequence_ledger(path: Path) -> dict[str, Any]:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return {"schema_version": 1, "dates": {}}
    except OSError as exc:
        raise ExperimentWorkflowError(
            f"failed to inspect Experiment identity ledger {path}: {exc}"
        ) from exc
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise ExperimentWorkflowError(
            f"Experiment identity ledger must be a single-link regular file: {path}"
        )
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if (
                opened.st_dev != metadata.st_dev
                or opened.st_ino != metadata.st_ino
                or opened.st_nlink != 1
                or not stat.S_ISREG(opened.st_mode)
            ):
                raise ExperimentWorkflowError(
                    f"Experiment identity ledger changed while opening: {path}"
                )
            payload = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ExperimentWorkflowError(
            f"failed to read Experiment identity ledger {path}: {exc}"
        ) from exc
    version = payload.get("schema_version", 1)
    if type(version) is not int or version != 1:
        raise ExperimentWorkflowError(
            f"unsupported Experiment identity ledger schema in {path}"
        )
    return dict(payload)


def _validate_budget(**values: int | float) -> None:
    unreviewed = values.pop("max_unreviewed_runs")
    if (
        isinstance(unreviewed, bool)
        or not isinstance(unreviewed, int)
        or unreviewed < 0
    ):
        raise ExperimentWorkflowError("max_unreviewed_runs must be non-negative")
    discrete = {
        "max_planned_points",
        "max_materialized_runs",
        "max_active_runs",
    }
    for name, value in values.items():
        if (
            isinstance(value, bool)
            or (name in discrete and not isinstance(value, int))
            or (name not in discrete and not isinstance(value, (int, float)))
            or not math.isfinite(value)
            or value <= 0
        ):
            requirement = "a positive integer" if name in discrete else "positive"
            raise ExperimentWorkflowError(f"{name} must be {requirement}")
    planned = values["max_planned_points"]
    materialized = values["max_materialized_runs"]
    active = values["max_active_runs"]
    if materialized > planned:
        raise ExperimentWorkflowError(
            "max_materialized_runs must not exceed max_planned_points"
        )
    if active > materialized:
        raise ExperimentWorkflowError(
            "max_active_runs must not exceed max_materialized_runs"
        )


def _updated_experiment_payload(
    current: ExperimentData,
    *,
    decision: str,
    outcome: str,
    reason: str,
    successor: str,
    reviewed_at: str,
) -> dict[str, Any]:
    payload = _deep_copy_mapping(current.raw)
    experiment = payload.setdefault("experiment", {})
    experiment["decision"] = decision
    experiment["outcome"] = outcome
    review = payload.setdefault("review", {})
    review["reason"] = reason
    review["reviewed_at"] = reviewed_at
    review["successor"] = successor
    return payload


def _deep_copy_mapping(value: dict[str, Any]) -> dict[str, Any]:
    import copy

    return copy.deepcopy(value)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug[:48] or "experiment"


@contextlib.contextmanager
def experiment_lock(project_root: Path) -> Iterator[None]:
    """Serialize Experiment mutation and formal Run budget admission."""
    state_dir = require_project_state_root(project_root)
    path = state_dir / "experiments.lock"
    flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise ExperimentWorkflowError(
            f"failed to open Experiment lock {path}: {exc}"
        ) from exc
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        with contextlib.suppress(OSError):
            os.close(descriptor)


def _write_new_toml(path: Path, payload: dict[str, Any]) -> None:
    descriptor, temporary = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            tomli_w.dump(payload, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path, follow_symlinks=False)
        os.unlink(temporary)
        _fsync_directory(path.parent)
    except (OSError, TypeError) as exc:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise ExperimentWorkflowError(f"failed to create {path}: {exc}") from exc


def _replace_toml(path: Path, payload: dict[str, Any]) -> None:
    descriptor, temporary = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            tomli_w.dump(payload, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    except (OSError, TypeError) as exc:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise ExperimentWorkflowError(f"failed to update {path}: {exc}") from exc


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
