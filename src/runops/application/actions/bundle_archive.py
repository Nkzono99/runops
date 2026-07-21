"""Reversible archival of a directory containing multiple runs."""

from __future__ import annotations

import os
import secrets
import shutil
import sys
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

import tomli_w

from runops.application.actions.helpers import _error, _precondition_fail
from runops.application.actions.result import ActionResult, ActionStatus
from runops.core.discovery import ARCHIVE_BUNDLE_METADATA_FILE, discover_runs
from runops.core.event_log import emit_event, logged_action
from runops.core.exceptions import ProjectNotFoundError, SimctlError
from runops.core.manifest import ManifestData, read_manifest, write_manifest
from runops.core.project import find_project_root
from runops.core.state import RunState

_ARCHIVE_DIR_NAME = "_archive"
_ACTIVE_STATES = frozenset({RunState.SUBMITTED, RunState.RUNNING})
_ADOPTABLE_STATES = frozenset({RunState.ARCHIVED, RunState.PURGED})


@dataclass(frozen=True)
class _BundleRun:
    relative_path: Path
    source_path: Path
    run_id: str
    state: RunState
    manifest: ManifestData
    original_bytes: bytes


@dataclass(frozen=True)
class _BundleArchivePlan:
    source: Path
    destination: Path
    source_runs: list[_BundleRun]
    adopted_runs: list[_BundleRun]


def default_bundle_archive_destination(
    bundle_dir: Path,
    *,
    archive_root: Path | None = None,
) -> Path:
    """Return the destination for a parent directory archived as one bundle."""
    source = bundle_dir.expanduser().resolve()
    project_root = _find_project_root_or_none(source)
    relative = Path(source.name)
    if project_root is not None:
        runs_dir = (project_root / "runs").resolve()
        try:
            relative = source.relative_to(runs_dir)
        except ValueError as exc:
            raise ValueError(
                f"Bundle must be located under {runs_dir}: {source}"
            ) from exc
        if not relative.parts:
            raise ValueError("The project runs/ root cannot be archived as a bundle.")
        if relative.parts[0] == _ARCHIVE_DIR_NAME:
            raise ValueError("Bundle is already located under runs/_archive/.")

    if archive_root is not None:
        root = archive_root.expanduser().resolve()
    elif project_root is not None:
        root = (project_root / "runs" / _ARCHIVE_DIR_NAME).resolve()
    else:
        root = (source.parent / _ARCHIVE_DIR_NAME).resolve()
    return (root / relative).resolve()


def plan_bundle_archive(
    bundle_dir: Path,
    *,
    archive_root: Path | None = None,
    adopt_archived: bool = False,
) -> ActionResult:
    """Validate and describe a bundle archive without changing the filesystem."""
    action = "plan_bundle_archive"
    plan, plan_error = _build_archive_plan(
        bundle_dir,
        archive_root=archive_root,
        adopt_archived=adopt_archived,
    )
    if plan_error:
        return _precondition_fail(action, plan_error)
    assert plan is not None
    return ActionResult(
        action=action,
        status=ActionStatus.SUCCESS,
        message="Bundle archive is ready",
        data=_plan_data(plan),
    )


@logged_action("archive_bundle")
def archive_bundle(
    bundle_dir: Path,
    *,
    archive_root: Path | None = None,
    adopt_archived: bool = False,
) -> ActionResult:
    """Move a run-containing parent directory without changing run states."""
    action = "archive_bundle"
    plan, plan_error = _build_archive_plan(
        bundle_dir,
        archive_root=archive_root,
        adopt_archived=adopt_archived,
    )
    if plan_error:
        return _precondition_fail(action, plan_error)
    assert plan is not None

    archived_at = datetime.now(tz=timezone.utc).isoformat()
    if plan.adopted_runs:
        apply_error = _archive_with_adoption(plan, archived_at=archived_at)
    else:
        apply_error = _archive_without_adoption(plan, archived_at=archived_at)
    if apply_error:
        return _error(action, apply_error)

    runs = [*plan.source_runs, *plan.adopted_runs]
    source = plan.source
    destination = plan.destination

    emit_event(
        "artifact_move",
        action=action,
        summary=f"Archive bundle {source.name}",
        path=destination,
        data={
            "source_path": str(source),
            "archive_path": str(destination),
            "run_count": len(runs),
            "adopted_run_count": len(plan.adopted_runs),
        },
        requires_verbose=True,
    )
    return ActionResult(
        action=action,
        status=ActionStatus.SUCCESS,
        message="Bundle archived",
        data={
            "bundle_name": source.name,
            "run_count": len(runs),
            "source_path": str(source),
            "archive_path": str(destination),
            "adopted_run_count": len(plan.adopted_runs),
            "adopted_runs": _adopted_run_data(plan.adopted_runs),
        },
    )


