"""Run lifecycle administration actions."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import secrets
import shutil
import stat
import sys
import tempfile
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

import tomli_w

from runops.application.actions.helpers import (
    _dir_size,
    _error,
    _precondition_fail,
    _require_state,
)
from runops.application.actions.result import ActionResult, ActionStatus
from runops.application.run_creation.staging import move_directory_noreplace
from runops.core.event_log import emit_event, logged_action
from runops.core.exceptions import ProjectNotFoundError, SimctlError
from runops.core.manifest import ManifestData
from runops.core.project import find_project_root
from runops.core.state import RunState

_ARCHIVE_DIR_NAME = "_archive"
_LIFECYCLE_RECEIPT_DIR = "lifecycle"
_LIFECYCLE_RECEIPT_KIND = "run-lifecycle-v1"
_LIFECYCLE_RECEIPT_VERSION = 1
_MAX_LIFECYCLE_RECEIPT_BYTES = 8 * 1024 * 1024
_MAX_LIFECYCLE_SNAPSHOT_BYTES = 2 * 1024 * 1024
_PURGE_RECEIPT_VERSION = 2


@dataclass(frozen=True)
class _LifecycleReceipt:
    """Validated write-ahead record for one Run archive/restore move."""

    action: str
    run_id: str
    source: Path
    destination: Path | None
    transition_at: str
    manifest_snapshot: bytes
    state_snapshot: bytes | None
    path: Path
    identity: tuple[int, int, int, int]


@dataclass(frozen=True)
class _LifecycleLiveImage:
    """Exact receipt-derived manifest/state images found at one endpoint."""

    manifest_phase: str
    state_is_postimage: bool
    manifest_identity: tuple[int, int, int, int]
    state_identity: tuple[int, int, int, int] | None


@dataclass(frozen=True)
class RunLifecycleRecovery:
    """Authoritatively validated pending recovery for one Run move."""

    run_id: str
    source: Path
    destination: Path | None
    current: Path


@dataclass(frozen=True)
class _PurgeReceipt:
    """Validated durable description of one in-progress purge transaction."""

    run_id: str
    tombstone: str
    targets: tuple[str, ...]
    bytes_staged: int
    compacted_at: str
    review_updates: dict[str, str]
    manifest_before_sha256: str
    manifest_after_sha256: str
    target_sha256: dict[str, str]
    tombstone_identity: tuple[int, int] | None
    target_identity: dict[str, tuple[int, int]]


@logged_action("review_run")
def review_run(
    run_dir: Path,
    *,
    reason: str,
    reviewed_by: str = "human",
) -> ActionResult:
    """Record that a terminal Run was reviewed without selecting evidence."""
    from runops.application.run_review import review_run as apply_review

    try:
        reviewed = apply_review(
            run_dir,
            reason=reason,
            reviewed_by=reviewed_by,
        )
    except SimctlError as exc:
        return _precondition_fail("review_run", str(exc))
    return ActionResult(
        action="review_run",
        status=ActionStatus.SUCCESS,
        message=f"Reviewed Run {reviewed.run_id}",
        data={
            "run_id": reviewed.run_id,
            "run_dir": str(reviewed.run_dir),
            "reason": reviewed.reason,
            "reviewed_by": reviewed.reviewed_by,
            "reviewed_at": reviewed.reviewed_at,
        },
    )


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


def _canonical_lifecycle_endpoint(path: Path) -> Path:
    """Resolve ancestors while retaining the final entry for symlink checks."""
    expanded = Path(os.path.abspath(path.expanduser()))
    return expanded.parent.resolve() / expanded.name


def _lifecycle_state_base(source: Path, *, create: bool) -> Path:
    """Return stable state outside a Run so its receipt survives directory moves."""
    from runops.application.state_root import require_project_state_root

    project_root = _find_project_root_or_none(source)
    if project_root is not None:
        if create or os.path.lexists(project_root / ".runops"):
            return require_project_state_root(project_root)
        return project_root.resolve() / ".runops"

    runs_root = next(
        (parent for parent in source.parents if parent.name == "runs"), None
    )
    if runs_root is not None:
        state_base = runs_root.parent / ".runops"
    else:
        state_base = source.parent / ".runops-lifecycle"
    if create:
        _require_real_directory(state_base, create=True)
    elif os.path.lexists(state_base):
        _require_real_directory(state_base, create=False)
    return state_base


def _require_real_directory(path: Path, *, create: bool) -> None:
    """Require one canonical directory without accepting a redirected path."""
    created = False
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        if not create:
            raise
        try:
            path.mkdir(mode=0o700)
            created = True
        except FileExistsError:
            pass
        metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise SimctlError(f"lifecycle state path must be a real directory: {path}")
    if path.resolve(strict=True) != path:
        raise SimctlError(f"lifecycle state path is not canonical: {path}")
    if created:
        _fsync_directory(path.parent)


def _lifecycle_receipt_path(action: str, source: Path, *, create: bool) -> Path:
    state_base = _lifecycle_state_base(source, create=create)
    receipt_dir = state_base / _LIFECYCLE_RECEIPT_DIR
    if create:
        _require_real_directory(receipt_dir, create=True)
    elif os.path.lexists(receipt_dir):
        _require_real_directory(receipt_dir, create=False)
    digest = hashlib.sha256(str(source).encode("utf-8")).hexdigest()[:24]
    return receipt_dir / f"{action}-{digest}.json"


def _read_single_link_regular(
    path: Path,
    *,
    maximum_bytes: int,
) -> tuple[bytes, tuple[int, int, int, int]]:
    """Read a bounded regular file without following or racing a symlink."""
    try:
        before = path.lstat()
    except OSError as exc:
        raise SimctlError(f"cannot inspect lifecycle file {path}: {exc}") from exc
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise SimctlError(f"lifecycle file must be a single-link regular file: {path}")
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise SimctlError(f"cannot safely open lifecycle file {path}: {exc}") from exc
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
        ):
            raise SimctlError(f"lifecycle file changed while opening: {path}")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(65536, maximum_bytes + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > maximum_bytes:
                raise SimctlError(f"lifecycle file is too large: {path}")
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    final = path.lstat()
    identity = (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
    final_identity = (final.st_dev, final.st_ino, final.st_size, final.st_mtime_ns)
    after_identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if (
        not stat.S_ISREG(final.st_mode)
        or final.st_nlink != 1
        or identity != after_identity
        or identity != final_identity
    ):
        raise SimctlError(f"lifecycle file changed while being read: {path}")
    return b"".join(chunks), identity


def _snapshot_lifecycle_file(path: Path, *, required: bool) -> bytes | None:
    if not os.path.lexists(path):
        if required:
            raise SimctlError(f"required lifecycle file does not exist: {path}")
        return None
    payload, _identity = _read_single_link_regular(
        path,
        maximum_bytes=_MAX_LIFECYCLE_SNAPSHOT_BYTES,
    )
    return payload


def _parse_lifecycle_receipt_path(raw: object, *, field: str) -> Path | None:
    if raw == "" and field == "destination":
        return None
    if not isinstance(raw, str) or not raw:
        raise SimctlError(f"invalid lifecycle receipt {field}")
    candidate = Path(raw)
    if not candidate.is_absolute() or str(candidate) != raw:
        raise SimctlError(f"lifecycle receipt {field} must be an absolute path")
    canonical = candidate.parent.resolve() / candidate.name
    if canonical != candidate:
        raise SimctlError(f"lifecycle receipt {field} is not canonical: {candidate}")
    return candidate


def _decode_lifecycle_snapshot(raw: object, *, field: str) -> bytes:
    if not isinstance(raw, str):
        raise SimctlError(f"invalid lifecycle receipt {field}")
    try:
        payload = base64.b64decode(raw.encode("ascii"), validate=True)
    except (UnicodeEncodeError, ValueError) as exc:
        raise SimctlError(f"invalid lifecycle receipt {field}: {exc}") from exc
    if len(payload) > _MAX_LIFECYCLE_SNAPSHOT_BYTES:
        raise SimctlError(f"lifecycle receipt {field} is too large")
    return payload


def _validate_manifest_snapshot(
    payload: bytes,
    *,
    run_id: str,
    action: str,
) -> None:
    try:
        raw = tomllib.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise SimctlError(
            f"invalid manifest snapshot in lifecycle receipt: {exc}"
        ) from exc
    run = raw.get("run")
    expected_state = (
        RunState.COMPLETED.value if action == "archive_run" else RunState.ARCHIVED.value
    )
    if (
        not isinstance(run, dict)
        or run.get("id") != run_id
        or run.get("status") != expected_state
    ):
        raise SimctlError(
            "lifecycle receipt manifest snapshot does not match its Run identity"
        )


def _load_lifecycle_receipt(
    action: str,
    source: Path,
) -> _LifecycleReceipt | None:
    path = _lifecycle_receipt_path(action, source, create=False)
    if not os.path.lexists(path):
        return None
    payload, identity = _read_single_link_regular(
        path,
        maximum_bytes=_MAX_LIFECYCLE_RECEIPT_BYTES,
    )
    try:
        raw = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SimctlError(f"invalid lifecycle receipt {path}: {exc}") from exc
    fields = {
        "schema_version",
        "kind",
        "action",
        "run_id",
        "source",
        "destination",
        "transition_at",
        "manifest_snapshot_b64",
        "manifest_sha256",
        "state_present",
        "state_snapshot_b64",
        "state_sha256",
    }
    if not isinstance(raw, dict) or set(raw) != fields:
        raise SimctlError(f"invalid lifecycle receipt schema: {path}")
    run_id = raw.get("run_id")
    transition_at = raw.get("transition_at")
    if (
        type(raw.get("schema_version")) is not int
        or raw.get("schema_version") != _LIFECYCLE_RECEIPT_VERSION
        or raw.get("kind") != _LIFECYCLE_RECEIPT_KIND
        or raw.get("action") != action
        or not isinstance(run_id, str)
        or not run_id
        or not isinstance(transition_at, str)
        or not transition_at
        or type(raw.get("state_present")) is not bool
    ):
        raise SimctlError(f"invalid lifecycle receipt fields: {path}")
    try:
        timestamp = datetime.fromisoformat(transition_at)
    except ValueError as exc:
        raise SimctlError(f"invalid lifecycle receipt timestamp: {path}") from exc
    if timestamp.tzinfo is None:
        raise SimctlError(f"lifecycle receipt timestamp lacks timezone: {path}")
    recorded_source = _parse_lifecycle_receipt_path(raw.get("source"), field="source")
    destination = _parse_lifecycle_receipt_path(
        raw.get("destination"),
        field="destination",
    )
    if recorded_source != source:
        raise SimctlError(f"lifecycle receipt source does not match command: {path}")
    manifest_snapshot = _decode_lifecycle_snapshot(
        raw.get("manifest_snapshot_b64"),
        field="manifest_snapshot_b64",
    )
    manifest_sha = raw.get("manifest_sha256")
    if (
        not isinstance(manifest_sha, str)
        or hashlib.sha256(manifest_snapshot).hexdigest() != manifest_sha
    ):
        raise SimctlError(f"lifecycle receipt manifest digest mismatch: {path}")
    state_present = raw["state_present"]
    raw_state = raw.get("state_snapshot_b64")
    raw_state_sha = raw.get("state_sha256")
    if state_present:
        state_snapshot = _decode_lifecycle_snapshot(
            raw_state,
            field="state_snapshot_b64",
        )
        if (
            not isinstance(raw_state_sha, str)
            or hashlib.sha256(state_snapshot).hexdigest() != raw_state_sha
        ):
            raise SimctlError(f"lifecycle receipt state digest mismatch: {path}")
    else:
        if raw_state != "" or raw_state_sha != "":
            raise SimctlError(f"invalid absent state snapshot in receipt: {path}")
        state_snapshot = None
    _validate_manifest_snapshot(manifest_snapshot, run_id=run_id, action=action)
    return _LifecycleReceipt(
        action=action,
        run_id=run_id,
        source=source,
        destination=destination,
        transition_at=transition_at,
        manifest_snapshot=manifest_snapshot,
        state_snapshot=state_snapshot,
        path=path,
        identity=identity,
    )


def _load_lifecycle_receipt_at_path(
    action: str,
    path: Path,
) -> _LifecycleReceipt:
    """Load one discovered receipt without trusting its source or filename."""
    payload, identity = _read_single_link_regular(
        path,
        maximum_bytes=_MAX_LIFECYCLE_RECEIPT_BYTES,
    )
    try:
        raw = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SimctlError(f"invalid lifecycle receipt {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise SimctlError(f"invalid lifecycle receipt schema: {path}")
    source = _parse_lifecycle_receipt_path(raw.get("source"), field="source")
    if source is None:
        raise SimctlError(f"invalid lifecycle receipt source: {path}")
    expected_path = _lifecycle_receipt_path(action, source, create=False)
    if expected_path != path:
        raise SimctlError(
            f"lifecycle receipt filename does not match its recorded source: {path}"
        )
    receipt = _load_lifecycle_receipt(action, source)
    if receipt is None:
        raise SimctlError(f"lifecycle receipt disappeared while inspecting: {path}")
    if receipt.identity != identity:
        raise SimctlError(f"lifecycle receipt changed while inspecting: {path}")
    return receipt


def _project_lifecycle_receipts(
    action: str,
    scope: Path,
) -> tuple[tuple[Path, _LifecycleReceipt], ...]:
    """Enumerate strict receipts from the managed project containing ``scope``."""
    canonical_scope = _canonical_lifecycle_endpoint(scope)
    try:
        project_root = find_project_root(canonical_scope).resolve()
    except ProjectNotFoundError:
        return ()
    receipt_dir = project_root / ".runops" / _LIFECYCLE_RECEIPT_DIR
    if not os.path.lexists(receipt_dir):
        return ()
    _require_real_directory(receipt_dir, create=False)
    try:
        entries = sorted(receipt_dir.iterdir())
    except OSError as exc:
        raise SimctlError(
            f"cannot enumerate lifecycle receipts in {receipt_dir}: {exc}"
        ) from exc

    prefix = f"{action}-"
    receipts: list[tuple[Path, _LifecycleReceipt]] = []
    for entry in entries:
        if not entry.name.startswith(prefix):
            continue
        if not entry.name.endswith(".json"):
            raise SimctlError(f"invalid lifecycle receipt filename: {entry}")
        receipt = _load_lifecycle_receipt_at_path(action, entry)
        receipt_project = _find_project_root_or_none(receipt.source)
        if receipt_project is None or receipt_project.resolve() != project_root:
            raise SimctlError(
                "lifecycle receipt source is outside the selected project: "
                f"{receipt.source}"
            )
        receipts.append((canonical_scope, receipt))
    return tuple(receipts)


def _validate_discovered_lifecycle_receipt(
    receipt: _LifecycleReceipt,
    *,
    project_root: Path,
) -> Path:
    """Validate namespace, topology, and live identity for a scanned receipt."""
    runs_entry = project_root / "runs"
    if runs_entry.is_symlink() or not runs_entry.is_dir():
        raise SimctlError(
            f"managed project runs/ must be a real directory: {runs_entry}"
        )
    runs_root = runs_entry.resolve()
    try:
        relative_source = receipt.source.relative_to(runs_root)
    except ValueError as exc:
        raise SimctlError(
            f"lifecycle receipt source is outside project runs/: {receipt.source}"
        ) from exc
    if not relative_source.parts:
        raise SimctlError(
            f"lifecycle receipt source is not a Run path: {receipt.source}"
        )
    if (
        receipt.action == "archive_run"
        and relative_source.parts[0] == _ARCHIVE_DIR_NAME
    ):
        raise SimctlError(
            f"archive receipt source is not in the active runs/ view: {receipt.source}"
        )
    if (
        receipt.action == "restore_run"
        and receipt.destination is not None
        and relative_source.parts[0] != _ARCHIVE_DIR_NAME
    ):
        raise SimctlError(
            "restore receipt source is not in managed archive storage: "
            f"{receipt.source}"
        )
    namespace_error = _pending_lifecycle_namespace_error(receipt)
    if namespace_error:
        raise SimctlError(namespace_error)
    current = _lifecycle_current_directory(receipt)
    _validate_lifecycle_live_image(receipt, current)
    return current


def _select_project_lifecycle_recoveries(
    action: str,
    scope: Path,
    *,
    run_id: str | None,
) -> tuple[RunLifecycleRecovery, ...]:
    """Resolve pending receipts by exact Run ID or original source scope."""
    discovered = _project_lifecycle_receipts(action, scope)
    if not discovered:
        return ()
    project_root = find_project_root(scope).resolve()
    selected: list[RunLifecycleRecovery] = []
    for canonical_scope, receipt in discovered:
        current = _validate_discovered_lifecycle_receipt(
            receipt,
            project_root=project_root,
        )
        if run_id is not None:
            matches_scope = receipt.run_id == run_id
        else:
            try:
                receipt.source.relative_to(canonical_scope)
            except ValueError:
                matches_scope = False
            else:
                matches_scope = True
        if not matches_scope:
            continue
        selected.append(
            RunLifecycleRecovery(
                run_id=receipt.run_id,
                source=receipt.source,
                destination=receipt.destination,
                current=current,
            )
        )

    by_run_id: dict[str, list[RunLifecycleRecovery]] = {}
    for recovery in selected:
        by_run_id.setdefault(recovery.run_id, []).append(recovery)
    duplicates = {
        candidate_id: recoveries
        for candidate_id, recoveries in by_run_id.items()
        if len(recoveries) > 1
    }
    if duplicates:
        duplicate_id = sorted(duplicates)[0]
        label = "archive" if action == "archive_run" else "restore"
        paths = ", ".join(str(recovery.source) for recovery in duplicates[duplicate_id])
        raise SimctlError(
            f"multiple pending {label} recoveries match Run ID {duplicate_id}: {paths}"
        )
    if run_id is not None and selected:
        from runops.application.run_discovery import resolve_project_run_strict

        resolved_path, _manifest = resolve_project_run_strict(project_root, run_id)
        if resolved_path != selected[0].current:
            raise SimctlError(
                "pending lifecycle recovery does not match the authoritative "
                f"Run ID location: {resolved_path}"
            )
    return tuple(sorted(selected, key=lambda recovery: recovery.source))


def _write_lifecycle_receipt(
    *,
    action: str,
    run_id: str,
    source: Path,
    destination: Path | None,
    transition_at: str,
    manifest_snapshot: bytes,
    state_snapshot: bytes | None,
) -> _LifecycleReceipt:
    path = _lifecycle_receipt_path(action, source, create=True)
    if os.path.lexists(path):
        raise SimctlError(f"pending lifecycle receipt already exists: {path}")
    payload = {
        "schema_version": _LIFECYCLE_RECEIPT_VERSION,
        "kind": _LIFECYCLE_RECEIPT_KIND,
        "action": action,
        "run_id": run_id,
        "source": str(source),
        "destination": str(destination) if destination is not None else "",
        "transition_at": transition_at,
        "manifest_snapshot_b64": base64.b64encode(manifest_snapshot).decode("ascii"),
        "manifest_sha256": hashlib.sha256(manifest_snapshot).hexdigest(),
        "state_present": state_snapshot is not None,
        "state_snapshot_b64": (
            base64.b64encode(state_snapshot).decode("ascii")
            if state_snapshot is not None
            else ""
        ),
        "state_sha256": (
            hashlib.sha256(state_snapshot).hexdigest()
            if state_snapshot is not None
            else ""
        ),
    }
    encoded = (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8")
    _restore_file_snapshot(path, encoded)
    loaded = _load_lifecycle_receipt(action, source)
    if loaded is None:
        raise SimctlError(f"lifecycle receipt disappeared after creation: {path}")
    return loaded


def _remove_lifecycle_receipt(receipt: _LifecycleReceipt) -> None:
    """Remove only the exact receipt inode that was validated under locks."""
    payload, identity = _read_single_link_regular(
        receipt.path,
        maximum_bytes=_MAX_LIFECYCLE_RECEIPT_BYTES,
    )
    del payload
    if identity != receipt.identity:
        raise SimctlError(f"lifecycle receipt changed before cleanup: {receipt.path}")
    receipt.path.unlink()
    _fsync_directory(receipt.path.parent)


def _validate_lifecycle_run_directory(path: Path) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise SimctlError(
            f"cannot inspect lifecycle Run directory {path}: {exc}"
        ) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise SimctlError(f"lifecycle Run path must be a real directory: {path}")
    if path.resolve(strict=True) != path:
        raise SimctlError(f"lifecycle Run path is not canonical: {path}")
    _snapshot_lifecycle_file(path / "manifest.toml", required=True)
    status = path / "status"
    if os.path.lexists(status):
        status_metadata = status.lstat()
        if stat.S_ISLNK(status_metadata.st_mode) or not stat.S_ISDIR(
            status_metadata.st_mode
        ):
            raise SimctlError(
                f"lifecycle status path must be a real directory: {status}"
            )


def _lifecycle_current_directory(receipt: _LifecycleReceipt) -> Path:
    source_exists = os.path.lexists(receipt.source)
    destination_exists = receipt.destination is not None and os.path.lexists(
        receipt.destination
    )
    if receipt.destination is None:
        if not source_exists:
            raise SimctlError(f"in-place lifecycle Run disappeared: {receipt.source}")
        current = receipt.source
    else:
        if source_exists == destination_exists:
            raise SimctlError(
                "lifecycle receipt topology requires exactly one Run endpoint: "
                f"source={source_exists}, destination={destination_exists}"
            )
        current = receipt.source if source_exists else receipt.destination
    _validate_lifecycle_run_directory(current)
    return current


def _pending_lifecycle_namespace_error(
    receipt: _LifecycleReceipt,
) -> str | None:
    destination = receipt.destination
    if destination is None:
        return None
    try:
        destination.relative_to(receipt.source)
    except ValueError:
        pass
    else:
        return f"lifecycle destination cannot be inside its source: {destination}"
    if receipt.action == "archive_run":
        return _validate_project_archive_destination(receipt.source, destination)
    if receipt.action == "restore_run":
        return _validate_project_restore_destination(receipt.source, destination)
    return f"unsupported lifecycle receipt action: {receipt.action}"


def _write_lifecycle_state_mirror(
    run_dir: Path,
    *,
    state: RunState,
    previous: RunState,
    transition_at: str,
) -> None:
    payload = {
        "state": state.value,
        "previous_state": previous.value,
        "changed_at": transition_at,
    }
    _restore_file_snapshot(
        run_dir / "status" / "state.json",
        (json.dumps(payload, indent=2) + "\n").encode("utf-8"),
    )


def _lifecycle_transition_states(
    action: str,
) -> tuple[RunState, RunState]:
    if action == "archive_run":
        return RunState.COMPLETED, RunState.ARCHIVED
    if action == "restore_run":
        return RunState.ARCHIVED, RunState.COMPLETED
    raise SimctlError(f"unsupported lifecycle receipt action: {action}")


def _expected_lifecycle_manifest_images(
    receipt: _LifecycleReceipt,
) -> tuple[bytes, bytes]:
    """Derive the only transition and committed manifests this receipt owns."""
    try:
        snapshot = tomllib.loads(receipt.manifest_snapshot.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise SimctlError(
            f"invalid manifest snapshot in lifecycle receipt: {exc}"
        ) from exc

    before, after = _lifecycle_transition_states(receipt.action)
    canonical = ManifestData.from_dict(snapshot).to_dict()
    run = canonical.get("run")
    if not isinstance(run, dict) or run.get("status") != before.value:
        raise SimctlError("lifecycle receipt manifest snapshot has an unexpected state")

    transitioned = copy.deepcopy(canonical)
    transitioned["run"]["status"] = after.value

    committed = copy.deepcopy(transitioned)
    final_dir = receipt.destination or receipt.source
    path = committed.setdefault("path", {})
    storage = committed.setdefault("storage", {})
    if not isinstance(path, dict) or not isinstance(storage, dict):
        raise SimctlError(
            "lifecycle receipt manifest snapshot has invalid path/storage sections"
        )
    if receipt.action == "archive_run":
        if "created_at_path" not in path:
            path["created_at_path"] = str(receipt.source)
        path["run_dir"] = str(final_dir)
        path["archived_from"] = str(receipt.source)
        path["archived_at"] = receipt.transition_at
        storage["tier"] = "cold"
        if not storage.get("form"):
            storage["form"] = "full"
    else:
        path["run_dir"] = str(final_dir)
        path["restored_from"] = str(receipt.source)
        path["restored_at"] = receipt.transition_at
        storage["tier"] = "hot"

    return (
        tomli_w.dumps(ManifestData.from_dict(transitioned).to_dict()).encode("utf-8"),
        tomli_w.dumps(ManifestData.from_dict(committed).to_dict()).encode("utf-8"),
    )


def _expected_lifecycle_state_postimage(receipt: _LifecycleReceipt) -> bytes:
    before, after = _lifecycle_transition_states(receipt.action)
    payload = {
        "state": after.value,
        "previous_state": before.value,
        "changed_at": receipt.transition_at,
    }
    return (json.dumps(payload, indent=2) + "\n").encode("utf-8")


def _validate_lifecycle_live_image(
    receipt: _LifecycleReceipt,
    current: Path,
) -> _LifecycleLiveImage:
    """Require exact preimages or deterministic transaction-owned postimages.

    Manifest and state writes are separate atomic replacements.  Their exact
    trusted images may therefore be observed in any combination while a
    forward operation or rollback is interrupted.  No other content is safe
    to overwrite, move, or use for receipt cleanup.
    """
    manifest, manifest_identity = _read_single_link_regular(
        current / "manifest.toml",
        maximum_bytes=_MAX_LIFECYCLE_SNAPSHOT_BYTES,
    )
    state_path = current / "status" / "state.json"
    try:
        state_path.lstat()
    except FileNotFoundError:
        state = None
        state_identity = None
    except OSError as exc:
        raise SimctlError(f"cannot inspect lifecycle file {state_path}: {exc}") from exc
    else:
        state, state_identity = _read_single_link_regular(
            state_path,
            maximum_bytes=_MAX_LIFECYCLE_SNAPSHOT_BYTES,
        )
    transitioned, committed = _expected_lifecycle_manifest_images(receipt)
    manifest_images = {
        receipt.manifest_snapshot: "preimage",
        transitioned: "transitioned",
        committed: "committed",
    }
    manifest_phase = manifest_images.get(manifest)
    if manifest_phase is None:
        raise SimctlError(
            "lifecycle receipt/live manifest digest mismatch; refusing recovery"
        )

    state_postimage = _expected_lifecycle_state_postimage(receipt)
    if state == receipt.state_snapshot:
        state_is_postimage = False
    elif state == state_postimage:
        state_is_postimage = True
    else:
        raise SimctlError(
            "lifecycle receipt/live state digest mismatch; refusing recovery"
        )

    final_dir = receipt.destination or receipt.source
    if manifest_phase == "committed" and current != final_dir:
        raise SimctlError(
            "committed lifecycle postimage is at the wrong endpoint; refusing recovery"
        )
    return _LifecycleLiveImage(
        manifest_phase=manifest_phase,
        state_is_postimage=state_is_postimage,
        manifest_identity=manifest_identity,
        state_identity=state_identity,
    )


def _remove_lifecycle_receipt_for_live_image(
    receipt: _LifecycleReceipt,
    current: Path,
    *,
    manifest_phase: str,
    state_is_postimage: bool,
) -> None:
    """Remove a receipt only while its exact expected live image stays stable."""
    live_image = _validate_lifecycle_live_image(receipt, current)
    if (
        live_image.manifest_phase != manifest_phase
        or live_image.state_is_postimage is not state_is_postimage
    ):
        raise SimctlError(
            "lifecycle receipt cleanup refused for an unexpected live phase"
        )

    _manifest, manifest_identity = _read_single_link_regular(
        current / "manifest.toml",
        maximum_bytes=_MAX_LIFECYCLE_SNAPSHOT_BYTES,
    )
    state_path = current / "status" / "state.json"
    try:
        state_path.lstat()
    except FileNotFoundError:
        state_identity = None
    except OSError as exc:
        raise SimctlError(f"cannot inspect lifecycle file {state_path}: {exc}") from exc
    else:
        _state, state_identity = _read_single_link_regular(
            state_path,
            maximum_bytes=_MAX_LIFECYCLE_SNAPSHOT_BYTES,
        )
    if (
        manifest_identity != live_image.manifest_identity
        or state_identity != live_image.state_identity
    ):
        raise SimctlError(
            "lifecycle live image changed before receipt cleanup; refusing cleanup"
        )
    _remove_lifecycle_receipt(receipt)


def _archive_run_under_guard(
    run_dir: Path, *, move_to: Path | None = None
) -> ActionResult:
    """Archive or forward-resume one receipt-backed Run transaction."""
    from runops.core.manifest import read_manifest, write_manifest
    from runops.core.state import update_state

    receipt: _LifecycleReceipt | None = None
    try:
        source = _canonical_lifecycle_endpoint(run_dir)
        requested_destination = (
            _canonical_lifecycle_endpoint(move_to) if move_to is not None else None
        )
        if requested_destination == source:
            requested_destination = None
        receipt = _load_lifecycle_receipt("archive_run", source)
        if receipt is not None and receipt.destination != requested_destination:
            return _precondition_fail(
                "archive_run",
                "pending archive receipt destination does not match this command",
            )
        if receipt is not None:
            namespace_error = _pending_lifecycle_namespace_error(receipt)
            if namespace_error:
                return _precondition_fail("archive_run", namespace_error)
        if receipt is None:
            completed_dir = requested_destination or source
            if _completed_archive_matches(
                completed_dir,
                source=source,
                destination=requested_destination,
            ):
                return _archive_success(
                    run_id=_completed_run_id(completed_dir),
                    source=source,
                    destination=requested_destination,
                    cleanup_pending="",
                )
            _validate_lifecycle_run_directory(source)
            _state_before, err = _require_state(source, RunState.COMPLETED)
            if err:
                return _precondition_fail("archive_run", err)
            destination = requested_destination
            if destination is not None:
                collision_error = _validate_archive_destination(source, destination)
                if collision_error:
                    return _precondition_fail("archive_run", collision_error)
                namespace_error = _validate_project_archive_destination(
                    source,
                    destination,
                )
                if namespace_error:
                    return _precondition_fail("archive_run", namespace_error)
            manifest_snapshot = _snapshot_lifecycle_file(
                source / "manifest.toml",
                required=True,
            )
            assert manifest_snapshot is not None
            state_snapshot = _snapshot_lifecycle_file(
                source / "status" / "state.json",
                required=False,
            )
            manifest_before = read_manifest(source)
            run_id = str(manifest_before.run.get("id", source.name))
            transition_at = datetime.now(tz=timezone.utc).isoformat()
            receipt = _write_lifecycle_receipt(
                action="archive_run",
                run_id=run_id,
                source=source,
                destination=destination,
                transition_at=transition_at,
                manifest_snapshot=manifest_snapshot,
                state_snapshot=state_snapshot,
            )
        assert receipt is not None
        current = _lifecycle_current_directory(receipt)
        live_image = _validate_lifecycle_live_image(receipt, current)
        transition_time = datetime.fromisoformat(receipt.transition_at)
        if live_image.manifest_phase == "preimage":
            update_state(
                current,
                RunState.ARCHIVED,
                timestamp=transition_time,
            )
            live_image = _validate_lifecycle_live_image(receipt, current)
        if not live_image.state_is_postimage:
            _write_lifecycle_state_mirror(
                current,
                state=RunState.ARCHIVED,
                previous=RunState.COMPLETED,
                transition_at=receipt.transition_at,
            )
            live_image = _validate_lifecycle_live_image(receipt, current)
        if live_image.manifest_phase not in {"transitioned", "committed"}:
            raise SimctlError(
                "pending archive did not reach its deterministic transition image"
            )

        destination = receipt.destination
        if (
            live_image.manifest_phase == "transitioned"
            and destination is not None
            and current == source
        ):
            destination.parent.mkdir(parents=True, exist_ok=True)
            move_directory_noreplace(source, destination)
            current = destination
            live_image = _validate_lifecycle_live_image(receipt, current)

        if live_image.manifest_phase == "transitioned":
            manifest = read_manifest(current)
            if "created_at_path" not in manifest.path:
                manifest.path["created_at_path"] = str(source)
            manifest.path["run_dir"] = str(current)
            manifest.path["archived_from"] = str(source)
            manifest.path["archived_at"] = receipt.transition_at
            manifest.storage["tier"] = "cold"
            if not manifest.storage.get("form"):
                manifest.storage["form"] = "full"
            write_manifest(current, manifest)
            live_image = _validate_lifecycle_live_image(receipt, current)
        if (
            live_image.manifest_phase != "committed"
            or not live_image.state_is_postimage
        ):
            raise SimctlError(
                "archive transaction did not reach its exact committed postimage"
            )
        if not _completed_archive_matches(
            current,
            source=source,
            destination=destination,
        ):
            raise SimctlError("archive transaction did not commit complete metadata")
    except (OSError, SimctlError) as exc:
        if receipt is None:
            return _error("archive_run", str(exc))
        recovery_errors = _rollback_lifecycle_transaction(receipt)
        message = f"Failed to commit archive transaction; rollback attempted: {exc}"
        if recovery_errors:
            message += "; " + "; ".join(recovery_errors)
        return _error("archive_run", message)

    cleanup_pending = ""
    try:
        _remove_lifecycle_receipt_for_live_image(
            receipt,
            current,
            manifest_phase="committed",
            state_is_postimage=True,
        )
    except (OSError, SimctlError):
        cleanup_pending = str(receipt.path)

    if destination is not None:
        emit_event(
            "artifact_move",
            action="archive_run",
            summary=f"Move archived run {receipt.run_id}",
            path=current,
            data={
                "run_id": receipt.run_id,
                "source_path": str(source),
                "archive_path": str(current),
            },
            requires_verbose=True,
        )
    return _archive_success(
        run_id=receipt.run_id,
        source=source,
        destination=destination,
        cleanup_pending=cleanup_pending,
    )


def _completed_lifecycle_state_matches(
    run_dir: Path,
    *,
    state: RunState,
    previous: RunState,
    transition_at: str,
) -> bool:
    try:
        payload = _snapshot_lifecycle_file(
            run_dir / "status" / "state.json",
            required=True,
        )
        assert payload is not None
        raw = json.loads(payload)
    except (AssertionError, OSError, SimctlError, UnicodeDecodeError, ValueError):
        return False
    return bool(
        raw
        == {
            "state": state.value,
            "previous_state": previous.value,
            "changed_at": transition_at,
        }
    )


def _completed_archive_matches(
    run_dir: Path,
    *,
    source: Path,
    destination: Path | None,
) -> bool:
    from runops.core.manifest import read_manifest

    expected = destination or source
    if run_dir != expected or not os.path.lexists(run_dir):
        return False
    try:
        _validate_lifecycle_run_directory(run_dir)
        manifest = read_manifest(run_dir)
    except (OSError, SimctlError):
        return False
    archived_at = manifest.path.get("archived_at")
    if not isinstance(archived_at, str) or not archived_at:
        return False
    try:
        timestamp = datetime.fromisoformat(archived_at)
    except ValueError:
        return False
    if timestamp.tzinfo is None:
        return False
    return bool(
        manifest.run.get("id")
        and manifest.run.get("status") == RunState.ARCHIVED.value
        and manifest.path.get("run_dir") == str(run_dir)
        and manifest.path.get("archived_from") == str(source)
        and manifest.storage.get("tier") == "cold"
        and manifest.storage.get("form")
        and _completed_lifecycle_state_matches(
            run_dir,
            state=RunState.ARCHIVED,
            previous=RunState.COMPLETED,
            transition_at=archived_at,
        )
    )


def _completed_run_id(run_dir: Path) -> str:
    from runops.core.manifest import read_manifest

    return str(read_manifest(run_dir).run.get("id", run_dir.name))


def _archive_success(
    *,
    run_id: str,
    source: Path,
    destination: Path | None,
    cleanup_pending: str,
) -> ActionResult:
    final_dir = destination or source
    return ActionResult(
        action="archive_run",
        status=ActionStatus.SUCCESS,
        message=(
            "Run archived; lifecycle receipt cleanup remains pending"
            if cleanup_pending
            else "Run archived"
        ),
        data={
            "run_id": run_id,
            "moved": destination is not None,
            "source_path": str(source),
            "archive_path": str(final_dir),
            "cleanup_pending": cleanup_pending,
        },
        state_before=RunState.COMPLETED.value,
        state_after=RunState.ARCHIVED.value,
    )


def _rollback_lifecycle_transaction(receipt: _LifecycleReceipt) -> list[str]:
    """Restore exact metadata bytes and original topology after a normal error."""
    errors: list[str] = []
    try:
        current = _lifecycle_current_directory(receipt)
        _validate_lifecycle_live_image(receipt, current)
    except SimctlError as exc:
        return [f"rollback refused without an exact trusted live image: {exc}"]
    try:
        _restore_file_snapshot(current / "manifest.toml", receipt.manifest_snapshot)
    except OSError as exc:
        errors.append(f"manifest restore failed: {exc}")
    try:
        _restore_file_snapshot(
            current / "status" / "state.json",
            receipt.state_snapshot,
        )
    except OSError as exc:
        errors.append(f"state restore failed: {exc}")
    if (
        receipt.destination is not None
        and current == receipt.destination
        and not errors
    ):
        try:
            _validate_lifecycle_live_image(receipt, current)
            receipt.source.parent.mkdir(parents=True, exist_ok=True)
            move_directory_noreplace(receipt.destination, receipt.source)
            current = receipt.source
        except (OSError, SimctlError) as exc:
            errors.append(f"directory rollback failed: {exc}")
    if not errors:
        try:
            current = _lifecycle_current_directory(receipt)
            live_image = _validate_lifecycle_live_image(receipt, current)
            if live_image.manifest_phase != "preimage" or live_image.state_is_postimage:
                raise SimctlError(
                    "lifecycle rollback did not restore the exact preimage"
                )
            _remove_lifecycle_receipt_for_live_image(
                receipt,
                current,
                manifest_phase="preimage",
                state_is_postimage=False,
            )
        except (OSError, SimctlError) as exc:
            errors.append(f"receipt cleanup failed: {exc}")
    return errors


def inspect_archive_recovery(
    run_dir: Path,
    *,
    move_to: Path | None,
) -> str | None:
    """Return the Run ID when an exact archive command can safely resume."""
    source = _canonical_lifecycle_endpoint(run_dir)
    destination = (
        _canonical_lifecycle_endpoint(move_to) if move_to is not None else None
    )
    if destination == source:
        destination = None
    pending = _load_lifecycle_receipt("archive_run", source)
    if pending is not None:
        if pending.destination != destination:
            raise SimctlError(
                "pending archive receipt destination does not match this command"
            )
        namespace_error = _pending_lifecycle_namespace_error(pending)
        if namespace_error:
            raise SimctlError(namespace_error)
        current = _lifecycle_current_directory(pending)
        _validate_lifecycle_live_image(pending, current)
        return pending.run_id
    completed_dir = destination or source
    if _completed_archive_matches(
        completed_dir,
        source=source,
        destination=destination,
    ):
        return _completed_run_id(completed_dir)
    return None


def inspect_archive_recoveries(
    scope: Path,
    *,
    run_id: str | None = None,
    archive_root: Path | None = None,
    keep_in_place: bool = False,
) -> tuple[RunLifecycleRecovery, ...]:
    """Find pending archive transactions selected by Run ID or source scope.

    The returned source paths are suitable for passing back to
    :func:`archive_run`.  Every candidate receipt is strictly decoded and its
    managed namespace, topology, live Run identity, and exact command
    destination are revalidated before it is returned.
    """
    recoveries = _select_project_lifecycle_recoveries(
        "archive_run",
        scope,
        run_id=run_id,
    )
    for recovery in recoveries:
        expected_destination = (
            None
            if keep_in_place
            else default_archive_destination(
                recovery.source,
                archive_root=archive_root,
            )
        )
        if expected_destination == recovery.source:
            expected_destination = None
        if recovery.destination != expected_destination:
            raise SimctlError(
                "pending archive receipt destination does not match this command"
            )
        inspected_id = inspect_archive_recovery(
            recovery.source,
            move_to=expected_destination,
        )
        if inspected_id != recovery.run_id:
            raise SimctlError(
                "pending archive receipt changed during recovery inspection"
            )
    return recoveries


@logged_action("archive_run")
def archive_run(run_dir: Path, *, move_to: Path | None = None) -> ActionResult:
    """Archive a Run while serializing against every run-local mutation."""
    from runops.application.execution.submission import (
        SubmissionLockError,
        submission_guard,
    )
    from runops.application.run_namespace import run_namespace_guard

    try:
        source = _canonical_lifecycle_endpoint(run_dir)
        destination = (
            _canonical_lifecycle_endpoint(move_to) if move_to is not None else None
        )
        if destination == source:
            destination = None
        pending = _load_lifecycle_receipt("archive_run", source)
        if pending is not None:
            if pending.destination != destination:
                return _precondition_fail(
                    "archive_run",
                    "pending archive receipt destination does not match this command",
                )
            namespace_error = _pending_lifecycle_namespace_error(pending)
            if namespace_error:
                return _precondition_fail("archive_run", namespace_error)
            lock_target = _lifecycle_current_directory(pending)
            _validate_lifecycle_live_image(pending, lock_target)
        elif os.path.lexists(source):
            _validate_lifecycle_run_directory(source)
            lock_target = source
        elif destination is not None and _completed_archive_matches(
            destination,
            source=source,
            destination=destination,
        ):
            lock_target = destination
        else:
            return _precondition_fail(
                "archive_run",
                "Run archive source does not exist and no recovery is provable: "
                f"{source}",
            )
        project_root = _find_project_root_or_none(source)
        namespace_guard = (
            run_namespace_guard(project_root)
            if project_root is not None
            else nullcontext()
        )
        with submission_guard(lock_target), namespace_guard:
            return _archive_run_under_guard(source, move_to=move_to)
    except (SubmissionLockError, SimctlError) as exc:
        return _precondition_fail(
            "archive_run", f"cannot safely continue Run archive: {exc}"
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


def _validate_project_archive_destination(
    source: Path,
    destination: Path,
) -> str | None:
    project_root = _find_project_root_or_none(source)
    if project_root is None:
        return None
    runs_entry = project_root / "runs"
    if runs_entry.is_symlink():
        return f"Managed project runs/ must not be a symlink: {runs_entry}"
    runs_root = runs_entry.resolve()
    archive_entry = runs_entry / _ARCHIVE_DIR_NAME
    if archive_entry.is_symlink():
        return f"Managed archive root must not be a symlink: {archive_entry}"
    if os.path.lexists(archive_entry) and not archive_entry.is_dir():
        return f"Managed archive root must be a directory: {archive_entry}"
    archive_root = archive_entry.resolve()
    try:
        archive_root.relative_to(runs_root)
    except ValueError:
        return f"Managed archive root escapes project runs/: {archive_entry}"
    try:
        destination.relative_to(archive_root)
    except ValueError:
        return (
            "Managed project Runs must be archived inside "
            f"{archive_root}; external --move-to would bypass Result and budget gates"
        )
    return None


def _validate_project_restore_destination(
    source: Path,
    destination: Path,
) -> str | None:
    project_root = _find_project_root_or_none(source)
    if project_root is None:
        return None
    runs_entry = project_root / "runs"
    if runs_entry.is_symlink():
        return f"Managed project runs/ must not be a symlink: {runs_entry}"
    runs_root = runs_entry.resolve()
    try:
        relative = destination.relative_to(runs_root)
    except ValueError:
        return f"Managed project Runs must be restored inside {runs_root}"
    if relative.parts and relative.parts[0] == _ARCHIVE_DIR_NAME:
        return "Managed project Runs must be restored to the active runs/ view"
    return None


def _restore_run_under_guard(run_dir: Path) -> ActionResult:
    """Restore or forward-resume one receipt-backed Run transaction."""
    from runops.core.manifest import read_manifest, update_manifest
    from runops.core.state import update_state

    receipt: _LifecycleReceipt | None = None
    try:
        source = _canonical_lifecycle_endpoint(run_dir)
        receipt = _load_lifecycle_receipt("restore_run", source)
        if receipt is not None:
            namespace_error = _pending_lifecycle_namespace_error(receipt)
            if namespace_error:
                return _precondition_fail("restore_run", namespace_error)
        if receipt is None:
            completed_source = _completed_restore_source(source)
            if completed_source is not None:
                return _restore_success(
                    run_id=_completed_run_id(source),
                    source=completed_source,
                    destination=source,
                    cleanup_pending="",
                )
            completed_destination = _find_completed_restore_destination(source)
            if completed_destination is not None:
                return _restore_success(
                    run_id=_completed_run_id(completed_destination),
                    source=source,
                    destination=completed_destination,
                    cleanup_pending="",
                )
            _validate_lifecycle_run_directory(source)
            _state_before, err = _require_state(source, RunState.ARCHIVED)
            if err:
                return _precondition_fail("restore_run", err)
            manifest = read_manifest(source)
            run_id = str(manifest.run.get("id", source.name))
            restore_path = manifest.path.get("archived_from") or manifest.path.get(
                "created_at_path"
            )
            destination = (
                _canonical_lifecycle_endpoint(Path(str(restore_path)))
                if restore_path
                else None
            )
            if destination == source:
                destination = None
            if destination is not None:
                collision_error = _validate_archive_destination(source, destination)
                if collision_error:
                    return _precondition_fail("restore_run", collision_error)
                namespace_error = _validate_project_restore_destination(
                    source,
                    destination,
                )
                if namespace_error:
                    return _precondition_fail("restore_run", namespace_error)
            manifest_snapshot = _snapshot_lifecycle_file(
                source / "manifest.toml",
                required=True,
            )
            assert manifest_snapshot is not None
            state_snapshot = _snapshot_lifecycle_file(
                source / "status" / "state.json",
                required=False,
            )
            transition_at = datetime.now(tz=timezone.utc).isoformat()
            receipt = _write_lifecycle_receipt(
                action="restore_run",
                run_id=run_id,
                source=source,
                destination=destination,
                transition_at=transition_at,
                manifest_snapshot=manifest_snapshot,
                state_snapshot=state_snapshot,
            )
        assert receipt is not None
        current = _lifecycle_current_directory(receipt)
        live_image = _validate_lifecycle_live_image(receipt, current)
        destination = receipt.destination
        if (
            live_image.manifest_phase != "committed"
            and destination is not None
            and current == source
        ):
            destination.parent.mkdir(parents=True, exist_ok=True)
            move_directory_noreplace(source, destination)
            current = destination
            live_image = _validate_lifecycle_live_image(receipt, current)

        if live_image.manifest_phase == "preimage":
            update_state(
                current,
                RunState.COMPLETED,
                timestamp=datetime.fromisoformat(receipt.transition_at),
            )
            live_image = _validate_lifecycle_live_image(receipt, current)
        if not live_image.state_is_postimage:
            _write_lifecycle_state_mirror(
                current,
                state=RunState.COMPLETED,
                previous=RunState.ARCHIVED,
                transition_at=receipt.transition_at,
            )
            live_image = _validate_lifecycle_live_image(receipt, current)
        if live_image.manifest_phase not in {"transitioned", "committed"}:
            raise SimctlError(
                "pending restore did not reach its deterministic transition image"
            )
        if live_image.manifest_phase == "transitioned":
            update_manifest(
                current,
                {
                    "path": {
                        "run_dir": str(current),
                        "restored_from": str(source),
                        "restored_at": receipt.transition_at,
                    },
                    "storage": {"tier": "hot"},
                },
            )
            live_image = _validate_lifecycle_live_image(receipt, current)
        if (
            live_image.manifest_phase != "committed"
            or not live_image.state_is_postimage
        ):
            raise SimctlError(
                "restore transaction did not reach its exact committed postimage"
            )
        if not _completed_restore_matches(current, source=source):
            raise SimctlError("restore transaction did not commit complete metadata")
    except (OSError, SimctlError) as exc:
        if receipt is None:
            return _error("restore_run", str(exc))
        recovery_errors = _rollback_lifecycle_transaction(receipt)
        message = f"Failed to commit restore transaction; rollback attempted: {exc}"
        if recovery_errors:
            message += "; " + "; ".join(recovery_errors)
        return _error("restore_run", message)

    cleanup_pending = ""
    try:
        _remove_lifecycle_receipt_for_live_image(
            receipt,
            current,
            manifest_phase="committed",
            state_is_postimage=True,
        )
    except (OSError, SimctlError):
        cleanup_pending = str(receipt.path)

    if destination is not None:
        emit_event(
            "artifact_move",
            action="restore_run",
            summary=f"Restore archived run {receipt.run_id}",
            path=current,
            data={
                "run_id": receipt.run_id,
                "source_path": str(source),
                "restore_path": str(current),
            },
            requires_verbose=True,
        )
    return _restore_success(
        run_id=receipt.run_id,
        source=source,
        destination=destination,
        cleanup_pending=cleanup_pending,
    )


def _completed_restore_matches(run_dir: Path, *, source: Path) -> bool:
    from runops.core.manifest import read_manifest

    if not os.path.lexists(run_dir):
        return False
    try:
        _validate_lifecycle_run_directory(run_dir)
        manifest = read_manifest(run_dir)
    except (OSError, SimctlError):
        return False
    restored_at = manifest.path.get("restored_at")
    if not isinstance(restored_at, str) or not restored_at:
        return False
    try:
        timestamp = datetime.fromisoformat(restored_at)
    except ValueError:
        return False
    if timestamp.tzinfo is None:
        return False
    return bool(
        manifest.run.get("id")
        and manifest.run.get("status") == RunState.COMPLETED.value
        and manifest.path.get("run_dir") == str(run_dir)
        and manifest.path.get("restored_from") == str(source)
        and manifest.storage.get("tier") == "hot"
        and _completed_lifecycle_state_matches(
            run_dir,
            state=RunState.COMPLETED,
            previous=RunState.ARCHIVED,
            transition_at=restored_at,
        )
    )


def _completed_restore_source(run_dir: Path) -> Path | None:
    from runops.core.manifest import read_manifest

    if not os.path.lexists(run_dir):
        return None
    try:
        _validate_lifecycle_run_directory(run_dir)
        manifest = read_manifest(run_dir)
    except (OSError, SimctlError):
        return None
    raw_source = manifest.path.get("restored_from")
    try:
        source = _parse_lifecycle_receipt_path(raw_source, field="restored_from")
    except SimctlError:
        return None
    if source is None or not _completed_restore_matches(run_dir, source=source):
        return None
    return source


def _find_completed_restore_destination(source: Path) -> Path | None:
    """Find one active Run that proves a receipt-cleaned restore completed."""
    if os.path.lexists(source):
        return None
    candidates: set[Path] = set()
    parts = list(source.parts)
    if _ARCHIVE_DIR_NAME in parts:
        index = parts.index(_ARCHIVE_DIR_NAME)
        inferred = Path(*parts[:index], *parts[index + 1 :])
        candidates.add(inferred)

    runs_root = next(
        (parent for parent in source.parents if parent.name == "runs"), None
    )
    if runs_root is not None and runs_root.is_dir():
        from runops.application.run_discovery import collect_run_manifests_strict

        for run_dir, _manifest in collect_run_manifests_strict(runs_root):
            candidates.add(run_dir)

    matches = sorted(
        candidate
        for candidate in candidates
        if _completed_restore_matches(candidate, source=source)
    )
    if len(matches) > 1:
        raise SimctlError(
            f"multiple completed Runs claim the same restored_from path: {source}"
        )
    return matches[0] if matches else None


def inspect_restore_recovery(run_dir: Path) -> tuple[Path, str] | None:
    """Return the original source and Run ID for an exact restore retry."""
    source = _canonical_lifecycle_endpoint(run_dir)
    pending = _load_lifecycle_receipt("restore_run", source)
    if pending is not None:
        namespace_error = _pending_lifecycle_namespace_error(pending)
        if namespace_error:
            raise SimctlError(namespace_error)
        current = _lifecycle_current_directory(pending)
        _validate_lifecycle_live_image(pending, current)
        return source, pending.run_id
    completed_source = _completed_restore_source(source)
    if completed_source is not None:
        return completed_source, _completed_run_id(source)
    completed_destination = _find_completed_restore_destination(source)
    if completed_destination is not None:
        return source, _completed_run_id(completed_destination)
    return None


def inspect_restore_recoveries(
    scope: Path,
    *,
    run_id: str | None = None,
) -> tuple[RunLifecycleRecovery, ...]:
    """Find pending restore transactions selected by Run ID or source scope."""
    recoveries = _select_project_lifecycle_recoveries(
        "restore_run",
        scope,
        run_id=run_id,
    )
    for recovery in recoveries:
        inspected = inspect_restore_recovery(recovery.source)
        if inspected != (recovery.source, recovery.run_id):
            raise SimctlError(
                "pending restore receipt changed during recovery inspection"
            )
    return recoveries


def _restore_success(
    *,
    run_id: str,
    source: Path,
    destination: Path | None,
    cleanup_pending: str,
) -> ActionResult:
    final_dir = destination or source
    moved = destination is not None and destination != source
    return ActionResult(
        action="restore_run",
        status=ActionStatus.SUCCESS,
        message=(
            "Run restored; lifecycle receipt cleanup remains pending"
            if cleanup_pending
            else "Run restored"
        ),
        data={
            "run_id": run_id,
            "moved": moved,
            "source_path": str(source),
            "restore_path": str(final_dir),
            "cleanup_pending": cleanup_pending,
        },
        state_before=RunState.ARCHIVED.value,
        state_after=RunState.COMPLETED.value,
    )


@logged_action("restore_run")
def restore_run(run_dir: Path) -> ActionResult:
    """Restore a Run while serializing against every run-local mutation."""
    from runops.application.execution.submission import (
        SubmissionLockError,
        submission_guard,
    )
    from runops.application.run_namespace import run_namespace_guard

    try:
        source = _canonical_lifecycle_endpoint(run_dir)
        pending = _load_lifecycle_receipt("restore_run", source)
        transaction_source = source
        if pending is not None:
            namespace_error = _pending_lifecycle_namespace_error(pending)
            if namespace_error:
                return _precondition_fail("restore_run", namespace_error)
            lock_target = _lifecycle_current_directory(pending)
            _validate_lifecycle_live_image(pending, lock_target)
        elif os.path.lexists(source):
            _validate_lifecycle_run_directory(source)
            completed_source = _completed_restore_source(source)
            if completed_source is not None:
                transaction_source = completed_source
            lock_target = source
        else:
            completed_destination = _find_completed_restore_destination(source)
            if completed_destination is None:
                return _precondition_fail(
                    "restore_run",
                    "Run restore source does not exist and no recovery is provable: "
                    f"{source}",
                )
            lock_target = completed_destination
        project_root = _find_project_root_or_none(transaction_source)
        namespace_guard = (
            run_namespace_guard(project_root)
            if project_root is not None
            else nullcontext()
        )
        with submission_guard(lock_target), namespace_guard:
            return _restore_run_under_guard(source)
    except (SubmissionLockError, SimctlError) as exc:
        return _precondition_fail(
            "restore_run", f"cannot safely continue Run restore: {exc}"
        )


@logged_action("purge_work")
def purge_work(
    run_dir: Path,
    *,
    discard_incomplete: bool = False,
    review_reason: str = "",
) -> ActionResult:
    """Delete purgeable outputs under shared Result and Run mutation locks."""
    from contextlib import nullcontext

    from runops.application.execution.submission import (
        SubmissionLockError,
        submission_guard,
    )
    from runops.application.research.results import result_mutation_guard
    from runops.application.research.workspace import ResearchWorkspaceError

    source = run_dir.resolve()
    project_root = _find_project_root_or_none(source)
    result_guard = (
        result_mutation_guard(project_root)
        if project_root is not None
        else nullcontext()
    )
    try:
        with result_guard, submission_guard(source):
            return _purge_work_under_guard(
                source,
                discard_incomplete=discard_incomplete,
                review_reason=review_reason,
            )
    except SubmissionLockError as exc:
        return _precondition_fail(
            "purge_work", f"failed to lock Run purge target: {exc}"
        )
    except ResearchWorkspaceError as exc:
        return _precondition_fail(
            "purge_work", f"failed to lock Result evidence registry: {exc}"
        )


def inspect_purge_recovery(run_dir: Path) -> str | None:
    """Return the Run ID only when a pending purge can be safely resumed.

    This is a read-only admission check for the CLI's otherwise strict
    ``archived`` state gate.  The application action repeats all validation
    under the Run and Result locks before it mutates recovery state.
    """
    from runops.core.manifest import read_manifest

    source = run_dir.resolve()
    unsafe_parent = _purge_parent_error(source)
    if unsafe_parent:
        raise SimctlError(unsafe_parent)
    payload = _read_purge_receipt(source)
    if payload is None:
        return None
    manifest = read_manifest(source)
    run_id = str(manifest.run.get("id", source.name))
    if payload.run_id != run_id:
        raise SimctlError("pending purge receipt run_id does not match manifest")
    status = str(manifest.run.get("status", ""))
    _validate_pending_purge_topology(source, payload, status=status)
    _validate_pending_purge_digests(
        source,
        payload,
        manifest=manifest,
        status=status,
    )
    return run_id


def _purge_work_under_guard(
    run_dir: Path,
    *,
    discard_incomplete: bool,
    review_reason: str,
) -> ActionResult:
    """Apply purge preflight and deletion under ``submission_guard``."""
    from runops.application.execution.readiness import read_cached_run_readiness
    from runops.application.research.results import protected_results_for_run_paths
    from runops.application.research.workspace import ResearchWorkspaceError
    from runops.core.manifest import read_manifest, update_manifest, write_manifest

    unsafe_parent = _purge_parent_error(run_dir)
    if unsafe_parent:
        return _precondition_fail("purge_work", unsafe_parent)

    try:
        resumed = _resume_pending_purge(run_dir)
    except (OSError, SimctlError, ValueError) as exc:
        return _error(
            "purge_work",
            f"Failed to recover pending purge transaction: {exc}",
        )
    if resumed is not None:
        return resumed

    try:
        current_manifest = read_manifest(run_dir)
    except SimctlError as exc:
        return _precondition_fail("purge_work", str(exc))
    current_status = str(current_manifest.run.get("status", ""))
    if current_status == RunState.PURGED.value:
        if (
            current_manifest.storage.get("tier") != "cold"
            or current_manifest.storage.get("form") != "compacted"
        ):
            return _error(
                "purge_work",
                "Run is purged but compacted storage metadata is incomplete and no "
                "recovery receipt exists",
            )
        remaining = [
            name
            for name in ("outputs", "restart", "tmp")
            if os.path.lexists(run_dir / "work" / name)
        ]
        if remaining:
            return _error(
                "purge_work",
                "Run is purged but purgeable work remains and no recovery receipt "
                f"exists: {', '.join(remaining)}",
            )
        changed_at = str(current_manifest.storage.get("compacted_at", ""))
        if changed_at:
            try:
                _write_purge_state_mirror(run_dir, changed_at=changed_at)
            except OSError as exc:
                return _error(
                    "purge_work",
                    f"Failed to repair purged state mirror: {exc}",
                )
        return ActionResult(
            action="purge_work",
            status=ActionStatus.SUCCESS,
            message="Run work is already purged",
            data={
                "removed_dirs": [],
                "bytes_removed": 0,
                "bytes_staged": 0,
                "cleanup_pending": "",
                "discarded_incomplete": bool(
                    current_manifest.run.get("readiness_disposition")
                    == "discarded_incomplete"
                ),
            },
            state_before=RunState.PURGED.value,
            state_after=RunState.PURGED.value,
        )

    state_str, err = _require_state(run_dir, RunState.ARCHIVED)
    if err:
        return _precondition_fail("purge_work", err)

    manifest = read_manifest(run_dir)
    protected_by_results: tuple[str, ...] = ()
    project_root = _find_project_root_or_none(run_dir)
    if project_root is not None:
        run_id = str(manifest.run.get("id", ""))
        try:
            protected_by_results = protected_results_for_run_paths(
                project_root,
                run_id,
                relative_roots=("work/outputs", "work/restart", "work/tmp"),
            )
        except ResearchWorkspaceError as exc:
            return _precondition_fail(
                "purge_work", f"cannot verify sealed Result protections: {exc}"
            )
        recorded = manifest.storage.get("protected_by_results", [])
        if list(protected_by_results) != recorded:
            update_manifest(
                run_dir,
                {
                    "storage": {
                        "protected_by_results": list(protected_by_results),
                    }
                },
            )
        if protected_by_results:
            return ActionResult(
                action="purge_work",
                status=ActionStatus.PRECONDITION_FAILED,
                message=(
                    "Purge blocked: sealed Results include Run-owned path evidence"
                ),
                data={
                    "protected_by_results": list(protected_by_results),
                    "requires_human": True,
                },
                state_before=state_str,
            )

    # The reverse-reference scan may refresh storage.protected_by_results.
    # Freeze the exact post-scan manifest that this transaction will commit.
    manifest = read_manifest(run_dir)
    readiness = read_cached_run_readiness(run_dir, manifest=manifest)
    requires_discard_review = readiness is None or not readiness.analysis_ready
    review_updates: dict[str, str] = {}
    if requires_discard_review:
        gate_data = {
            "readiness": readiness.to_dict() if readiness is not None else None,
            "recommended_action": (
                readiness.recommended_action
                if readiness is not None
                else "analyze_outputs"
            ),
            "requires_human": True,
        }
        if not discard_incomplete:
            return ActionResult(
                action="purge_work",
                status=ActionStatus.PRECONDITION_FAILED,
                message=(
                    "Cached readiness is incomplete or unknown; inspect outputs or "
                    "rerun with "
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
        review_updates = {
            "readiness_disposition": "discarded_incomplete",
            "readiness_review_reason": review_reason.strip(),
            "readiness_reviewed_at": datetime.now(tz=timezone.utc).isoformat(),
        }

    work_dir = run_dir / "work"
    targets = ["outputs", "restart", "tmp"]
    total_removed = 0
    candidates: list[tuple[str, Path]] = []
    for dirname in targets:
        target_dir = work_dir / dirname
        if not os.path.lexists(target_dir):
            continue
        if target_dir.is_symlink() or not target_dir.is_dir():
            return _precondition_fail(
                "purge_work",
                f"Purge target must be a real directory: {target_dir}",
            )
        try:
            total_removed += _dir_size(target_dir)
        except OSError as exc:
            return _error("purge_work", f"Failed to inspect {target_dir}: {exc}")
        candidates.append((dirname, target_dir))

    try:
        target_sha256 = {
            dirname: _purge_directory_digest(target_dir)
            for dirname, target_dir in candidates
        }
    except SimctlError as exc:
        return _precondition_fail("purge_work", str(exc))

    compacted_at = datetime.now(tz=timezone.utc).isoformat()
    committed_manifest = copy.deepcopy(manifest)
    committed_manifest.run["status"] = RunState.PURGED.value
    committed_manifest.run.update(review_updates)
    committed_manifest.storage.update(
        {
            "tier": "cold",
            "form": "compacted",
            "compacted_at": compacted_at,
        }
    )
    manifest_before_sha256 = _purge_manifest_data_sha256(manifest)
    manifest_after_sha256 = _purge_manifest_data_sha256(committed_manifest)

    tombstone: Path | None = None
    staged: list[tuple[str, Path]] = []
    receipt_written = False
    try:
        tombstone_identity: tuple[int, int] | None = None
        if candidates:
            work_dir.mkdir(parents=True, exist_ok=True)
            tombstone = _new_purge_tombstone(work_dir)
            tombstone.mkdir(mode=0o700)
            _fsync_directory(work_dir)
            tombstone_identity = _purge_directory_identity(tombstone)
        target_identity = {
            dirname: _purge_directory_identity(target_dir)
            for dirname, target_dir in candidates
        }
        _write_purge_receipt(
            run_dir,
            run_id=str(manifest.run.get("id", run_dir.name)),
            tombstone=tombstone,
            targets=tuple(dirname for dirname, _path in candidates),
            total_removed=total_removed,
            compacted_at=compacted_at,
            review_updates=review_updates,
            manifest_before_sha256=manifest_before_sha256,
            manifest_after_sha256=manifest_after_sha256,
            target_sha256=target_sha256,
            tombstone_identity=tombstone_identity,
            target_identity=target_identity,
        )
        receipt_written = True
        for dirname, target_dir in candidates:
            assert tombstone is not None
            move_directory_noreplace(target_dir, tombstone / dirname)
            staged.append((dirname, target_dir))
        receipt = _read_purge_receipt(run_dir)
        if receipt is None:
            raise SimctlError("pending purge receipt disappeared before commit")
        _validate_pending_purge_topology(
            run_dir,
            receipt,
            status=RunState.ARCHIVED.value,
        )
        _validate_pending_purge_digests(
            run_dir,
            receipt,
            manifest=read_manifest(run_dir),
            status=RunState.ARCHIVED.value,
        )
    except (OSError, SimctlError) as exc:
        if receipt_written:
            rollback_error = _rollback_pending_purge_if_trusted(run_dir)
        else:
            rollback_error = _rollback_purge_staging(tombstone, staged)
        if receipt_written and not rollback_error:
            try:
                _remove_validated_purge_receipt(
                    run_dir,
                    status=RunState.ARCHIVED.value,
                )
            except (OSError, SimctlError) as cleanup_exc:
                rollback_error = f"receipt cleanup failed: {cleanup_exc}"
        message = f"Failed to stage purge targets: {exc}"
        if rollback_error:
            receipt_error = _write_recovery_receipt(
                run_dir,
                action="purge_work",
                error=str(exc),
                recovery_errors=[f"data restore failed: {rollback_error}"],
                source=run_dir,
                destination=tombstone,
            )
            message += f"; rollback failed: {rollback_error}"
            if receipt_error:
                message += f"; recovery receipt failed: {receipt_error}"
        return _error("purge_work", message)

    try:
        write_manifest(run_dir, committed_manifest)
        _write_purge_state_mirror(run_dir, changed_at=compacted_at)
    except (OSError, SimctlError) as exc:
        try:
            committed = (
                read_manifest(run_dir).run.get("status") == RunState.PURGED.value
            )
        except SimctlError:
            committed = False
        if committed:
            return _error(
                "purge_work",
                "Purge commit point was reached but metadata completion is pending; "
                f"rerun the same command: {exc}",
            )
        recovery_errors: list[str] = []
        rollback_error = _rollback_pending_purge_if_trusted(run_dir)
        if rollback_error:
            recovery_errors.append(f"rollback refused or failed: {rollback_error}")
        if not recovery_errors:
            try:
                _remove_validated_purge_receipt(
                    run_dir,
                    status=RunState.ARCHIVED.value,
                )
            except (OSError, SimctlError) as recovery_exc:
                recovery_errors.append(f"receipt cleanup failed: {recovery_exc}")
        message = f"Failed to commit purge metadata: {exc}"
        if recovery_errors:
            receipt_error = _write_recovery_receipt(
                run_dir,
                action="purge_work",
                error=str(exc),
                recovery_errors=recovery_errors,
                source=run_dir,
                destination=tombstone,
            )
            if receipt_error:
                recovery_errors.append(f"recovery receipt failed: {receipt_error}")
            message += "; automatic rollback was not completed; " + "; ".join(
                recovery_errors
            )
        else:
            message += "; staged data was restored"
        return _error("purge_work", message)

    cleanup_pending = ""
    try:
        trusted_receipt = _require_valid_pending_purge(
            run_dir,
            status=RunState.PURGED.value,
        )
        if tombstone is not None:
            _validate_purge_tombstone(
                tombstone,
                expected_targets=trusted_receipt.targets,
                expected_identity=trusted_receipt.tombstone_identity,
            )
            shutil.rmtree(tombstone)
            _fsync_directory(work_dir)
        _remove_validated_purge_receipt(
            run_dir,
            status=RunState.PURGED.value,
        )
    except (OSError, SimctlError):
        cleanup_pending = str(
            tombstone
            if tombstone is not None and os.path.lexists(tombstone)
            else _purge_receipt_path(run_dir)
        )

    return ActionResult(
        action="purge_work",
        status=ActionStatus.SUCCESS,
        message=(
            "Purge committed; tombstone cleanup remains pending"
            if cleanup_pending
            else "Purged work files"
        ),
        data={
            "removed_dirs": [dirname for dirname, _target in staged],
            "bytes_removed": 0 if cleanup_pending else total_removed,
            "bytes_staged": total_removed,
            "cleanup_pending": cleanup_pending,
            "discarded_incomplete": bool(requires_discard_review),
        },
        state_before=state_str,
        state_after=RunState.PURGED.value,
    )


def _new_purge_tombstone(work_dir: Path) -> Path:
    for _attempt in range(100):
        candidate = work_dir / f".delete-purge-{secrets.token_hex(8)}"
        if not os.path.lexists(candidate):
            return candidate
    raise OSError("could not allocate a unique purge tombstone")


def _purge_parent_error(run_dir: Path) -> str | None:
    """Reject parent indirection before reading or mutating purge state."""
    for name in ("status", "work"):
        entry = run_dir / name
        if not os.path.lexists(entry):
            continue
        try:
            metadata = entry.lstat()
        except OSError as exc:
            return f"Cannot safely inspect purge parent {entry}: {exc}"
        if not stat.S_ISDIR(metadata.st_mode):
            return f"Purge parent must be a real directory: {entry}"
    return None


def _purge_receipt_path(run_dir: Path) -> Path:
    return run_dir / "status" / ".purge-pending.json"


def _purge_manifest_data_sha256(manifest: ManifestData) -> str:
    """Hash canonical manifest content independent of TOML formatting."""
    encoded = tomli_w.dumps(manifest.to_dict()).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _purge_directory_digest(path: Path) -> str:
    """Hash one purge target as a closed, non-symlink directory tree."""
    from runops.application.run_creation.workflow import directory_content_hash

    try:
        return directory_content_hash(path)
    except (OSError, SimctlError) as exc:
        raise SimctlError(f"cannot hash purge target {path}: {exc}") from exc


def _purge_directory_identity(path: Path) -> tuple[int, int]:
    """Return the stable root identity for one real purge directory."""
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise SimctlError(f"cannot inspect purge directory {path}: {exc}") from exc
    if not stat.S_ISDIR(metadata.st_mode):
        raise SimctlError(f"purge directory must be a real directory: {path}")
    return metadata.st_dev, metadata.st_ino


def _write_purge_receipt(
    run_dir: Path,
    *,
    run_id: str,
    tombstone: Path | None,
    targets: tuple[str, ...],
    total_removed: int,
    compacted_at: str,
    review_updates: dict[str, str],
    manifest_before_sha256: str,
    manifest_after_sha256: str,
    target_sha256: dict[str, str],
    tombstone_identity: tuple[int, int] | None,
    target_identity: dict[str, tuple[int, int]],
) -> None:
    """Persist the purge topology before the first destructive rename."""
    path = _purge_receipt_path(run_dir)
    if os.path.lexists(path):
        raise SimctlError(f"pending purge receipt already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": _PURGE_RECEIPT_VERSION,
        "run_id": run_id,
        "tombstone": tombstone.name if tombstone is not None else "",
        "targets": list(targets),
        "bytes_staged": total_removed,
        "compacted_at": compacted_at,
        "review_updates": dict(review_updates),
        "manifest_before_sha256": manifest_before_sha256,
        "manifest_after_sha256": manifest_after_sha256,
        "target_sha256": dict(target_sha256),
        "tombstone_identity": (
            list(tombstone_identity) if tombstone_identity is not None else None
        ),
        "target_identity": {
            name: list(identity) for name, identity in target_identity.items()
        },
    }
    _restore_file_snapshot(
        path,
        (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode(
            "utf-8"
        ),
    )


def _read_purge_receipt(run_dir: Path) -> _PurgeReceipt | None:
    path = _purge_receipt_path(run_dir)
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise SimctlError(
            f"pending purge receipt must be a single-link regular file: {path}"
        )
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
    descriptor = -1
    try:
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino)
        ):
            raise SimctlError(f"pending purge receipt changed while opening: {path}")
        chunks: list[bytes] = []
        total = 0
        while chunk := os.read(descriptor, 64 * 1024):
            total += len(chunk)
            if total > 1024 * 1024:
                raise SimctlError(f"pending purge receipt is too large: {path}")
            chunks.append(chunk)
        after = os.fstat(descriptor)
        current = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise SimctlError(
            f"cannot safely read pending purge receipt {path}: {exc}"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if (
        (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        != (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
        or after.st_nlink != 1
        or (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino)
        or current.st_nlink != 1
        or not stat.S_ISREG(current.st_mode)
    ):
        raise SimctlError(f"pending purge receipt changed while being read: {path}")
    try:
        payload = json.loads(b"".join(chunks).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SimctlError(f"invalid pending purge receipt {path}: {exc}") from exc
    required_fields = {
        "schema_version",
        "run_id",
        "tombstone",
        "targets",
        "bytes_staged",
        "compacted_at",
        "review_updates",
        "manifest_before_sha256",
        "manifest_after_sha256",
        "target_sha256",
        "tombstone_identity",
        "target_identity",
    }
    if (
        not isinstance(payload, dict)
        or set(payload) != required_fields
        or type(payload.get("schema_version")) is not int
        or payload.get("schema_version") != _PURGE_RECEIPT_VERSION
    ):
        raise SimctlError(f"invalid pending purge receipt schema: {path}")
    run_id = payload.get("run_id")
    tombstone = payload.get("tombstone")
    targets = payload.get("targets")
    bytes_staged = payload.get("bytes_staged")
    compacted_at = payload.get("compacted_at")
    review_updates = payload.get("review_updates")
    manifest_before_sha256 = payload.get("manifest_before_sha256")
    manifest_after_sha256 = payload.get("manifest_after_sha256")
    target_sha256 = payload.get("target_sha256")
    tombstone_identity_raw = payload.get("tombstone_identity")
    target_identity_raw = payload.get("target_identity")
    allowed_targets = {"outputs", "restart", "tmp"}
    allowed_review = {
        "readiness_disposition",
        "readiness_review_reason",
        "readiness_reviewed_at",
    }
    if (
        not isinstance(run_id, str)
        or not run_id
        or not isinstance(tombstone, str)
        or (
            tombstone
            and (
                not tombstone.startswith(".delete-purge-")
                or Path(tombstone).name != tombstone
            )
        )
        or not isinstance(targets, list)
        or any(not isinstance(item, str) for item in targets)
        or isinstance(bytes_staged, bool)
        or not isinstance(bytes_staged, int)
        or bytes_staged < 0
        or not isinstance(compacted_at, str)
        or not compacted_at
        or not isinstance(review_updates, dict)
        or any(
            key not in allowed_review or not isinstance(value, str)
            for key, value in review_updates.items()
        )
        or not _is_plain_sha256(manifest_before_sha256)
        or not _is_plain_sha256(manifest_after_sha256)
        or not isinstance(target_sha256, dict)
        or any(
            not isinstance(key, str) or not _is_prefixed_sha256(value)
            for key, value in target_sha256.items()
        )
        or not _is_purge_identity_or_none(tombstone_identity_raw)
        or not isinstance(target_identity_raw, dict)
        or any(
            not isinstance(key, str) or not _is_purge_identity(value)
            for key, value in target_identity_raw.items()
        )
    ):
        raise SimctlError(f"invalid pending purge receipt fields: {path}")
    target_names = tuple(targets)
    review_keys = set(review_updates)
    if (
        any(item not in allowed_targets for item in target_names)
        or len(set(target_names)) != len(target_names)
        or bool(target_names) != bool(tombstone)
        or (review_keys and review_keys != allowed_review)
        or set(target_sha256) != set(target_names)
        or (tombstone_identity_raw is not None) != bool(tombstone)
        or set(target_identity_raw) != set(target_names)
    ):
        raise SimctlError(f"invalid pending purge receipt topology: {path}")
    return _PurgeReceipt(
        run_id=run_id,
        tombstone=tombstone,
        targets=target_names,
        bytes_staged=bytes_staged,
        compacted_at=compacted_at,
        review_updates={str(key): str(value) for key, value in review_updates.items()},
        manifest_before_sha256=cast("str", manifest_before_sha256),
        manifest_after_sha256=cast("str", manifest_after_sha256),
        target_sha256={str(key): str(value) for key, value in target_sha256.items()},
        tombstone_identity=(
            cast("tuple[int, int]", tuple(tombstone_identity_raw))
            if tombstone_identity_raw is not None
            else None
        ),
        target_identity={
            str(key): cast("tuple[int, int]", tuple(value))
            for key, value in target_identity_raw.items()
        },
    )


def _is_plain_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _is_prefixed_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and value.startswith("sha256:")
        and _is_plain_sha256(value.removeprefix("sha256:"))
    )


def _is_purge_identity(value: object) -> bool:
    return bool(
        isinstance(value, list)
        and len(value) == 2
        and all(type(component) is int and component >= 0 for component in value)
    )


def _is_purge_identity_or_none(value: object) -> bool:
    return value is None or _is_purge_identity(value)


def _remove_purge_receipt(run_dir: Path) -> None:
    path = _purge_receipt_path(run_dir)
    payload = _read_purge_receipt(run_dir)
    if payload is None:
        return
    path.unlink()
    _fsync_directory(path.parent)


def _write_purge_state_mirror(run_dir: Path, *, changed_at: str) -> None:
    payload = {
        "state": RunState.PURGED.value,
        "previous_state": RunState.ARCHIVED.value,
        "changed_at": changed_at,
    }
    _restore_file_snapshot(
        run_dir / "status" / "state.json",
        (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )


def _resume_pending_purge(run_dir: Path) -> ActionResult | None:
    """Rollback an uncommitted purge or finish one past its manifest commit."""
    from runops.core.manifest import read_manifest, write_manifest

    payload = _read_purge_receipt(run_dir)
    if payload is None:
        return None
    manifest = read_manifest(run_dir)
    run_id = str(manifest.run.get("id", run_dir.name))
    if payload.run_id != run_id:
        raise SimctlError("pending purge receipt run_id does not match manifest")
    target_names = payload.targets
    work_dir = run_dir / "work"
    tombstone_name = payload.tombstone
    tombstone = work_dir / tombstone_name if tombstone_name else None
    status = str(manifest.run.get("status", ""))
    _validate_pending_purge_topology(run_dir, payload, status=status)
    _validate_pending_purge_digests(
        run_dir,
        payload,
        manifest=manifest,
        status=status,
    )

    if status == RunState.ARCHIVED.value:
        rollback_error = _rollback_pending_purge_if_trusted(run_dir)
        if rollback_error:
            raise SimctlError(
                f"pending purge rollback refused or failed: {rollback_error}"
            )
        _remove_validated_purge_receipt(
            run_dir,
            status=RunState.ARCHIVED.value,
        )
        return None

    if status != RunState.PURGED.value:
        raise SimctlError(f"pending purge has unexpected manifest status {status!r}")

    for dirname in target_names:
        if os.path.lexists(work_dir / dirname):
            raise SimctlError(f"committed purge unexpectedly restored work/{dirname}")
    if tombstone is not None and os.path.lexists(tombstone):
        _validate_purge_tombstone(
            tombstone,
            expected_targets=target_names,
            expected_identity=payload.tombstone_identity,
        )
        shutil.rmtree(tombstone)
        _fsync_directory(work_dir)

    review_updates = payload.review_updates
    manifest.run.update(review_updates)
    manifest.storage.update(
        {
            "tier": "cold",
            "form": "compacted",
            "compacted_at": payload.compacted_at,
        }
    )
    write_manifest(run_dir, manifest)
    _write_purge_state_mirror(run_dir, changed_at=payload.compacted_at)
    _remove_validated_purge_receipt(
        run_dir,
        status=RunState.PURGED.value,
    )
    return ActionResult(
        action="purge_work",
        status=ActionStatus.SUCCESS,
        message="Completed pending purge transaction",
        data={
            "removed_dirs": list(target_names),
            "bytes_removed": payload.bytes_staged,
            "bytes_staged": payload.bytes_staged,
            "cleanup_pending": "",
            "discarded_incomplete": bool(review_updates),
        },
        state_before=RunState.ARCHIVED.value,
        state_after=RunState.PURGED.value,
    )


def _validate_purge_tombstone(
    tombstone: Path,
    *,
    expected_targets: tuple[str, ...],
    expected_identity: tuple[int, int] | None = None,
) -> None:
    """Reject redirected or contaminated purge staging before recovery."""
    if not os.path.lexists(tombstone):
        return
    try:
        metadata = tombstone.lstat()
    except OSError as exc:
        raise SimctlError(f"cannot inspect purge tombstone {tombstone}: {exc}") from exc
    if not stat.S_ISDIR(metadata.st_mode):
        raise SimctlError(f"purge tombstone must be a real directory: {tombstone}")
    if (
        expected_identity is not None
        and (
            metadata.st_dev,
            metadata.st_ino,
        )
        != expected_identity
    ):
        raise SimctlError(
            f"purge tombstone identity does not match its durable receipt: {tombstone}"
        )
    allowed = set(expected_targets)
    try:
        children = tuple(tombstone.iterdir())
    except OSError as exc:
        raise SimctlError(f"cannot inspect purge tombstone {tombstone}: {exc}") from exc
    for child in children:
        try:
            child_metadata = child.lstat()
        except OSError as exc:
            raise SimctlError(f"cannot inspect purge target {child}: {exc}") from exc
        if child.name not in allowed or not stat.S_ISDIR(child_metadata.st_mode):
            raise SimctlError(f"purge tombstone contains an unexpected entry: {child}")


def _validate_pending_purge_topology(
    run_dir: Path,
    payload: _PurgeReceipt,
    *,
    status: str,
) -> None:
    """Validate every receipt endpoint without mutating the transaction."""
    if status not in {RunState.ARCHIVED.value, RunState.PURGED.value}:
        raise SimctlError(f"pending purge has unexpected manifest status {status!r}")
    work_dir = run_dir / "work"
    tombstone = work_dir / payload.tombstone if payload.tombstone else None
    if tombstone is not None and os.path.lexists(tombstone):
        _validate_purge_tombstone(
            tombstone,
            expected_targets=payload.targets,
            expected_identity=payload.tombstone_identity,
        )

    for dirname in payload.targets:
        original = work_dir / dirname
        staged = tombstone / dirname if tombstone is not None else None
        original_exists = os.path.lexists(original)
        staged_exists = bool(staged is not None and os.path.lexists(staged))
        if status == RunState.ARCHIVED.value:
            if original_exists == staged_exists:
                topology = "both original and staged" if original_exists else "neither"
                raise SimctlError(f"pending purge has {topology} work/{dirname}")
        elif original_exists:
            raise SimctlError(f"committed purge unexpectedly restored work/{dirname}")
        candidate = original if original_exists else staged if staged_exists else None
        if candidate is not None:
            actual_identity = _purge_directory_identity(candidate)
            if actual_identity != payload.target_identity[dirname]:
                raise SimctlError(
                    "pending purge target identity does not match its durable receipt: "
                    f"{candidate}"
                )


def _validate_pending_purge_digests(
    run_dir: Path,
    payload: _PurgeReceipt,
    *,
    manifest: ManifestData,
    status: str,
) -> None:
    """Bind retry decisions to the live manifest and retained staged bytes."""
    expected_manifest = (
        payload.manifest_before_sha256
        if status == RunState.ARCHIVED.value
        else payload.manifest_after_sha256
    )
    if _purge_manifest_data_sha256(manifest) != expected_manifest:
        raise SimctlError(
            "pending purge live manifest digest does not match its durable receipt"
        )

    # Before the commit point, rollback is allowed only for exact target-tree
    # preimages.  After it, rmtree may have removed an arbitrary prefix of the
    # transaction-owned trees before failing.  Their root device/inode, checked
    # by _validate_pending_purge_topology, is the durable cleanup authority.
    if status == RunState.PURGED.value:
        return

    work_dir = run_dir / "work"
    tombstone = work_dir / payload.tombstone if payload.tombstone else None
    for dirname, expected_digest in payload.target_sha256.items():
        original = work_dir / dirname
        staged = tombstone / dirname if tombstone is not None else None
        if os.path.lexists(original):
            candidate = original
        elif staged is not None and os.path.lexists(staged):
            candidate = staged
        else:
            raise SimctlError(f"pending purge lost work/{dirname} before commit")
        actual_digest = _purge_directory_digest(candidate)
        if actual_digest != expected_digest:
            raise SimctlError(
                "pending purge target digest does not match its durable receipt: "
                f"{candidate}"
            )


def _require_valid_pending_purge(
    run_dir: Path,
    *,
    status: str,
) -> _PurgeReceipt:
    """Load and bind a pending purge to its exact live manifest and target trees."""
    from runops.core.manifest import read_manifest

    payload = _read_purge_receipt(run_dir)
    if payload is None:
        raise SimctlError("pending purge receipt disappeared during recovery")
    manifest = read_manifest(run_dir)
    if str(manifest.run.get("id", run_dir.name)) != payload.run_id:
        raise SimctlError("pending purge receipt run_id does not match manifest")
    current_status = str(manifest.run.get("status", ""))
    if current_status != status:
        raise SimctlError(
            "pending purge manifest changed before recovery: "
            f"expected {status!r}, found {current_status!r}"
        )
    _validate_pending_purge_topology(run_dir, payload, status=status)
    _validate_pending_purge_digests(
        run_dir,
        payload,
        manifest=manifest,
        status=status,
    )
    return payload


def _remove_validated_purge_receipt(run_dir: Path, *, status: str) -> None:
    """Remove a purge receipt only while its trusted live image remains exact."""
    expected = _require_valid_pending_purge(run_dir, status=status)
    current = _read_purge_receipt(run_dir)
    if current != expected:
        raise SimctlError("pending purge receipt changed before cleanup")
    _remove_purge_receipt(run_dir)


def _rollback_pending_purge_if_trusted(run_dir: Path) -> str:
    """Restore staged targets only after receipt-bound preimages are revalidated."""
    try:
        payload = _require_valid_pending_purge(
            run_dir,
            status=RunState.ARCHIVED.value,
        )
        work_dir = run_dir / "work"
        tombstone = work_dir / payload.tombstone if payload.tombstone else None
        for dirname in reversed(payload.targets):
            original = work_dir / dirname
            staged = tombstone / dirname if tombstone is not None else None
            if staged is not None and os.path.lexists(staged):
                expected_digest = payload.target_sha256[dirname]
                if _purge_directory_digest(staged) != expected_digest:
                    raise SimctlError(
                        "pending purge target changed immediately before rollback: "
                        f"{staged}"
                    )
                move_directory_noreplace(staged, original)
        if tombstone is not None and os.path.lexists(tombstone):
            _validate_purge_tombstone(
                tombstone,
                expected_targets=payload.targets,
                expected_identity=payload.tombstone_identity,
            )
            tombstone.rmdir()
            _fsync_directory(work_dir)
        _require_valid_pending_purge(
            run_dir,
            status=RunState.ARCHIVED.value,
        )
    except (OSError, SimctlError) as exc:
        return str(exc)
    return ""


def _rollback_purge_staging(
    tombstone: Path | None,
    staged: list[tuple[str, Path]],
) -> str:
    if tombstone is None:
        return ""
    errors: list[str] = []
    for dirname, original in reversed(staged):
        try:
            move_directory_noreplace(tombstone / dirname, original)
        except (OSError, SimctlError) as exc:
            errors.append(f"{dirname}: {exc}")
    try:
        tombstone.rmdir()
        _fsync_directory(tombstone.parent)
    except OSError as exc:
        errors.append(f"tombstone: {exc}")
    return "; ".join(errors)


def _restore_file_snapshot(path: Path, payload: bytes | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if payload is None:
        path.unlink(missing_ok=True)
        _fsync_directory(path.parent)
        return
    descriptor, temporary = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        _fsync_directory(path.parent)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def _write_recovery_receipt(
    run_dir: Path,
    *,
    action: str,
    error: str,
    recovery_errors: list[str],
    source: Path,
    destination: Path | None,
) -> str:
    """Persist a structured marker when automatic lifecycle rollback is incomplete."""
    payload = {
        "schema_version": 1,
        "action": action,
        "recorded_at": datetime.now(tz=timezone.utc).isoformat(),
        "error": error,
        "recovery_errors": list(recovery_errors),
        "source": str(source),
        "destination": str(destination) if destination is not None else "",
        "requires_human": True,
    }
    path = run_dir / "status" / "recovery.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _restore_file_snapshot(
            path,
            (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        )
    except OSError as exc:
        return str(exc)
    return ""


def _rollback_lifecycle_mutation(
    *,
    current_dir: Path,
    original_dir: Path,
    manifest_snapshot: object,
    state_snapshot: bytes | None,
    moved: bool,
    action: str,
    error: str,
    destination: Path | None,
) -> list[str]:
    """Restore Run metadata and topology after an archive transaction fails."""
    from runops.core.manifest import ManifestData, write_manifest

    recovery_errors: list[str] = []
    if not isinstance(manifest_snapshot, ManifestData):
        return ["invalid in-memory manifest recovery snapshot"]
    try:
        write_manifest(current_dir, manifest_snapshot)
    except (OSError, SimctlError) as recovery_exc:
        recovery_errors.append(f"manifest restore failed: {recovery_exc}")
    try:
        _restore_file_snapshot(
            current_dir / "status" / "state.json",
            state_snapshot,
        )
    except OSError as recovery_exc:
        recovery_errors.append(f"state restore failed: {recovery_exc}")
    if moved and not recovery_errors:
        try:
            move_directory_noreplace(current_dir, original_dir)
            current_dir = original_dir
        except (OSError, SimctlError) as recovery_exc:
            recovery_errors.append(f"directory rollback failed: {recovery_exc}")
    if recovery_errors:
        receipt_dir = current_dir if current_dir.exists() else original_dir
        receipt_error = _write_recovery_receipt(
            receipt_dir,
            action=action,
            error=error,
            recovery_errors=recovery_errors,
            source=original_dir,
            destination=destination,
        )
        if receipt_error:
            recovery_errors.append(f"recovery receipt failed: {receipt_error}")
    return recovery_errors


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
    from runops.application.experiments import experiment_lock
    from runops.application.run_budget import persist_manifest_budget_usage
    from runops.application.run_namespace import run_namespace_guard
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
    project_root = _find_project_root_or_none(source)
    experiment_guard = (
        experiment_lock(project_root) if project_root is not None else nullcontext()
    )
    namespace_guard = (
        run_namespace_guard(project_root) if project_root is not None else nullcontext()
    )
    try:
        with experiment_guard, submission_guard(source) as guard, namespace_guard:
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

            manifest = read_manifest(source)
            run_id = manifest.run.get("id", source.name)
            experiment_id = str(manifest.intent.get("experiment_id", "")).strip()
            if project_root is not None and experiment_id:
                # The manifest is the write-ahead record for budget charges.
                # Backfill it durably before deleting the only remaining source.
                persist_manifest_budget_usage(
                    project_root,
                    source,
                    manifest,
                )
            bytes_removed = _dir_size(source)
            delete_path = _unique_delete_staging_path(source)
            os.rename(source, delete_path)
            _fsync_directory(source.parent)
            shutil.rmtree(delete_path)
            _fsync_directory(source.parent)
    except (SubmissionClaimError, SubmissionLockError) as e:
        return _error("delete_run", f"Submission guard failed: {e}")
    except SimctlError as e:
        return _precondition_fail(
            "delete_run",
            f"Cannot durably account Run before deletion: {e}",
        )
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
        candidate = source.with_name(f".delete-{source.name}-{secrets.token_hex(8)}")
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
