"""State transition management for runs.

Defines the canonical set of run states, valid transitions between them,
and functions to update state in both manifest.toml and status/state.json.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from runops.core.event_log import emit_artifact_event
from runops.core.exceptions import InvalidStateTransitionError


class RunState(str, Enum):
    """Possible states for a simulation run.

    Values match SPEC section 13.
    """

    CREATED = "created"
    SUBMITTED = "submitted"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"
    PURGED = "purged"


#: Valid state transitions for internal lifecycle operations.
#: Matches SPEC section 13.2 exactly.
VALID_TRANSITIONS: dict[RunState, frozenset[RunState]] = {
    RunState.CREATED: frozenset({RunState.SUBMITTED, RunState.FAILED}),
    RunState.SUBMITTED: frozenset(
        {RunState.RUNNING, RunState.FAILED, RunState.CANCELLED}
    ),
    RunState.RUNNING: frozenset(
        {RunState.COMPLETED, RunState.FAILED, RunState.CANCELLED}
    ),
    RunState.COMPLETED: frozenset({RunState.ARCHIVED}),
    RunState.FAILED: frozenset(),
    RunState.CANCELLED: frozenset(),
    RunState.ARCHIVED: frozenset({RunState.COMPLETED, RunState.PURGED}),
    RunState.PURGED: frozenset(),
}

#: Reconciliation transitions: allowed when syncing with external state
#: (Slurm).  These cover cases where intermediate states were not observed
#: (e.g. submitted -> completed when the job ran between sync polls).
RECONCILIATION_TRANSITIONS: dict[RunState, frozenset[RunState]] = {
    RunState.CREATED: frozenset({RunState.SUBMITTED, RunState.FAILED}),
    RunState.SUBMITTED: frozenset(
        {
            RunState.RUNNING,
            RunState.COMPLETED,  # skipped running
            RunState.FAILED,
            RunState.CANCELLED,
        }
    ),
    RunState.RUNNING: frozenset(
        {RunState.COMPLETED, RunState.FAILED, RunState.CANCELLED}
    ),
    RunState.COMPLETED: frozenset({RunState.ARCHIVED}),
    RunState.FAILED: frozenset(),
    RunState.CANCELLED: frozenset(),
    RunState.ARCHIVED: frozenset({RunState.COMPLETED, RunState.PURGED}),
    RunState.PURGED: frozenset(),
}


def validate_transition(current: RunState, target: RunState) -> bool:
    """Check whether a state transition is valid.

    Args:
        current: The current run state.
        target: The desired next state.

    Returns:
        True if the transition is allowed, False otherwise.
    """
    return target in VALID_TRANSITIONS.get(current, frozenset())


def transition_state(current: RunState, target: RunState) -> RunState:
    """Perform a validated state transition.

    Args:
        current: The current run state.
        target: The desired next state.

    Returns:
        The new state (same as target).

    Raises:
        InvalidStateTransitionError: If the transition is not allowed.
    """
    if not validate_transition(current, target):
        raise InvalidStateTransitionError(current.value, target.value)
    return target


def validate_reconciliation(current: RunState, target: RunState) -> bool:
    """Check whether a reconciliation transition is valid.

    Reconciliation transitions are a superset of lifecycle transitions,
    allowing state jumps that occur when intermediate states are not
    observed (e.g. ``submitted -> completed`` during Slurm sync).

    Args:
        current: The current run state.
        target: The observed external state.

    Returns:
        True if the reconciliation is allowed.
    """
    return target in RECONCILIATION_TRANSITIONS.get(current, frozenset())


def update_state(
    run_dir: Path,
    new_state: RunState,
    *,
    timestamp: datetime | None = None,
    reconcile: bool = False,
    reason: str = "",
    slurm_state: str = "",
) -> None:
    """Update the run state in both manifest.toml and status/state.json.

    This function reads the current manifest, validates the transition,
    updates ``run.status`` in manifest.toml, and writes a corresponding
    ``status/state.json``.

    Args:
        run_dir: Path to the run directory.
        new_state: The target state.
        timestamp: Optional timestamp for the state change. Defaults
            to the current UTC time.
        reconcile: If True, use reconciliation rules (allows skipping
            intermediate states during Slurm sync).
        reason: Terminal reason for failed/cancelled states
            (e.g. ``"timeout"``, ``"oom"``, ``"node_fail"``).
        slurm_state: Raw Slurm state string for provenance.

    Raises:
        InvalidStateTransitionError: If the transition is not allowed.
        ManifestNotFoundError: If manifest.toml does not exist.
    """
    # Import here to avoid circular imports
    from runops.core.manifest import read_manifest, update_manifest

    if timestamp is None:
        timestamp = datetime.now(tz=timezone.utc)

    manifest = read_manifest(run_dir)
    current_str = manifest.run.get("status", "")
    try:
        current = RunState(current_str)
    except ValueError:
        raise InvalidStateTransitionError(current_str, new_state.value) from None

    # Validate transition
    if reconcile:
        if not validate_reconciliation(current, new_state):
            raise InvalidStateTransitionError(current.value, new_state.value)
    else:
        transition_state(current, new_state)

    # Build manifest updates
    run_updates: dict[str, Any] = {"status": new_state.value}
    if reason:
        run_updates["failure_reason"] = reason
    if slurm_state:
        run_updates["last_slurm_state"] = slurm_state

    update_manifest(run_dir, {"run": run_updates})

    _write_state_json(
        run_dir,
        new_state=new_state,
        previous_state=current,
        timestamp=timestamp,
        reason=reason,
        slurm_state=slurm_state,
    )


def reset_state_for_retry(
    run_dir: Path,
    *,
    timestamp: datetime | None = None,
    run_updates: dict[str, Any] | None = None,
    job_updates: dict[str, Any] | None = None,
) -> RunState:
    """Reset a failed or cancelled run to created for a retry attempt.

    This is a deliberate lifecycle reset, not a normal state-machine
    transition. It updates both ``manifest.toml`` and ``status/state.json``
    so agent-facing status views remain consistent with the manifest.

    Args:
        run_dir: Path to the run directory.
        timestamp: Optional timestamp for the reset. Defaults to current UTC
            time.
        run_updates: Additional ``[run]`` manifest fields to write after the
            default retry reset fields.
        job_updates: Additional ``[job]`` manifest fields to write after the
            default retry reset fields.

    Returns:
        The previous terminal state.

    Raises:
        InvalidStateTransitionError: If the current state is not failed or
            cancelled.
        ManifestNotFoundError: If manifest.toml does not exist.
    """
    from runops.core.manifest import read_manifest, update_manifest

    if timestamp is None:
        timestamp = datetime.now(tz=timezone.utc)

    manifest = read_manifest(run_dir)
    current_str = manifest.run.get("status", "")
    try:
        current = RunState(current_str)
    except ValueError:
        raise InvalidStateTransitionError(current_str, RunState.CREATED.value) from None

    if current not in {RunState.FAILED, RunState.CANCELLED}:
        raise InvalidStateTransitionError(current.value, RunState.CREATED.value)

    merged_run_updates: dict[str, Any] = {
        "status": RunState.CREATED.value,
        "failure_reason": "",
        "last_slurm_state": "",
    }
    if run_updates:
        merged_run_updates.update(run_updates)
    merged_job_updates: dict[str, Any] = {
        "job_id": "",
        "submitted_at": "",
    }
    if job_updates:
        merged_job_updates.update(job_updates)

    update_manifest(
        run_dir,
        {
            "run": merged_run_updates,
            "job": merged_job_updates,
            "curation": {
                "review_status": "unreviewed",
                "reviewed_at": "",
                "reviewed_by": "",
                "reason": "",
            },
        },
    )
    _write_state_json(
        run_dir,
        new_state=RunState.CREATED,
        previous_state=current,
        timestamp=timestamp,
        reason="retry",
    )
    return current


def _write_state_json(
    run_dir: Path,
    *,
    new_state: RunState,
    previous_state: RunState,
    timestamp: datetime,
    reason: str = "",
    slurm_state: str = "",
) -> None:
    """Write the status/state.json mirror for a state change."""
    status_dir = run_dir / "status"
    status_dir.mkdir(parents=True, exist_ok=True)
    state_json: dict[str, Any] = {
        "state": new_state.value,
        "previous_state": previous_state.value,
        "changed_at": timestamp.isoformat(),
    }
    if reason:
        state_json["reason"] = reason
    if slurm_state:
        state_json["slurm_state"] = slurm_state
    state_file = status_dir / "state.json"
    existed_before = state_file.exists()
    with open(state_file, "w") as f:
        json.dump(state_json, f, indent=2)
        f.write("\n")
    emit_artifact_event(
        state_file,
        operation="update" if existed_before else "create",
        artifact_kind="state_mirror",
        summary="Update status/state.json",
    )