@logged_action("restore_bundle")
def restore_bundle(bundle_dir: Path) -> ActionResult:
    """Restore an archived parent directory and preserve every run state."""
    action = "restore_bundle"
    source = bundle_dir.expanduser().resolve()
    metadata_path = source / ARCHIVE_BUNDLE_METADATA_FILE
    if not source.is_dir() or not metadata_path.is_file():
        return _precondition_fail(
            action,
            f"Archived bundle metadata not found: {metadata_path}",
        )

    destination, metadata_error = _read_restore_destination(metadata_path)
    if metadata_error:
        return _precondition_fail(action, metadata_error)
    assert destination is not None

    destination_error = _validate_destination(source, destination, "Restore")
    if destination_error:
        return _precondition_fail(action, destination_error)

    runs, load_error = _load_bundle_runs(source)
    if load_error:
        return _precondition_fail(action, load_error)
    if not runs:
        return _precondition_fail(action, f"No runs found under bundle: {source}")

    restored_at = datetime.now(tz=timezone.utc).isoformat()
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
    except (OSError, shutil.Error) as exc:
        return _error(action, f"Failed to move {source} to {destination}: {exc}")

    try:
        for run in runs:
            restored_run_dir = destination / run.relative_path
            manifest = run.manifest
            manifest.path["run_dir"] = str(restored_run_dir.resolve())
            manifest.path["bundle_restored_from"] = str(run.source_path)
            manifest.path["bundle_restored_at"] = restored_at
            write_manifest(restored_run_dir, manifest)
        (destination / ARCHIVE_BUNDLE_METADATA_FILE).unlink()
    except (OSError, SimctlError) as exc:
        rollback_error = _rollback_move(
            current=destination,
            original=source,
            runs=runs,
            remove_metadata=False,
        )
        message = f"Failed to update restored bundle manifests: {exc}"
        if rollback_error:
            message += f"; rollback failed: {rollback_error}"
        return _error(action, message)

    emit_event(
        "artifact_move",
        action=action,
        summary=f"Restore bundle {source.name}",
        path=destination,
        data={
            "source_path": str(source),
            "restore_path": str(destination),
            "run_count": len(runs),
        },
        requires_verbose=True,
    )
    return ActionResult(
        action=action,
        status=ActionStatus.SUCCESS,
        message="Bundle restored",
        data={
            "bundle_name": source.name,
            "run_count": len(runs),
            "source_path": str(source),
            "restore_path": str(destination),
        },
    )


def _find_project_root_or_none(path: Path) -> Path | None:
    try:
        return find_project_root(path)
    except ProjectNotFoundError:
        return None


def _load_bundle_runs(bundle_dir: Path) -> tuple[list[_BundleRun], str | None]:
    runs: list[_BundleRun] = []
    for run_dir in discover_runs(bundle_dir):
        try:
            manifest = read_manifest(run_dir)
            raw_state = str(manifest.run.get("status", ""))
            state = RunState(raw_state)
            relative = run_dir.relative_to(bundle_dir)
            original_bytes = (run_dir / "manifest.toml").read_bytes()
        except (OSError, SimctlError, ValueError) as exc:
            return [], f"Invalid run under bundle {run_dir}: {exc}"
        runs.append(
            _BundleRun(
                relative_path=relative,
                source_path=run_dir.resolve(),
                run_id=str(manifest.run.get("id", run_dir.name)),
                state=state,
                manifest=manifest,
                original_bytes=original_bytes,
            )
        )
    return runs, None


