"""Project-wide Experiment budget accounting for every formal Run path."""

from __future__ import annotations

import contextlib
import math
import os
import stat
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomli_w

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from runops.application.run_discovery import collect_run_manifests_strict
from runops.application.run_namespace import run_namespace_guard
from runops.application.state_root import require_project_state_root
from runops.core.case import parse_walltime_hours
from runops.core.exceptions import SimctlError
from runops.core.experiment import ExperimentData
from runops.core.manifest import ManifestData
from runops.core.project import ProjectConfig
from runops.core.run.curation import has_valid_run_review

_ACTIVE_RUN_STATES = frozenset({"created", "submitted", "running"})
_COMPLETED_EQUIVALENT_STATES = frozenset({"completed", "archived", "purged"})
_USAGE_FILE = "experiment-usage.toml"


@dataclass(frozen=True)
class ExperimentRunRecord:
    """One formal Run counted against an Experiment budget."""

    run_dir: Path
    manifest: ManifestData


def collect_experiment_run_records(
    project_root: Path,
    experiment_id: str,
) -> tuple[ExperimentRunRecord, ...]:
    """Collect all active and cold Run manifests owned by an Experiment."""
    return tuple(
        record
        for record in _collect_project_run_records(project_root)
        if record.manifest.intent.get("experiment_id") == experiment_id
    )


def _collect_project_run_records(
    project_root: Path,
) -> tuple[ExperimentRunRecord, ...]:
    """Collect one strict snapshot of every formal Run in the project."""
    with run_namespace_guard(project_root):
        return tuple(
            ExperimentRunRecord(run_dir, manifest)
            for run_dir, manifest in collect_run_manifests_strict(project_root / "runs")
        )


def _resolve_budget_record_sets(
    project_root: Path,
    experiment_id: str,
    supplied_owner_records: tuple[ExperimentRunRecord, ...] | None,
) -> tuple[tuple[ExperimentRunRecord, ...], tuple[ExperimentRunRecord, ...]]:
    """Return project-global and current-owner views of one strict snapshot.

    ``records`` remains an accepted pre-collected-owner API for existing
    callers, but it cannot suppress the project-wide scan.  A stale or partial
    supplied view is rejected instead of being used to undercount an
    Experiment budget.
    """
    project_records = _collect_project_run_records(project_root)
    owner_records = tuple(
        record
        for record in project_records
        if record.manifest.intent.get("experiment_id") == experiment_id
    )
    if supplied_owner_records is not None:
        supplied_keys = tuple(
            sorted(_record_key(record) for record in supplied_owner_records)
        )
        owner_keys = tuple(sorted(_record_key(record) for record in owner_records))
        if supplied_keys != owner_keys:
            raise SimctlError(
                "pre-collected Experiment Run records do not match the strict "
                f"formal Run namespace for {experiment_id}"
            )
    return project_records, owner_records


def _record_key(record: ExperimentRunRecord) -> tuple[str, str]:
    return (
        str(record.run_dir),
        str(record.manifest.run.get("id", "")).strip(),
    )


def _is_unreviewed_completed(record: ExperimentRunRecord) -> bool:
    return record.manifest.run.get(
        "status"
    ) in _COMPLETED_EQUIVALENT_STATES and not has_valid_run_review(
        record.manifest.curation
    )


def _enforce_unreviewed_completed_caps(
    project: ProjectConfig,
    experiment: ExperimentData,
    *,
    project_records: tuple[ExperimentRunRecord, ...],
    owner_records: tuple[ExperimentRunRecord, ...],
) -> None:
    _enforce_project_unreviewed_completed_cap(project, project_records)

    experiment_unreviewed = sum(map(_is_unreviewed_completed, owner_records))
    experiment_cap = experiment.budget.max_unreviewed_runs
    if experiment_unreviewed >= experiment_cap and experiment_unreviewed > 0:
        raise SimctlError(
            "Experiment unreviewed completed Run backlog reached its limit: "
            f"{experiment_unreviewed}/{experiment_cap}"
        )


def _enforce_project_unreviewed_completed_cap(
    project: ProjectConfig,
    project_records: tuple[ExperimentRunRecord, ...],
) -> None:
    """Apply the owner-independent project backlog gate to one strict snapshot."""
    project_unreviewed = sum(map(_is_unreviewed_completed, project_records))
    project_cap = project.experiment_policy.max_unreviewed_completed_runs
    if project_unreviewed >= project_cap and project_unreviewed > 0:
        raise SimctlError(
            "project-wide unreviewed completed Run backlog reached its limit: "
            f"{project_unreviewed}/{project_cap}"
        )


