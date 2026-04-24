"""Run lifecycle administration actions."""

from __future__ import annotations

import shutil
from pathlib import Path

from runops.core.actions.helpers import (
    _dir_size,
    _error,
    _precondition_fail,
    _require_state,
)
from runops.core.actions.result import ActionResult, ActionStatus
from runops.core.event_log import logged_action
from runops.core.exceptions import SimctlError
from runops.core.state import RunState


@logged_action("archive_run")
def archive_run(run_dir: Path) -> ActionResult:
    """Archive a completed run."""
    from runops.core.manifest import read_manifest
    from runops.core.state import update_state

    state_str, err = _require_state(run_dir, RunState.COMPLETED)
    if err:
        return _precondition_fail("archive_run", err)

    run_id = read_manifest(run_dir).run.get("id", run_dir.name)

    try:
        update_state(run_dir, RunState.ARCHIVED)
    except SimctlError as e:
        return _error("archive_run", str(e))

    return ActionResult(
        action="archive_run",
        status=ActionStatus.SUCCESS,
        message="Run archived",
        data={"run_id": run_id},
        state_before=state_str,
        state_after=RunState.ARCHIVED.value,
    )


@logged_action("purge_work")
def purge_work(run_dir: Path) -> ActionResult:
    """Delete purgeable work outputs from an archived run."""
    from runops.core.state import update_state

    state_str, err = _require_state(run_dir, RunState.ARCHIVED)
    if err:
        return _precondition_fail("purge_work", err)

    work_dir = run_dir / "work"
    targets = ["outputs", "restart", "tmp"]
    removed_dirs: list[str] = []
    total_removed = 0

    for dirname in targets:
        target_dir = work_dir / dirname
        if not target_dir.is_dir():
            continue
        try:
            total_removed += _dir_size(target_dir)
            shutil.rmtree(target_dir)
        except OSError as e:
            return _error("purge_work", f"Failed to remove {target_dir}: {e}")
        removed_dirs.append(dirname)

    try:
        update_state(run_dir, RunState.PURGED)
    except SimctlError as e:
        return _error("purge_work", str(e))

    return ActionResult(
        action="purge_work",
        status=ActionStatus.SUCCESS,
        message="Purged work files",
        data={
            "removed_dirs": removed_dirs,
            "bytes_removed": total_removed,
        },
        state_before=state_str,
        state_after=RunState.PURGED.value,
    )


@logged_action("cancel_run")
def cancel_run(run_dir: Path) -> ActionResult:
    """Cancel an active Slurm job (scancel) and sync the run state.

    Wraps ``scancel <job_id>`` followed by ``sync_run`` so the manifest is
    updated atomically once Slurm reports the cancellation.  Use this instead
    of bare ``scancel`` so the run state ends up consistent.
    """
    from runops.core import actions as action_registry
    from runops.core.manifest import read_manifest
    from runops.slurm.submit import (
        SlurmCancelError,
        SlurmNotFoundError,
        scancel_job,
    )

    manifest = read_manifest(run_dir)
    run_id = manifest.run.get("id", run_dir.name)
    job_id = manifest.job.get("job_id", "")
    if not job_id:
        return _precondition_fail("cancel_run", "No job_id recorded in manifest")

    state_str, err = _require_state(run_dir, RunState.SUBMITTED, RunState.RUNNING)
    if err:
        return _precondition_fail("cancel_run", err)

    try:
        scancel_job(job_id)
    except SlurmNotFoundError as e:
        return _error("cancel_run", str(e))
    except SlurmCancelError as e:
        return _error("cancel_run", str(e))

    # Slurm typically takes a moment to mark the job as cancelled.  Run
    # sync_run so the manifest reflects whatever Slurm reports right now;
    # the caller can re-sync later if needed.
    sync_result = action_registry.sync_run(run_dir)

    if sync_result.status is not ActionStatus.SUCCESS:
        return ActionResult(
            action="cancel_run",
            status=ActionStatus.SUCCESS,
            message=(
                f"scancel sent for job {job_id}; sync did not complete "
                f"({sync_result.message}).  Re-run `runops runs sync` shortly."
            ),
            data={"run_id": run_id, "job_id": job_id},
            state_before=state_str,
            state_after=state_str,
        )

    return ActionResult(
        action="cancel_run",
        status=ActionStatus.SUCCESS,
        message=f"Cancelled job {job_id}; {sync_result.message}",
        data={
            "run_id": run_id,
            "job_id": job_id,
            "slurm_state": sync_result.data.get("slurm_state", ""),
        },
        state_before=state_str,
        state_after=sync_result.state_after or state_str,
    )


@logged_action("delete_run")
def delete_run(run_dir: Path) -> ActionResult:
    """Hard-delete a run directory.

    Only runs in a terminal non-completed state (``created``, ``cancelled``,
    or ``failed``) may be deleted.  Completed and archived runs hold valuable
    results and must go through the archive/purge flow instead.
    """
    state_str, err = _require_state(
        run_dir,
        RunState.CREATED,
        RunState.CANCELLED,
        RunState.FAILED,
    )
    if err:
        return _precondition_fail("delete_run", err)

    from runops.core.manifest import read_manifest

    run_id = read_manifest(run_dir).run.get("id", run_dir.name)
    bytes_removed = _dir_size(run_dir)

    try:
        shutil.rmtree(run_dir)
    except OSError as e:
        return _error("delete_run", f"Failed to remove {run_dir}: {e}")

    return ActionResult(
        action="delete_run",
        status=ActionStatus.SUCCESS,
        message=f"Deleted run {run_id}",
        data={"run_id": run_id, "bytes_removed": bytes_removed},
        state_before=state_str,
        state_after="",
    )