def _build_archive_plan(
    bundle_dir: Path,
    *,
    archive_root: Path | None,
    adopt_archived: bool,
) -> tuple[_BundleArchivePlan | None, str | None]:
    source = bundle_dir.expanduser().resolve()
    if not source.is_dir():
        return None, f"Bundle directory not found: {source}"
    if (source / ARCHIVE_BUNDLE_METADATA_FILE).exists():
        return None, f"Bundle is already archived: {source}"

    try:
        destination = default_bundle_archive_destination(
            source,
            archive_root=archive_root,
        )
    except ValueError as exc:
        return None, str(exc)

    nesting_error = _validate_destination_nesting(source, destination, "Archive")
    if nesting_error:
        return None, nesting_error

    destination_exists = os.path.lexists(destination)
    if destination_exists and not adopt_archived:
        return None, f"Archive destination already exists: {destination}"
    if destination_exists and (destination.is_symlink() or not destination.is_dir()):
        return None, f"Archive destination is not a directory: {destination}"

    source_runs, load_error = _load_bundle_runs(source)
    if load_error:
        return None, load_error
    active = [run for run in source_runs if run.state in _ACTIVE_STATES]
    if active:
        details = ", ".join(f"{run.run_id} ({run.state.value})" for run in active)
        return None, f"Cannot archive a bundle containing active runs: {details}"

    adopted_runs: list[_BundleRun] = []
    if destination_exists:
        if (destination / ARCHIVE_BUNDLE_METADATA_FILE).exists():
            return None, f"Archive destination is already a bundle: {destination}"
        adopted_runs, load_error = _load_bundle_runs(destination)
        if load_error:
            return None, load_error
        if not adopted_runs:
            return None, f"No individually archived runs found under: {destination}"
        adoption_error = _validate_adopted_runs(
            source,
            destination,
            adopted_runs,
        )
        if adoption_error:
            return None, adoption_error

    if not source_runs and not adopted_runs:
        return None, f"No runs found under bundle: {source}"

    return (
        _BundleArchivePlan(
            source=source,
            destination=destination,
            source_runs=source_runs,
            adopted_runs=adopted_runs,
        ),
        None,
    )


def _validate_adopted_runs(
    source: Path,
    destination: Path,
    runs: list[_BundleRun],
) -> str | None:
    for run in runs:
        if run.state not in _ADOPTABLE_STATES:
            return (
                f"Cannot adopt {run.run_id}: state is '{run.state.value}', "
                "expected archived or purged"
            )
        raw_archived_from = run.manifest.path.get("archived_from")
        if not isinstance(raw_archived_from, str) or not raw_archived_from:
            return f"Cannot adopt {run.run_id}: path.archived_from is missing"
        archived_from = Path(raw_archived_from).expanduser()
        if not archived_from.is_absolute():
            return (
                f"Cannot adopt {run.run_id}: path.archived_from must be absolute: "
                f"{raw_archived_from}"
            )
        try:
            original_relative = archived_from.resolve().relative_to(source)
        except ValueError:
            return f"Archived run {run.run_id} does not belong to bundle {source}"
        if original_relative != run.relative_path:
            return (
                f"Archived run {run.run_id} has moved relative to its bundle: "
                f"expected {original_relative}, found {run.relative_path}"
            )

        restore_target = source / original_relative
        if os.path.lexists(restore_target):
            return (
                f"Cannot adopt {run.run_id}: source path already exists: "
                f"{restore_target}"
            )
        ancestor = restore_target.parent
        while ancestor != source:
            if os.path.lexists(ancestor) and (
                ancestor.is_symlink() or not ancestor.is_dir()
            ):
                return (
                    f"Cannot adopt {run.run_id}: source ancestor is not a "
                    f"directory: {ancestor}"
                )
            ancestor = ancestor.parent

    run_roots = [destination / run.relative_path for run in runs]
    for path in destination.rglob("*"):
        if any(_is_relative_to(path, root) for root in run_roots):
            continue
        if path.is_dir() and any(_is_relative_to(root, path) for root in run_roots):
            continue
        return f"Archive destination contains an unowned path: {path}"
    return None


