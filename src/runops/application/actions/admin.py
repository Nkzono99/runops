"""Run lifecycle administration actions."""

from __future__ import annotations

import os
import secrets
import shutil
import stat
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path

from runops.application.actions.helpers import (
    _dir_size,
    _error,
    _precondition_fail,
    _require_state,
)
from runops.application.actions.result import ActionResult, ActionStatus
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

    if moved:
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
    if os.path.lexists(destination):
        return f"Archive destination already exists: {destination}"
    try:
        destination.relative_to(source)
    except ValueError:
        return None
    return (
        f"Archive destination cannot be inside the source run directory: {destination}"
    )


@logged_action("restore_run")
def restore_run(run_dir: Path) -> ActionResult:
    """Restore an archived run to its pre-archive path without deleting data."""
    from runops.core.manifest import read_manifest, update_manifest
    from runops.core.state import update_state

    source = run_dir.resolve()
    state_str, err = _require_state(source, RunState.ARCHIVED)
    if err:
        return _precondition_fail("restore_run", err)

    manifest = read_manifest(source)
    run_id = manifest.run.get("id", source.name)
    restore_path = manifest.path.get("archived_from") or manifest.path.get(
        "created_at_path"
    )
    destination = (
        Path(os.path.abspath(Path(str(restore_path)).expanduser()))
        if restore_path
        else None
    )
    if destination == source:
        destination = None

    if destination is not None:
        collision_error = _validate_archive_destination(source, destination)
        if collision_error:
            return _precondition_fail("restore_run", collision_error)

    final_dir = source
    moved = False
    if destination is not None:
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
        except (OSError, shutil.Error) as e:
            return _error(
                "restore_run", f"Failed to move {source} to {destination}: {e}"
            )
        final_dir = destination
        moved = True

    try:
        update_state(final_dir, RunState.COMPLETED)
        update_manifest(
            final_dir,
            {
                "path": {
                    "run_dir": str(final_dir),
                    "restored_from": str(source),
                    "restored_at": datetime.now(tz=timezone.utc).isoformat(),
                }
            },
        )
    except SimctlError as e:
        if moved:
            with suppress(OSError, shutil.Error):
                shutil.move(str(final_dir), str(source))
        return _error("restore_run", str(e))

    if moved:
        emit_event(
            "artifact_move",
            action="restore_run",
            summary=f"Restore archived run {run_id}",
            path=final_dir,
            data={
                "run_id": run_id,
                "source_path": str(source),
                "restore_path": str(final_dir),
            },
            requires_verbose=True,
        )

    return ActionResult(
        action="restore_run",
        status=ActionStatus.SUCCESS,
        message="Run restored",
        data={
            "run_id": run_id,
            "moved": moved,
            "source_path": str(source),
            "restore_path": str(final_dir),
        },
        state_before=state_str,
        state_after=RunState.COMPLETED.value,
    )