def enforce_project_unreviewed_completed_budget(project: ProjectConfig) -> None:
    """Enforce project-wide review WIP for an ownerless formal Run action.

    The strict scan is intentional.  Missing, unsafe, or unreadable namespace
    entries must block admission instead of turning an unknown backlog into
    zero.
    """
    _enforce_project_unreviewed_completed_cap(
        project,
        _collect_project_run_records(project.root_dir),
    )


def enforce_experiment_run_budget(
    project: ProjectConfig,
    experiment: ExperimentData,
    *,
    new_count: int,
    new_core_hours: float,
    reservation_tokens: tuple[str, ...],
    records: tuple[ExperimentRunRecord, ...] | None = None,
    persist: bool = True,
) -> None:
    """Fail closed when new formal Runs would exceed a cognitive/resource cap.

    Callers must hold the project Experiment lock from validation through the
    final Run commit.  Counting archived/purged manifests is intentional:
    storage movement or compaction must not create fresh scientific budget.
    """
    if new_count < 0 or not math.isfinite(new_core_hours) or new_core_hours < 0:
        raise SimctlError("formal Run budget increments must be non-negative")
    clean_tokens = tuple(token.strip() for token in reservation_tokens)
    if len(clean_tokens) != new_count or any(not token for token in clean_tokens):
        raise SimctlError(
            "formal Run budget requires one non-empty reservation token per Run"
        )
    if len(set(clean_tokens)) != len(clean_tokens):
        raise SimctlError("formal Run budget reservation tokens must be unique")
    project_records, known = _resolve_budget_record_sets(
        project.root_dir,
        experiment.id,
        records,
    )

    usage_path = require_project_state_root(project.root_dir) / _USAGE_FILE
    usage = _read_usage_ledger(usage_path)
    reservations = _experiment_reservations(usage, experiment.id)
    by_token = {str(item["token"]): item for item in reservations}
    changed = False
    for record in known:
        changed = (
            _backfill_manifest_reservations(reservations, by_token, record) or changed
        )

    per_run_hours = new_core_hours / new_count if new_count else 0.0
    new_tokens = [token for token in clean_tokens if token not in by_token]
    for token in clean_tokens:
        existing = by_token.get(token)
        if existing is None:
            continue
        recorded_hours = float(existing["core_hours"])
        if not math.isclose(
            recorded_hours, per_run_hours, rel_tol=1e-12, abs_tol=1e-12
        ):
            raise SimctlError(
                f"formal Run budget reservation {token!r} changed core-hour cost"
            )

    materialized = sum(item["kind"] == "run" for item in reservations)
    if materialized + len(new_tokens) > experiment.budget.max_materialized_runs:
        raise SimctlError(
            "Experiment materialization cap exceeded: "
            f"{materialized} reserved + {len(new_tokens)} new > "
            f"{experiment.budget.max_materialized_runs}"
        )
    active = sum(
        str(record.manifest.run.get("status", "")) in _ACTIVE_RUN_STATES
        for record in known
    )
    if active + new_count > experiment.budget.max_active_runs:
        raise SimctlError(
            "Experiment active Run WIP limit exceeded: "
            f"{active} active + {new_count} new > "
            f"{experiment.budget.max_active_runs}"
        )
    if new_count:
        _enforce_unreviewed_completed_caps(
            project,
            experiment,
            project_records=project_records,
            owner_records=known,
        )
    existing_hours = sum(float(item["core_hours"]) for item in reservations)
    added_hours = per_run_hours * len(new_tokens)
    if existing_hours + added_hours > experiment.budget.max_core_hours:
        raise SimctlError(
            "Experiment core-hour budget exceeded: "
            f"{existing_hours:g} reserved + {added_hours:g} new > "
            f"{experiment.budget.max_core_hours:g}"
        )

    for token in new_tokens:
        item: dict[str, str | float] = {
            "token": token,
            "core_hours": per_run_hours,
            "kind": "run",
        }
        reservations.append(item)
        by_token[token] = item
        changed = True
    if changed and persist:
        _write_usage_ledger(usage_path, usage)