def _archive_without_adoption(
    plan: _BundleArchivePlan,
    *,
    archived_at: str,
) -> str | None:
    metadata_path = plan.source / ARCHIVE_BUNDLE_METADATA_FILE
    try:
        _write_toml_atomic(metadata_path, _bundle_metadata(plan, archived_at))
        plan.destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(plan.source), str(plan.destination))
    except (OSError, shutil.Error) as exc:
        with suppress(OSError):
            metadata_path.unlink()
        return f"Failed to move {plan.source} to {plan.destination}: {exc}"

    try:
        _update_archived_manifests(plan, archived_at=archived_at)
    except (OSError, SimctlError) as exc:
        rollback_error = _rollback_move(
            current=plan.destination,
            original=plan.source,
            runs=plan.source_runs,
            remove_metadata=True,
        )
        message = f"Failed to update bundle manifests: {exc}"
        if rollback_error:
            message += f"; rollback failed: {rollback_error}"
        return message
    return None


def _archive_with_adoption(
    plan: _BundleArchivePlan,
    *,
    archived_at: str,
) -> str | None:
    staging = _new_staging_path(plan.destination)
    destination_staged = False
    source_moved = False
    moved_adopted: list[_BundleRun] = []
    created_parents: list[Path] = []
    try:
        shutil.move(str(plan.destination), str(staging))
        destination_staged = True
        shutil.move(str(plan.source), str(plan.destination))
        source_moved = True
        for run in plan.adopted_runs:
            target = plan.destination / run.relative_path
            created_parents.extend(
                _create_missing_parents(target.parent, plan.destination)
            )
            shutil.move(str(staging / run.relative_path), str(target))
            moved_adopted.append(run)
        _write_toml_atomic(
            plan.destination / ARCHIVE_BUNDLE_METADATA_FILE,
            _bundle_metadata(plan, archived_at),
        )
        _update_archived_manifests(plan, archived_at=archived_at)
        _remove_empty_tree(staging)
    except (OSError, shutil.Error, SimctlError) as exc:
        rollback_error = _rollback_adopted_archive(
            plan,
            staging=staging,
            destination_staged=destination_staged,
            source_moved=source_moved,
            moved_adopted=moved_adopted,
            created_parents=created_parents,
        )
        message = f"Failed to adopt archived runs into bundle: {exc}"
        if rollback_error:
            message += f"; rollback failed: {rollback_error}"
        return message
    return None


def _update_archived_manifests(
    plan: _BundleArchivePlan,
    *,
    archived_at: str,
) -> None:
    adopted_ids = {id(run) for run in plan.adopted_runs}
    for run in [*plan.source_runs, *plan.adopted_runs]:
        final_run_dir = plan.destination / run.relative_path
        manifest = run.manifest
        if "created_at_path" not in manifest.path:
            created_at_path = run.source_path
            if id(run) in adopted_ids:
                archived_from = manifest.path.get("archived_from")
                if isinstance(archived_from, str) and archived_from:
                    created_at_path = Path(archived_from).expanduser().resolve()
            manifest.path["created_at_path"] = str(created_at_path)
        manifest.path["run_dir"] = str(final_run_dir.resolve())
        manifest.path["bundle_archived_from"] = str(run.source_path)
        manifest.path["bundle_archived_at"] = archived_at
        write_manifest(final_run_dir, manifest)


def _rollback_adopted_archive(
    plan: _BundleArchivePlan,
    *,
    staging: Path,
    destination_staged: bool,
    source_moved: bool,
    moved_adopted: list[_BundleRun],
    created_parents: list[Path],
) -> str | None:
    try:
        moved_ids = {id(run) for run in moved_adopted}
        source_root = plan.destination if source_moved else plan.source
        for run in plan.source_runs:
            (source_root / run.relative_path / "manifest.toml").write_bytes(
                run.original_bytes
            )
        for run in plan.adopted_runs:
            if id(run) in moved_ids:
                root = plan.destination
            elif destination_staged:
                root = staging
            else:
                root = plan.destination
            (root / run.relative_path / "manifest.toml").write_bytes(run.original_bytes)
        if source_moved:
            with suppress(OSError):
                (plan.destination / ARCHIVE_BUNDLE_METADATA_FILE).unlink()
        if destination_staged:
            for run in reversed(moved_adopted):
                original = staging / run.relative_path
                original.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(
                    str(plan.destination / run.relative_path),
                    str(original),
                )
            for parent in sorted(
                set(created_parents),
                key=lambda path: len(path.parts),
                reverse=True,
            ):
                with suppress(OSError):
                    parent.rmdir()
        if source_moved:
            shutil.move(str(plan.destination), str(plan.source))
        if destination_staged:
            shutil.move(str(staging), str(plan.destination))
    except (OSError, shutil.Error) as exc:
        return str(exc)
    return None