@logged_action("purge_work")
def purge_work(
    run_dir: Path,
    *,
    discard_incomplete: bool = False,
    review_reason: str = "",
) -> ActionResult:
    """Delete purgeable work outputs from an archived run."""
    from runops.application.execution.readiness import read_cached_run_readiness
    from runops.core.manifest import read_manifest, update_manifest
    from runops.core.state import update_state

    state_str, err = _require_state(run_dir, RunState.ARCHIVED)
    if err:
        return _precondition_fail("purge_work", err)

    manifest = read_manifest(run_dir)
    readiness = read_cached_run_readiness(run_dir, manifest=manifest)
    if readiness is not None and not readiness.analysis_ready:
        gate_data = {
            "readiness": readiness.to_dict(),
            "recommended_action": readiness.recommended_action,
            "requires_human": True,
        }
        if not discard_incomplete:
            return ActionResult(
                action="purge_work",
                status=ActionStatus.PRECONDITION_FAILED,
                message=(
                    "Cached readiness is not ready; inspect outputs or rerun with "
                    "--discard-incomplete --reason <WHY>."
                ),
                data=gate_data,
                state_before=state_str,
            )
        if not review_reason.strip():
            return ActionResult(
                action="purge_work",
                status=ActionStatus.PRECONDITION_FAILED,
                message="--discard-incomplete requires a non-empty review reason.",
                data=gate_data,
                state_before=state_str,
            )
        update_manifest(
            run_dir,
            {
                "run": {
                    "readiness_disposition": "discarded_incomplete",
                    "readiness_review_reason": review_reason.strip(),
                    "readiness_reviewed_at": datetime.now(tz=timezone.utc).isoformat(),
                }
            },
        )

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
            "discarded_incomplete": bool(
                readiness is not None and not readiness.analysis_ready
            ),
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
    from runops.application import actions as action_registry
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
    from runops.application.execution.submission import (
        SubmissionClaimError,
        SubmissionLockError,
        submission_guard,
    )
    from runops.core.manifest import read_manifest

    requested_source = run_dir.absolute()
    try:
        requested_stat = os.lstat(requested_source)
    except OSError as e:
        return _error("delete_run", f"Failed to inspect {requested_source}: {e}")
    if stat.S_ISLNK(requested_stat.st_mode):
        return _precondition_fail(
            "delete_run",
            f"Refusing to delete a run through a symlink: {requested_source}",
        )
    try:
        source = requested_source.resolve(strict=True)
        source_stat = os.stat(source, follow_symlinks=False)
    except (OSError, RuntimeError) as e:
        return _error("delete_run", f"Failed to resolve {requested_source}: {e}")
    if (
        source_stat.st_dev != requested_stat.st_dev
        or source_stat.st_ino != requested_stat.st_ino
    ):
        return _precondition_fail(
            "delete_run",
            f"Run path changed while resolving it: {requested_source}",
        )
    delete_path = source
    try:
        with submission_guard(source) as guard:
            guarded_stat = os.stat(source, follow_symlinks=False)
            if (
                not stat.S_ISDIR(guarded_stat.st_mode)
                or guarded_stat.st_dev != source_stat.st_dev
                or guarded_stat.st_ino != source_stat.st_ino
            ):
                return _precondition_fail(
                    "delete_run",
                    f"Run path changed while acquiring its submission guard: {source}",
                )
            if guard.claim:
                return _precondition_fail(
                    "delete_run",
                    "Run has a durable submission claim "
                    f"{guard.claim!r}; reconcile it before deletion",
                )

            state_str, err = _require_state(
                source,
                RunState.CREATED,
                RunState.CANCELLED,
                RunState.FAILED,
            )
            if err:
                return _precondition_fail("delete_run", err)

            run_id = read_manifest(source).run.get("id", source.name)
            bytes_removed = _dir_size(source)
            delete_path = _unique_delete_staging_path(source)
            os.rename(source, delete_path)
            _fsync_directory(source.parent)
            shutil.rmtree(delete_path)
            _fsync_directory(source.parent)
    except (SubmissionClaimError, SubmissionLockError) as e:
        return _error("delete_run", f"Submission guard failed: {e}")
    except OSError as e:
        recovery = (
            f"; staged path retained at {delete_path}"
            if delete_path != source and delete_path.exists()
            else ""
        )
        return _error("delete_run", f"Failed to remove {source}: {e}{recovery}")

    return ActionResult(
        action="delete_run",
        status=ActionStatus.SUCCESS,
        message=f"Deleted run {run_id}",
        data={"run_id": run_id, "bytes_removed": bytes_removed},
        state_before=state_str,
        state_after="",
    )


def _unique_delete_staging_path(source: Path) -> Path:
    """Choose a collision-resistant sibling used to hide a run before deletion."""
    for _ in range(16):
        candidate = source.with_name(
            f".{source.name}.runops-delete-{secrets.token_hex(8)}"
        )
        if not os.path.lexists(candidate):
            return candidate
    raise OSError("failed to allocate a unique run deletion staging path")


def _fsync_directory(directory: Path) -> None:
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open(directory, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