def reserve_experiment_retry_budget(
    project: ProjectConfig,
    experiment: ExperimentData,
    *,
    manifest: ManifestData,
    next_attempt: int,
    records: tuple[ExperimentRunRecord, ...] | None = None,
    active_increment: int = 1,
    persist: bool = True,
) -> None:
    """Reserve one retry attempt without consuming another materialized-Run slot.

    A retry makes an existing terminal Run active again and consumes its full
    declared core-hour envelope.  The caller must hold ``experiment_lock``
    until the Run reset commits.  The attempt token makes a failed reset safe
    to retry without charging the same attempt twice.
    """
    if next_attempt < 1:
        raise SimctlError("retry budget requires a positive attempt number")
    if active_increment not in {0, 1}:
        raise SimctlError("retry budget active increment must be zero or one")
    run_id = str(manifest.run.get("id", "")).strip()
    if not run_id:
        raise SimctlError("retry budget requires an immutable run.id")
    project_records, known = _resolve_budget_record_sets(
        project.root_dir,
        experiment.id,
        records,
    )

    usage_path = require_project_state_root(project.root_dir) / _USAGE_FILE
    usage = _read_usage_ledger(usage_path)
    reservations = _experiment_reservations(usage, experiment.id)
    by_token = {str(item["token"]): item for item in reservations}
    changed = False
    for record in known:
        changed = (
            _backfill_manifest_reservations(reservations, by_token, record) or changed
        )

    active = sum(
        str(record.manifest.run.get("status", "")) in _ACTIVE_RUN_STATES
        for record in known
    )
    if active + active_increment > experiment.budget.max_active_runs:
        raise SimctlError(
            "Experiment active Run WIP limit exceeded by retry: "
            f"{active} active + {active_increment} retry > "
            f"{experiment.budget.max_active_runs}"
        )
    _enforce_unreviewed_completed_caps(
        project,
        experiment,
        project_records=project_records,
        owner_records=known,
    )

    token = f"attempt:{run_id}:{next_attempt}"
    core_hours = declared_manifest_core_hours(manifest)
    existing = by_token.get(token)
    if existing is not None:
        if existing["kind"] != "attempt" or not math.isclose(
            float(existing["core_hours"]),
            core_hours,
            rel_tol=1e-12,
            abs_tol=1e-12,
        ):
            raise SimctlError(
                f"retry budget reservation {token!r} changed kind or core-hour cost"
            )
    else:
        existing_hours = sum(float(item["core_hours"]) for item in reservations)
        if existing_hours + core_hours > experiment.budget.max_core_hours:
            raise SimctlError(
                "Experiment core-hour budget exceeded by retry: "
                f"{existing_hours:g} reserved + {core_hours:g} retry > "
                f"{experiment.budget.max_core_hours:g}"
            )
        if persist:
            reservations.append(
                {"token": token, "core_hours": core_hours, "kind": "attempt"}
            )
            changed = True
    if changed and persist:
        _write_usage_ledger(usage_path, usage)


def _backfill_manifest_reservations(
    reservations: list[dict[str, str | float]],
    by_token: dict[str, dict[str, str | float]],
    record: ExperimentRunRecord,
) -> bool:
    """Recover committed Run/attempt charges from one immutable manifest."""
    run_id = str(record.manifest.run.get("id", "")).strip()
    if not run_id:
        raise SimctlError(f"formal Run at {record.run_dir} has no immutable run.id")
    run_token = str(
        record.manifest.identity.get("budget_reservation", f"run:{run_id}")
    ).strip()
    if not run_token:
        raise SimctlError(
            f"formal Run {run_id} has an empty budget reservation identity"
        )
    core_hours = declared_manifest_core_hours(record.manifest)
    changed = False
    expected = [(run_token, "run")]
    raw_attempts = record.manifest.job.get("budget_attempts", [])
    if not isinstance(raw_attempts, list) or any(
        isinstance(value, bool) or not isinstance(value, int) or value < 1
        for value in raw_attempts
    ):
        raise SimctlError(f"formal Run {run_id} has invalid job.budget_attempts")
    if len(set(raw_attempts)) != len(raw_attempts):
        raise SimctlError(f"formal Run {run_id} repeats job.budget_attempts")
    expected.extend((f"attempt:{run_id}:{value}", "attempt") for value in raw_attempts)
    for token, kind in expected:
        current = by_token.get(token)
        if current is not None:
            if current["kind"] != kind or not math.isclose(
                float(current["core_hours"]),
                core_hours,
                rel_tol=1e-12,
                abs_tol=1e-12,
            ):
                raise SimctlError(
                    f"budget reservation {token!r} changed kind or core-hour cost"
                )
            continue
        item: dict[str, str | float] = {
            "token": token,
            "core_hours": core_hours,
            "kind": kind,
        }
        reservations.append(item)
        by_token[token] = item
        changed = True
    return changed


def persist_manifest_budget_usage(
    project_root: Path,
    run_dir: Path,
    manifest: ManifestData,
) -> None:
    """Durably transfer one Run's monotonic budget charges from its manifest.

    The manifest is the write-ahead record across the unavoidable two-file
    commit boundary.  This reconciliation deliberately does not reapply the
    current budget limits: an already-published charge must remain recordable
    even if policy was tightened later.
    """
    experiment_id = str(manifest.intent.get("experiment_id", "")).strip()
    if not experiment_id:
        return
    usage_path = require_project_state_root(project_root) / _USAGE_FILE
    usage = _read_usage_ledger(usage_path)
    reservations = _experiment_reservations(usage, experiment_id)
    by_token = {str(item["token"]): item for item in reservations}
    changed = _backfill_manifest_reservations(
        reservations,
        by_token,
        ExperimentRunRecord(run_dir=run_dir, manifest=manifest),
    )
    if changed:
        _write_usage_ledger(usage_path, usage)