def _bundle_metadata(plan: _BundleArchivePlan, archived_at: str) -> dict[str, Any]:
    return {
        "bundle": {
            "format_version": 1,
            "archived_from": str(plan.source),
            "archived_at": archived_at,
            "run_count": len(plan.source_runs) + len(plan.adopted_runs),
            "adopted_run_ids": sorted(run.run_id for run in plan.adopted_runs),
        }
    }


def _plan_data(plan: _BundleArchivePlan) -> dict[str, Any]:
    return {
        "source_path": str(plan.source),
        "archive_path": str(plan.destination),
        "run_count": len(plan.source_runs) + len(plan.adopted_runs),
        "source_run_count": len(plan.source_runs),
        "adopted_run_count": len(plan.adopted_runs),
        "adopted_runs": _adopted_run_data(plan.adopted_runs),
    }


def _adopted_run_data(runs: list[_BundleRun]) -> list[dict[str, str]]:
    return [
        {"run_id": run.run_id, "status": run.state.value}
        for run in sorted(runs, key=lambda item: item.run_id)
    ]


def _new_staging_path(destination: Path) -> Path:
    while True:
        candidate = destination.parent / (
            f".{destination.name}.adopt-{secrets.token_hex(6)}"
        )
        if not os.path.lexists(candidate):
            return candidate


def _create_missing_parents(parent: Path, root: Path) -> list[Path]:
    missing: list[Path] = []
    current = parent
    while current != root and not current.exists():
        missing.append(current)
        current = current.parent
    parent.mkdir(parents=True, exist_ok=True)
    return missing


def _remove_empty_tree(root: Path) -> None:
    paths = list(root.rglob("*"))
    non_directories = [path for path in paths if not path.is_dir()]
    if non_directories:
        raise OSError(f"Adoption staging directory is not empty: {non_directories[0]}")
    for path in sorted(paths, key=lambda item: len(item.parts), reverse=True):
        path.rmdir()
    root.rmdir()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _validate_destination_nesting(
    source: Path,
    destination: Path,
    label: str,
) -> str | None:
    if destination == source:
        return f"{label} destination is the source bundle: {destination}"
    if _is_relative_to(destination, source):
        return f"{label} destination cannot be inside the source bundle: {destination}"
    return None


def _validate_destination(source: Path, destination: Path, label: str) -> str | None:
    if destination == source:
        return f"{label} destination is the source bundle: {destination}"
    if os.path.lexists(destination):
        return f"{label} destination already exists: {destination}"
    try:
        destination.relative_to(source)
    except ValueError:
        return None
    return f"{label} destination cannot be inside the source bundle: {destination}"


def _write_toml_atomic(path: Path, data: dict[str, Any]) -> None:
    descriptor, temporary = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            tomli_w.dump(data, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        with suppress(OSError):
            os.unlink(temporary)
        raise


def _read_restore_destination(path: Path) -> tuple[Path | None, str | None]:
    try:
        with open(path, "rb") as stream:
            raw = tomllib.load(stream)
        bundle = raw.get("bundle")
        archived_from = (
            bundle.get("archived_from") if isinstance(bundle, dict) else None
        )
        if not isinstance(archived_from, str) or not archived_from:
            return None, f"Missing bundle.archived_from in {path}"
        destination = Path(archived_from).expanduser()
        if not destination.is_absolute():
            return (
                None,
                f"bundle.archived_from must be an absolute path: {archived_from}",
            )
        return destination.resolve(), None
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return None, f"Invalid archived bundle metadata {path}: {exc}"


def _rollback_move(
    *,
    current: Path,
    original: Path,
    runs: list[_BundleRun],
    remove_metadata: bool,
) -> str | None:
    try:
        for run in runs:
            manifest_path = current / run.relative_path / "manifest.toml"
            manifest_path.write_bytes(run.original_bytes)
        shutil.move(str(current), str(original))
        if remove_metadata:
            with suppress(OSError):
                (original / ARCHIVE_BUNDLE_METADATA_FILE).unlink()
    except (OSError, shutil.Error) as exc:
        return str(exc)
    return None
