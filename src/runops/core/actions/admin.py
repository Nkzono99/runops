"""Run lifecycle administration actions."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from runops.core.actions.helpers import (
    _dir_size,
    _error,
    _precondition_fail,
    _require_state,
)
from runops.core.actions.result import ActionResult, ActionStatus
from runops.core.event_log import emit_event, logged_action
from runops.core.exceptions import ProjectNotFoundError, SimctlError
from runops.core.project import find_project_root
from runops.core.state import RunState

_ARCHIVE_DIR_NAME = "_archive"


def default_archive_destination(
    run_dir: Path,
    *,
    archive_root: Path | None = None,
) -> Path:
    """Return the default archive destination for a run directory.

    When ``run_dir`` belongs to a runops project, the destination preserves
    the run's path relative to ``runs/`` under ``runs/_archive/`` or a custom
    ``archive_root``.  Standalone run directories fall back to a sibling
    ``_archive`` directory.

    Args:
        run_dir: Run directory to archive.
        archive_root: Optional archive root overriding ``runs/_archive``.

    Returns:
        Absolute destination directory for the archived run.
    """
    source = run_dir.resolve()
    project_root = _find_project_root_or_none(source)
    if archive_root is None:
        root = (
            project_root / "runs" / _ARCHIVE_DIR_NAME
            if project_root is not None
            else source.parent / _ARCHIVE_DIR_NAME
        )
    else:
        root = archive_root.resolve()

    return (root / _archive_relative_path(source, project_root)).resolve()


def _find_project_root_or_none(path: Path) -> Path | None:
    try:
        return find_project_root(path)
    except ProjectNotFoundError:
        return None


def _archive_relative_path(run_dir: Path, project_root: Path | None) -> Path:
    if project_root is None:
        return Path(run_dir.name)

    runs_dir = (project_root / "runs").resolve()
    try:
        relative = run_dir.relative_to(runs_dir)
    except ValueError:
        return Path(run_dir.name)

    if relative.parts and relative.parts[0] == _ARCHIVE_DIR_NAME:
        remainder = relative.parts[1:]
        return Path(*remainder) if remainder else Path(run_dir.name)
    return relative


@logged_action("archive_run")
def archive_run(run_dir: Path, *, move_to: Path | None = None) -> ActionResult:
    """Archive a completed run, optionally relocating its directory.

    Args:
        run_dir: Run directory to archive.
        move_to: Optional final run directory to move the archived run into.

    Returns:
        Structured action result with source and archive paths.
    """
    from runops.core.manifest import read_manifest, write_manifest
    from runops.core.state import update_state

    source = run_dir.resolve()
    state_str, err = _require_state(source, RunState.COMPLETED)
    if err:
        return _precondition_fail("archive_run", err)

    run_id = read_manifest(source).run.get("id", source.name)
    destination = move_to.resolve() if move_to is not None else None
    if destination is not None:
        collision_error = _validate_archive_destination(source, destination)
        if collision_error:
            return _precondition_fail("archive_run", collision_error)
        if destination == source:
            destination = None

    try:
        update_state(source, RunState.ARCHIVED)
    except SimctlError as e:
        return _error("archive_run", str(e))

    final_dir = source
    moved = False
    if destination is not None:
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
        except (OSError, shutil.Error) as e:
            return _error(
                "archive_run", f"Failed to move {source} to {destination}: {e}"
            )

        final_dir = destination
        moved = True
        try:
            manifest = read_manifest(final_dir)
            if "created_at_path" not in manifest.path:
                manifest.path["created_at_path"] = str(source)
            manifest.path["run_dir"] = str(final_dir)
            manifest.path["archived_from"] = str(source)
            manifest.path["archived_at"] = datetime.now(tz=timezone.utc).isoformat()
            write_manifest(final_dir, manifest)
        except SimctlError as e:
            return _error("archive_run", str(e))

        emit_event(
            "artifact_move",
            action="archive_run",
            summary=f"Move archived run {run_id}",
            path=final_dir,
            data={
                "run_id": run_id,
                "source_path": str(source),
                "archive_path": str(final_dir),
            },
            requires_verbose=True,
        )

    return ActionResult(
        action="archive_run",
        status=ActionStatus.SUCCESS,
        message="Run archived",
        data={
            "run_id": run_id,
            "moved": moved,
            "source_path": str(source),
            "archive_path": str(final_dir),
        },
        state_before=state_str,
        state_after=RunState.ARCHIVED.value,
    )


def _validate_archive_destination(source: Path, destination: Path) -> str | None:
    if destination == source:
        return None
    if destination.exists():
        return f"Archive destination already exists: {destination}"
    try:
        destination.relative_to(source)
    except ValueError:
        return None
    return (
        f"Archive destination cannot be inside the source run directory: {destination}"
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
