"""Agent Gateway actions for deriving and inspecting Runs."""

from __future__ import annotations

from pathlib import Path

from runops.application.actions.helpers import _error, _precondition_fail
from runops.application.actions.result import ActionResult, ActionStatus
from runops.application.execution.submission import SubmissionLockError
from runops.core.event_log import logged_action
from runops.core.exceptions import SimctlError
from runops.core.state import RunState


@logged_action("clone_run")
def clone_run(
    source_dir: Path,
    *,
    dest_dir: Path | None = None,
    overrides: dict[str, str] | None = None,
    experiment_id: str | None = None,
    purpose: str | None = None,
) -> ActionResult:
    """Clone a completed-equivalent Run through the shared derivation use case."""
    from runops.application.run_derivation import clone_run as derive_clone

    try:
        result = derive_clone(
            source_dir,
            dest_dir=dest_dir,
            overrides=overrides,
            experiment_id=experiment_id,
            purpose=purpose,
        )
    except SimctlError as exc:
        return _precondition_fail("clone_run", str(exc))
    except SubmissionLockError as exc:
        return _error("clone_run", f"Error locking clone source: {exc}")
    except OSError as exc:
        return _error("clone_run", f"Error creating clone directory: {exc}")

    return ActionResult(
        action="clone_run",
        status=ActionStatus.SUCCESS,
        message=(
            f"Reused equivalent Run {result.run_info.run_id}"
            if result.reused
            else f"Cloned {result.source_run_id} -> {result.run_info.run_id}"
        ),
        data={
            "source_run_id": result.source_run_id,
            "run_id": result.run_info.run_id,
            "run_dir": str(result.run_info.run_dir),
            "reused": result.reused,
            "warnings": list(result.warnings),
        },
        state_after="" if result.reused else RunState.CREATED.value,
    )


@logged_action("extend_run")
def extend_run(
    source_dir: Path,
    *,
    dest_dir: Path | None = None,
    nstep: int | None = None,
    experiment_id: str | None = None,
    purpose: str | None = None,
    submit: bool = False,
) -> ActionResult:
    """Create a continuation and optionally submit the new Run."""
    from runops.application.actions.run_lifecycle import submit_run
    from runops.application.run_derivation import extend_run as derive_continuation

    try:
        result = derive_continuation(
            source_dir,
            dest_dir=dest_dir,
            nstep=nstep,
            experiment_id=experiment_id,
            purpose=purpose,
        )
    except SimctlError as exc:
        return _precondition_fail("extend_run", str(exc))
    except SubmissionLockError as exc:
        return _error("extend_run", f"Error locking continuation source: {exc}")
    except OSError as exc:
        return _error("extend_run", f"Error creating continuation: {exc}")

    data = {
        "source_run_id": result.source_run_id,
        "run_id": result.run_info.run_id,
        "run_dir": str(result.run_info.run_dir),
        "reused": result.reused,
        "continuation": result.continuation,
        "warnings": list(result.warnings),
    }
    message = (
        f"Reused equivalent Run {result.run_info.run_id}"
        if result.reused
        else f"Created continuation Run {result.run_info.run_id}"
    )
    state_after = "" if result.reused else RunState.CREATED.value
    if submit and not result.reused:
        submitted = submit_run(result.run_info.run_dir)
        data["submission"] = submitted.to_dict()
        if submitted.status is not ActionStatus.SUCCESS:
            return ActionResult(
                action="extend_run",
                status=submitted.status,
                message=f"{message}; auto-submit failed: {submitted.message}",
                data=data,
                state_after=state_after,
            )
        message = f"{message}; {submitted.message}"
        state_after = submitted.state_after
    elif submit:
        data["submission"] = {
            "status": "skipped",
            "message": "Equivalent completed Run was reused; no submission needed.",
        }

    return ActionResult(
        action="extend_run",
        status=ActionStatus.SUCCESS,
        message=message,
        data=data,
        state_after=state_after,
    )


@logged_action("inspect_regeneration")
def inspect_regeneration(
    run_dir: Path,
    *,
    dry_run: bool = False,
) -> ActionResult:
    """Compare a Run with its case while preserving immutable input identity."""
    from runops.application.run_derivation import inspect_run_regeneration

    try:
        result = inspect_run_regeneration(run_dir, dry_run=dry_run)
    except SimctlError as exc:
        return _precondition_fail("inspect_regeneration", str(exc))
    except OSError as exc:
        return _error("inspect_regeneration", f"Regeneration inspection failed: {exc}")

    return ActionResult(
        action="inspect_regeneration",
        status=ActionStatus.SUCCESS,
        message=(
            f"Inspected input drift for {result.run_id} from case {result.case_name}"
        ),
        data={
            "run_id": result.run_id,
            "case_name": result.case_name,
            "added": list(result.added),
            "modified": list(result.modified),
            "removed": list(result.removed),
            "unchanged": list(result.unchanged),
            "has_changes": result.has_changes,
            "work_exists": result.work_exists,
        },
    )


__all__ = ["clone_run", "extend_run", "inspect_regeneration"]