def _read_usage_ledger(path: Path) -> dict[str, Any]:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return {"schema_version": 1, "experiments": {}}
    except OSError as exc:
        raise SimctlError(
            f"cannot inspect Experiment usage ledger {path}: {exc}"
        ) from exc
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise SimctlError(
            f"Experiment usage ledger must be a single-link regular file: {path}"
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
                raise SimctlError(
                    f"Experiment usage ledger changed while opening: {path}"
                )
            payload = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise SimctlError(f"cannot read Experiment usage ledger {path}: {exc}") from exc
    if (
        type(payload.get("schema_version")) is not int
        or payload.get("schema_version") != 1
        or not isinstance(payload.get("experiments"), dict)
    ):
        raise SimctlError(f"invalid Experiment usage ledger: {path}")
    return dict(payload)


def _experiment_reservations(
    payload: dict[str, Any],
    experiment_id: str,
) -> list[dict[str, str | float]]:
    experiments = payload.setdefault("experiments", {})
    if not isinstance(experiments, dict):
        raise SimctlError("invalid Experiment usage ledger experiments table")
    section = experiments.setdefault(experiment_id, {"reservations": []})
    if not isinstance(section, dict):
        raise SimctlError(f"invalid usage ledger entry for {experiment_id}")
    raw_reservations = section.setdefault("reservations", [])
    if not isinstance(raw_reservations, list):
        raise SimctlError(f"invalid usage reservations for {experiment_id}")
    parsed: list[dict[str, str | float]] = []
    seen: set[str] = set()
    for item in raw_reservations:
        if not isinstance(item, dict):
            raise SimctlError(f"invalid usage reservation for {experiment_id}")
        token = item.get("token")
        core_hours = item.get("core_hours")
        kind = item.get("kind", "run")
        if (
            not isinstance(token, str)
            or not token.strip()
            or token in seen
            or isinstance(core_hours, bool)
            or not isinstance(core_hours, (int, float))
            or not math.isfinite(core_hours)
            or core_hours < 0
            or not isinstance(kind, str)
            or kind not in {"run", "attempt"}
        ):
            raise SimctlError(f"invalid usage reservation for {experiment_id}")
        normalized: dict[str, str | float] = {
            "token": token,
            "core_hours": float(core_hours),
            "kind": str(kind),
        }
        parsed.append(normalized)
        seen.add(token)
    section["reservations"] = parsed
    return parsed


def _write_usage_ledger(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            tomli_w.dump(payload, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = ""
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except (OSError, TypeError) as exc:
        raise SimctlError(
            f"cannot persist Experiment usage ledger {path}: {exc}"
        ) from exc
    finally:
        if temporary:
            with contextlib.suppress(OSError):
                os.unlink(temporary)


def declared_job_core_hours(job: object) -> float:
    """Estimate declared core-hours for a JobData-like object."""
    walltime = _walltime_hours(str(getattr(job, "walltime", "")))
    if walltime is None:
        raise SimctlError("cannot enforce core-hour budget: invalid job.walltime")
    processes = _positive_int(getattr(job, "processes", 0))
    cores = _positive_int(getattr(job, "cores", 0))
    ntasks = _positive_int(getattr(job, "ntasks", 0))
    width = max(processes * max(cores, 1), ntasks, 1)
    return walltime * width


def declared_manifest_core_hours(manifest: ManifestData) -> float:
    """Estimate declared core-hours from a frozen Run manifest."""
    job = manifest.job
    walltime = _walltime_hours(str(job.get("walltime", "")))
    if walltime is None:
        run_id = str(manifest.run.get("id", "unknown"))
        raise SimctlError(
            f"cannot enforce core-hour budget: Run {run_id} has invalid job.walltime"
        )
    processes = _positive_int(job.get("processes"))
    cores = _positive_int(job.get("cores"))
    ntasks = _positive_int(job.get("ntasks"))
    width = max(processes * max(cores, 1), ntasks, 1)
    return walltime * width


def _positive_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return 0
    return value


def _walltime_hours(value: str) -> float | None:
    return parse_walltime_hours(value)


__all__ = [
    "ExperimentRunRecord",
    "collect_experiment_run_records",
    "declared_job_core_hours",
    "declared_manifest_core_hours",
    "enforce_experiment_run_budget",
    "enforce_project_unreviewed_completed_budget",
    "persist_manifest_budget_usage",
    "reserve_experiment_retry_budget",
]
