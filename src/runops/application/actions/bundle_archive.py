"""Reversible archival of a directory containing multiple runs."""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
import stat
import sys
import tempfile
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager, nullcontext, suppress
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
from runops.application.execution.submission import (
    SubmissionLockError,
    submission_guard,
)
from runops.application.run_creation.staging import move_directory_noreplace
from runops.application.run_discovery import collect_run_manifests_strict
from runops.application.run_namespace import run_namespace_guard
from runops.core.discovery import ARCHIVE_BUNDLE_METADATA_FILE
from runops.core.event_log import emit_event, logged_action
from runops.core.exceptions import ProjectNotFoundError, SimctlError
from runops.core.manifest import ManifestData, read_manifest, write_manifest
from runops.core.project import find_project_root
from runops.core.state import RunState

_ARCHIVE_DIR_NAME = "_archive"
_ACTIVE_STATES = frozenset({RunState.SUBMITTED, RunState.RUNNING})
_ADOPTABLE_STATES = frozenset({RunState.ARCHIVED, RunState.PURGED})
_ADOPTION_RECEIPT_FILE = "receipt.toml"
_ADOPTION_RECEIPT_VERSION = 2
_ADOPTION_STAGED_DIR = "adopted"
_BUNDLE_TRANSACTION_RECEIPT_VERSION = 1


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


@dataclass(frozen=True)
class _BundleRestorePlan:
    source: Path
    destination: Path
    runs: list[_BundleRun]
    metadata_bytes: bytes
    metadata_identity: tuple[int, int, int, int]


@dataclass(frozen=True)
class _BundleTransactionRun:
    relative_path: Path
    run_id: str
    state: RunState
    manifest_preimage: bytes
    manifest_postimage: bytes
    directory_device: int
    directory_inode: int
    tree_identity_sha256: str


@dataclass(frozen=True)
class _PendingBundleTransaction:
    action: str
    receipt_path: Path
    source: Path
    destination: Path
    transition_at: str
    source_directory_device: int
    source_directory_inode: int
    source_tree_identity_sha256: str
    marker_preimage: bytes | None
    marker_postimage: bytes | None
    runs: tuple[_BundleTransactionRun, ...]
    receipt_bytes: bytes
    receipt_identity: tuple[int, int, int, int]


@dataclass(frozen=True)
class _AdoptionReceiptRun:
    relative_path: Path
    original_source_path: Path
    run_id: str
    state: RunState
    adopted: bool
    manifest_preimage_sha256: str = ""
    manifest_postimage_sha256: str = ""
    directory_device: int = 0
    directory_inode: int = 0
    tree_identity_sha256: str = ""


@dataclass(frozen=True)
class _PendingAdoption:
    transaction: Path
    source: Path
    destination: Path
    archived_at: str
    runs: tuple[_AdoptionReceiptRun, ...]
    receipt_bytes: bytes
    receipt_identity: tuple[int, int, int, int]
    source_directory_device: int = 0
    source_directory_inode: int = 0
    source_tree_identity_sha256: str = ""
    cleanup_only: bool = False
    completed: bool = False

    @property
    def adopted_runs(self) -> tuple[_AdoptionReceiptRun, ...]:
        return tuple(run for run in self.runs if run.adopted)

    @property
    def source_runs(self) -> tuple[_AdoptionReceiptRun, ...]:
        return tuple(run for run in self.runs if not run.adopted)


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
        if project_root is not None:
            managed_archive_root = _managed_archive_root(project_root)
            try:
                root.relative_to(managed_archive_root)
            except ValueError as exc:
                raise ValueError(
                    "Managed project bundles must be archived inside "
                    f"{managed_archive_root}; an external archive root would "
                    "bypass Result and budget gates"
                ) from exc
    elif project_root is not None:
        root = _managed_archive_root(project_root)
    else:
        root = (source.parent / _ARCHIVE_DIR_NAME).resolve()
    destination = (root / relative).resolve()
    if project_root is not None:
        managed_archive_root = _managed_archive_root(project_root)
        try:
            destination.relative_to(managed_archive_root)
        except ValueError as exc:
            raise ValueError(
                "Managed bundle archive destination escapes runs/_archive: "
                f"{destination}"
            ) from exc
    return destination


def _managed_archive_root(project_root: Path) -> Path:
    """Return a canonical, non-symlink managed archive root."""
    runs_entry = project_root / "runs"
    if runs_entry.is_symlink():
        raise ValueError(f"Managed project runs/ must not be a symlink: {runs_entry}")
    runs_root = runs_entry.resolve()
    archive_entry = runs_entry / _ARCHIVE_DIR_NAME
    if archive_entry.is_symlink():
        raise ValueError(f"Managed archive root must not be a symlink: {archive_entry}")
    if os.path.lexists(archive_entry) and not archive_entry.is_dir():
        raise ValueError(f"Managed archive root must be a directory: {archive_entry}")
    archive_root = archive_entry.resolve()
    try:
        archive_root.relative_to(runs_root)
    except ValueError as exc:
        raise ValueError(
            f"Managed archive root escapes project runs/: {archive_entry}"
        ) from exc
    return archive_root


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


def inspect_bundle_adoption_recovery(
    bundle_dir: Path,
    *,
    archive_root: Path | None = None,
) -> ActionResult | None:
    """Describe a pending or receipt-cleaned adoption without mutating it."""
    pending, pending_error = _find_pending_adoption(
        bundle_dir,
        archive_root=archive_root,
    )
    if pending_error:
        raise SimctlError(pending_error)
    if pending is None:
        pending, completed_error = _find_completed_adoption_retry(
            bundle_dir,
            archive_root=archive_root,
            adopt_archived=True,
        )
        if completed_error:
            raise SimctlError(completed_error)
    if pending is None:
        return None
    return ActionResult(
        action="inspect_bundle_adoption_recovery",
        status=ActionStatus.SUCCESS,
        message="Interrupted bundle adoption can be resumed",
        data={
            "bundle_name": pending.source.name,
            "run_count": len(pending.runs),
            "source_path": str(pending.source),
            "archive_path": str(pending.destination),
            "adopted_run_count": len(pending.adopted_runs),
            "adopted_runs": [
                {"run_id": run.run_id, "status": run.state.value}
                for run in sorted(
                    pending.adopted_runs,
                    key=lambda item: item.run_id,
                )
            ],
            "resumed": True,
        },
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
    pending_bundle, pending_bundle_error = _find_pending_bundle_transaction(
        bundle_dir,
        action="archive",
        archive_root=archive_root,
    )
    if pending_bundle_error:
        return _precondition_fail(action, pending_bundle_error)
    if pending_bundle is not None:
        return _resume_bundle_transaction(pending_bundle)
    completed_bundle = _completed_bundle_transaction_retry(
        bundle_dir,
        action="archive",
        archive_root=archive_root,
    )
    if completed_bundle is not None:
        return completed_bundle

    pending, pending_error = _find_pending_adoption(
        bundle_dir,
        archive_root=archive_root,
    )
    if pending_error:
        return _precondition_fail(action, pending_error)
    if pending is not None:
        if not adopt_archived:
            return _precondition_fail(
                action,
                "An interrupted bundle adoption is pending; retry the same "
                "archive command with adopt_archived enabled",
            )
        return _resume_pending_adoption(pending)

    completed, completed_error = _find_completed_adoption_retry(
        bundle_dir,
        archive_root=archive_root,
        adopt_archived=adopt_archived,
    )
    if completed_error:
        return _precondition_fail(action, completed_error)
    if completed is not None:
        return _resume_pending_adoption(completed)

    plan, plan_error = _build_archive_plan(
        bundle_dir,
        archive_root=archive_root,
        adopt_archived=adopt_archived,
    )
    if plan_error:
        return _precondition_fail(action, plan_error)
    assert plan is not None
    lock_paths = _archive_plan_run_paths(plan)

    try:
        with _acquire_run_guards(lock_paths):
            project_root = _find_project_root_or_none(plan.source)
            namespace_guard = (
                run_namespace_guard(project_root)
                if project_root is not None
                else nullcontext()
            )
            with namespace_guard:
                pending_bundle, pending_bundle_error = _find_pending_bundle_transaction(
                    bundle_dir,
                    action="archive",
                    archive_root=archive_root,
                )
                if pending_bundle_error:
                    return _precondition_fail(action, pending_bundle_error)
                if pending_bundle is not None:
                    return _resume_bundle_transaction_under_guards(pending_bundle)
                current_plan, plan_error = _build_archive_plan(
                    bundle_dir,
                    archive_root=archive_root,
                    adopt_archived=adopt_archived,
                )
                if plan_error:
                    return _precondition_fail(action, plan_error)
                assert current_plan is not None
                drift_error = _validate_locked_run_paths(
                    lock_paths,
                    _archive_plan_run_paths(current_plan),
                )
                if drift_error:
                    return _precondition_fail(action, drift_error)

                archived_at = datetime.now(tz=timezone.utc).isoformat()
                if current_plan.adopted_runs:
                    apply_error = _archive_with_adoption(
                        current_plan,
                        archived_at=archived_at,
                    )
                else:
                    apply_error = _archive_without_adoption(
                        current_plan,
                        archived_at=archived_at,
                    )
                if apply_error:
                    return _error(action, apply_error)

                runs = [*current_plan.source_runs, *current_plan.adopted_runs]
                source = current_plan.source
                destination = current_plan.destination

                emit_event(
                    "artifact_move",
                    action=action,
                    summary=f"Archive bundle {source.name}",
                    path=destination,
                    data={
                        "source_path": str(source),
                        "archive_path": str(destination),
                        "run_count": len(runs),
                        "adopted_run_count": len(current_plan.adopted_runs),
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
                        "adopted_run_count": len(current_plan.adopted_runs),
                        "adopted_runs": _adopted_run_data(current_plan.adopted_runs),
                    },
                )
    except SubmissionLockError as exc:
        return _bundle_lock_failure(action, exc)
    except SimctlError as exc:
        return _error(action, f"Failed to lock the Run namespace: {exc}")


def _find_pending_adoption(
    bundle_dir: Path,
    *,
    archive_root: Path | None,
) -> tuple[_PendingAdoption | None, str | None]:
    source = bundle_dir.expanduser().resolve()
    try:
        destination = default_bundle_archive_destination(
            source,
            archive_root=archive_root,
        )
    except ValueError as exc:
        return None, str(exc)

    parent = destination.parent
    if not os.path.lexists(parent):
        return None, None
    if parent.is_symlink() or not parent.is_dir():
        return None, f"Archive destination parent is not a real directory: {parent}"
    prefix = f".tmp-adopt-{destination.name}-"
    try:
        candidates = sorted(
            (path for path in parent.iterdir() if path.name.startswith(prefix)),
            key=str,
        )
    except OSError as exc:
        return None, f"Cannot inspect pending bundle adoption under {parent}: {exc}"
    if len(candidates) > 1:
        return (
            None,
            "Multiple pending bundle adoption transactions exist for "
            f"{destination}: {', '.join(str(path) for path in candidates)}",
        )
    if not candidates:
        return None, None

    transaction = candidates[0]
    if not os.path.lexists(transaction / _ADOPTION_RECEIPT_FILE):
        pending, error = _load_receiptless_completed_adoption(
            transaction,
            source,
            destination,
        )
    else:
        pending, error = _load_adoption_receipt(transaction)
    if error:
        return None, error
    assert pending is not None
    if pending.source != source or pending.destination != destination:
        return (
            None,
            "Pending bundle adoption receipt does not match this retry: "
            f"expected {source} -> {destination}, receipt contains "
            f"{pending.source} -> {pending.destination}",
        )
    return pending, None


def _find_completed_adoption_retry(
    bundle_dir: Path,
    *,
    archive_root: Path | None,
    adopt_archived: bool,
) -> tuple[_PendingAdoption | None, str | None]:
    """Recognize a fully committed adoption after its transaction was removed."""
    if not adopt_archived:
        return None, None
    source = bundle_dir.expanduser().resolve()
    if os.path.lexists(source):
        return None, None
    try:
        destination = default_bundle_archive_destination(
            source,
            archive_root=archive_root,
        )
    except ValueError as exc:
        return None, str(exc)
    if not os.path.lexists(destination / ARCHIVE_BUNDLE_METADATA_FILE):
        return None, None
    return _load_receiptless_completed_adoption(None, source, destination)


def _load_receiptless_completed_adoption(
    transaction: Path | None,
    source: Path,
    destination: Path,
) -> tuple[_PendingAdoption | None, str | None]:
    if transaction is not None:
        if transaction.is_symlink() or not transaction.is_dir():
            return None, f"Adoption transaction must be a real directory: {transaction}"
        try:
            entries = list(transaction.iterdir())
        except OSError as exc:
            return None, f"Cannot inspect adoption transaction {transaction}: {exc}"
        if entries:
            return (
                None,
                f"Pending adoption receipt is missing and transaction is not empty: "
                f"{transaction}",
            )
    if os.path.lexists(source):
        return None, "Completed adoption retry unexpectedly found the source bundle"
    if destination.is_symlink() or not destination.is_dir():
        return None, f"Completed adoption destination is missing: {destination}"

    marker = destination / ARCHIVE_BUNDLE_METADATA_FILE
    try:
        marker_bytes, _ = _read_bundle_marker(marker)
        raw = tomllib.loads(marker_bytes.decode("utf-8"))
    except (OSError, SimctlError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        return None, f"Cannot verify receiptless adoption cleanup {transaction}: {exc}"
    bundle = raw.get("bundle")
    if (
        set(raw) != {"bundle"}
        or not isinstance(bundle, dict)
        or set(bundle)
        != {
            "format_version",
            "archived_from",
            "archived_at",
            "run_count",
            "adopted_run_ids",
        }
    ):
        return None, f"Invalid bundle marker during adoption cleanup: {marker}"
    format_version = bundle.get("format_version")
    archived_from = bundle.get("archived_from")
    archived_at = bundle.get("archived_at")
    run_count = bundle.get("run_count")
    adopted_ids = bundle.get("adopted_run_ids")
    if (
        type(format_version) is not int
        or format_version != 1
        or archived_from != str(source)
        or not isinstance(archived_at, str)
        or not archived_at
        or type(run_count) is not int
        or run_count < 1
        or not isinstance(adopted_ids, list)
        or not adopted_ids
        or any(not isinstance(item, str) or not item for item in adopted_ids)
        or len(set(adopted_ids)) != len(adopted_ids)
    ):
        return None, f"Bundle marker cannot prove completed adoption: {marker}"
    try:
        timestamp = datetime.fromisoformat(archived_at)
    except ValueError:
        return None, f"Bundle marker has invalid archived_at: {marker}"
    if timestamp.tzinfo is None:
        return None, f"Bundle marker archived_at lacks timezone: {marker}"
    try:
        records = collect_run_manifests_strict(destination)
    except SimctlError as exc:
        return None, f"Cannot verify completed adoption Runs: {exc}"
    if len(records) != run_count:
        return None, f"Bundle marker Run count does not match {destination}"
    adopted_id_set = set(adopted_ids)
    runs: list[_AdoptionReceiptRun] = []
    seen_ids: set[str] = set()
    for run_dir, manifest in records:
        run_id = str(manifest.run.get("id", ""))
        raw_state = str(manifest.run.get("status", ""))
        if not run_id or run_id in seen_ids:
            return None, f"Invalid Run identity during adoption cleanup: {run_dir}"
        try:
            state = RunState(raw_state)
            relative = run_dir.relative_to(destination)
        except ValueError as exc:
            return None, f"Invalid Run during adoption cleanup {run_dir}: {exc}"
        raw_original = manifest.path.get("bundle_archived_from")
        if not isinstance(raw_original, str):
            return None, f"Run lacks bundle_archived_from during cleanup: {run_dir}"
        original = Path(raw_original)
        if not original.is_absolute() or str(original.resolve()) != raw_original:
            return (
                None,
                f"Run has unsafe bundle_archived_from during cleanup: {run_dir}",
            )
        adopted = run_id in adopted_id_set
        if state in _ACTIVE_STATES or (adopted and state not in _ADOPTABLE_STATES):
            return None, f"Invalid Run state during adoption cleanup: {run_dir}"
        expected_original = (
            destination / relative if adopted else source / relative
        ).resolve()
        if original.resolve() != expected_original:
            return None, f"Run path does not match completed adoption: {run_dir}"
        if (
            manifest.path.get("run_dir") != str(run_dir.resolve())
            or manifest.path.get("bundle_archived_at") != archived_at
            or manifest.storage.get("tier") != "cold"
        ):
            return (
                None,
                f"Run manifest is incomplete during adoption cleanup: {run_dir}",
            )
        seen_ids.add(run_id)
        runs.append(
            _AdoptionReceiptRun(
                relative_path=relative,
                original_source_path=original.resolve(),
                run_id=run_id,
                state=state,
                adopted=adopted,
            )
        )
    if adopted_id_set != {run.run_id for run in runs if run.adopted}:
        return None, f"Adopted Run IDs do not match completed bundle: {marker}"
    return (
        _PendingAdoption(
            transaction=(
                transaction.resolve()
                if transaction is not None
                else destination.parent / f".tmp-adopt-{destination.name}-completed"
            ),
            source=source,
            destination=destination,
            archived_at=archived_at,
            runs=tuple(runs),
            receipt_bytes=b"",
            receipt_identity=(0, 0, 0, 0),
            cleanup_only=True,
            completed=transaction is None,
        ),
        None,
    )


def _load_adoption_receipt(
    transaction: Path,
) -> tuple[_PendingAdoption | None, str | None]:
    if transaction.is_symlink() or not transaction.is_dir():
        return None, f"Adoption transaction must be a real directory: {transaction}"
    receipt_path = transaction / _ADOPTION_RECEIPT_FILE
    if not os.path.lexists(receipt_path):
        return None, f"Pending adoption receipt is missing: {receipt_path}"
    try:
        payload, identity = _read_bundle_marker(receipt_path)
        raw = tomllib.loads(payload.decode("utf-8"))
    except (OSError, SimctlError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        return None, f"Cannot read pending adoption receipt {receipt_path}: {exc}"

    adoption = raw.get("adoption")
    raw_runs = raw.get("runs")
    if (
        set(raw) != {"adoption", "runs"}
        or not isinstance(adoption, dict)
        or not isinstance(raw_runs, list)
    ):
        return None, f"Invalid pending adoption receipt structure: {receipt_path}"
    version = adoption.get("format_version")
    if type(version) is not int:
        return None, f"Invalid adoption receipt version in {receipt_path}"
    if version != _ADOPTION_RECEIPT_VERSION:
        return (
            None,
            f"Unsupported adoption receipt version in {receipt_path}: {version}",
        )
    expected_adoption_fields = {
        "format_version",
        "transaction_path",
        "source_path",
        "archive_path",
        "archived_at",
        "run_count",
        "source_run_count",
        "adopted_run_count",
        "source_directory_device",
        "source_directory_inode",
        "source_tree_identity_sha256",
    }
    if set(adoption) != expected_adoption_fields:
        return None, f"Invalid adoption fields in receipt: {receipt_path}"

    raw_transaction = adoption.get("transaction_path")
    raw_source = adoption.get("source_path")
    raw_destination = adoption.get("archive_path")
    archived_at = adoption.get("archived_at")
    raw_run_count = adoption.get("run_count")
    raw_source_count = adoption.get("source_run_count")
    raw_adopted_count = adoption.get("adopted_run_count")
    raw_source_device = adoption.get("source_directory_device")
    raw_source_inode = adoption.get("source_directory_inode")
    raw_source_tree_digest = adoption.get("source_tree_identity_sha256")
    integer_fields = (
        version,
        raw_run_count,
        raw_source_count,
        raw_adopted_count,
        raw_source_device,
        raw_source_inode,
    )
    if any(type(value) is not int for value in integer_fields):
        return None, f"Invalid integer fields in adoption receipt: {receipt_path}"
    assert isinstance(raw_source_device, int)
    assert isinstance(raw_source_inode, int)
    if (
        raw_source_device < 0
        or raw_source_inode <= 0
        or not _is_sha256_digest(raw_source_tree_digest)
    ):
        return None, f"Invalid source tree identity in receipt: {receipt_path}"
    assert isinstance(raw_source_tree_digest, str)
    if not isinstance(archived_at, str) or not archived_at:
        return None, f"Invalid archived_at in adoption receipt: {receipt_path}"
    try:
        timestamp = datetime.fromisoformat(archived_at)
    except ValueError:
        return None, f"Invalid archived_at in adoption receipt: {receipt_path}"
    if timestamp.tzinfo is None:
        return None, f"archived_at must include a timezone in {receipt_path}"

    transaction_path, path_error = _receipt_absolute_path(
        raw_transaction,
        "transaction_path",
        receipt_path,
    )
    if path_error:
        return None, path_error
    source, path_error = _receipt_absolute_path(
        raw_source,
        "source_path",
        receipt_path,
    )
    if path_error:
        return None, path_error
    destination, path_error = _receipt_absolute_path(
        raw_destination,
        "archive_path",
        receipt_path,
    )
    if path_error:
        return None, path_error
    assert transaction_path is not None
    assert source is not None
    assert destination is not None
    if transaction_path != transaction.resolve():
        return (
            None,
            "Adoption receipt transaction_path does not match its directory: "
            f"{transaction_path} != {transaction.resolve()}",
        )

    runs: list[_AdoptionReceiptRun] = []
    run_ids: set[str] = set()
    relative_paths: set[Path] = set()
    for index, item in enumerate(raw_runs):
        if not isinstance(item, dict) or set(item) != {
            "run_id",
            "relative_path",
            "original_source_path",
            "status",
            "adopted",
            "manifest_preimage_sha256",
            "manifest_postimage_sha256",
            "directory_device",
            "directory_inode",
            "tree_identity_sha256",
        }:
            return None, f"Invalid runs[{index}] in adoption receipt: {receipt_path}"
        run_id = item.get("run_id")
        raw_relative = item.get("relative_path")
        raw_original = item.get("original_source_path")
        raw_status = item.get("status")
        adopted = item.get("adopted")
        manifest_preimage_digest = item.get("manifest_preimage_sha256")
        manifest_postimage_digest = item.get("manifest_postimage_sha256")
        directory_device = item.get("directory_device")
        directory_inode = item.get("directory_inode")
        tree_identity_digest = item.get("tree_identity_sha256")
        if not isinstance(run_id, str) or not run_id or run_id in run_ids:
            return None, f"Invalid or duplicate run_id in {receipt_path}: {run_id!r}"
        relative, relative_error = _receipt_relative_path(
            raw_relative,
            receipt_path,
        )
        if relative_error:
            return None, relative_error
        assert relative is not None
        if relative in relative_paths:
            return None, f"Duplicate relative_path in {receipt_path}: {relative}"
        if any(
            _is_relative_to(relative, existing) or _is_relative_to(existing, relative)
            for existing in relative_paths
        ):
            return None, f"Overlapping Run paths in {receipt_path}: {relative}"
        original, path_error = _receipt_absolute_path(
            raw_original,
            f"runs[{index}].original_source_path",
            receipt_path,
        )
        if path_error:
            return None, path_error
        assert original is not None
        if (
            not isinstance(raw_status, str)
            or type(adopted) is not bool
            or type(directory_device) is not int
            or directory_device < 0
            or type(directory_inode) is not int
            or directory_inode <= 0
            or not _is_sha256_digest(manifest_preimage_digest)
            or not _is_sha256_digest(manifest_postimage_digest)
            or not _is_sha256_digest(tree_identity_digest)
        ):
            return None, f"Invalid runs[{index}] fields in {receipt_path}"
        assert isinstance(adopted, bool)
        assert isinstance(manifest_preimage_digest, str)
        assert isinstance(manifest_postimage_digest, str)
        assert isinstance(directory_device, int)
        assert isinstance(directory_inode, int)
        assert isinstance(tree_identity_digest, str)
        try:
            state = RunState(raw_status)
        except ValueError:
            return None, f"Invalid Run state in {receipt_path}: {raw_status!r}"
        if state in _ACTIVE_STATES:
            return (
                None,
                f"Active Run found in adoption receipt: {run_id} ({state.value})",
            )
        if adopted and state not in _ADOPTABLE_STATES:
            return (
                None,
                f"Invalid adopted Run state in {receipt_path}: "
                f"{run_id} ({state.value})",
            )
        expected_original = (
            destination / relative if adopted else source / relative
        ).resolve()
        if original != expected_original:
            return (
                None,
                f"Run source path in adoption receipt is inconsistent for {run_id}: "
                f"{original} != {expected_original}",
            )
        run_ids.add(run_id)
        relative_paths.add(relative)
        runs.append(
            _AdoptionReceiptRun(
                relative_path=relative,
                original_source_path=original,
                run_id=run_id,
                state=state,
                adopted=adopted,
                manifest_preimage_sha256=manifest_preimage_digest,
                manifest_postimage_sha256=manifest_postimage_digest,
                directory_device=directory_device,
                directory_inode=directory_inode,
                tree_identity_sha256=tree_identity_digest,
            )
        )

    source_count = sum(not run.adopted for run in runs)
    adopted_count = sum(run.adopted for run in runs)
    if (
        raw_run_count != len(runs)
        or raw_source_count != source_count
        or raw_adopted_count != adopted_count
        or adopted_count == 0
    ):
        return None, f"Run counts are inconsistent in adoption receipt: {receipt_path}"
    return (
        _PendingAdoption(
            transaction=transaction.resolve(),
            source=source,
            destination=destination,
            archived_at=archived_at,
            runs=tuple(runs),
            receipt_bytes=payload,
            receipt_identity=identity,
            source_directory_device=raw_source_device,
            source_directory_inode=raw_source_inode,
            source_tree_identity_sha256=raw_source_tree_digest,
        ),
        None,
    )


def _is_sha256_digest(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        return len(bytes.fromhex(value)) == 32
    except ValueError:
        return False


def _receipt_absolute_path(
    value: object,
    field: str,
    receipt_path: Path,
) -> tuple[Path | None, str | None]:
    if not isinstance(value, str) or not value:
        return None, f"Invalid {field} in adoption receipt: {receipt_path}"
    path = Path(value)
    if not path.is_absolute():
        return None, f"{field} must be absolute in adoption receipt: {value}"
    resolved = path.resolve()
    if str(resolved) != value:
        return None, f"{field} must be canonical in adoption receipt: {value}"
    return resolved, None


def _receipt_relative_path(
    value: object,
    receipt_path: Path,
) -> tuple[Path | None, str | None]:
    if not isinstance(value, str) or not value:
        return None, f"Invalid relative_path in adoption receipt: {receipt_path}"
    path = Path(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        return None, f"Unsafe relative_path in adoption receipt: {value!r}"
    return path, None


def _resume_pending_adoption(pending: _PendingAdoption) -> ActionResult:
    action = "archive_bundle"
    lock_paths, topology_error = _pending_adoption_run_paths(pending)
    if topology_error:
        return _precondition_fail(action, topology_error)
    assert lock_paths is not None
    try:
        with _acquire_run_guards(lock_paths):
            project_root = _find_project_root_or_none(pending.source)
            namespace_guard = (
                run_namespace_guard(project_root)
                if project_root is not None
                else nullcontext()
            )
            with namespace_guard:
                if pending.completed:
                    current, receipt_error = _load_receiptless_completed_adoption(
                        None,
                        pending.source,
                        pending.destination,
                    )
                elif pending.cleanup_only:
                    current, receipt_error = _load_receiptless_completed_adoption(
                        pending.transaction,
                        pending.source,
                        pending.destination,
                    )
                else:
                    current, receipt_error = _load_adoption_receipt(pending.transaction)
                if receipt_error:
                    return _precondition_fail(action, receipt_error)
                assert current is not None
                if pending.completed or pending.cleanup_only:
                    receipt_changed = current != pending
                else:
                    receipt_changed = (
                        current.receipt_bytes != pending.receipt_bytes
                        or current.receipt_identity != pending.receipt_identity
                    )
                if receipt_changed:
                    return _precondition_fail(
                        action,
                        "Pending adoption receipt changed while acquiring locks; retry",
                    )
                current_paths, topology_error = _pending_adoption_run_paths(current)
                if topology_error:
                    return _precondition_fail(action, topology_error)
                assert current_paths is not None
                drift_error = _validate_locked_run_paths(lock_paths, current_paths)
                if drift_error:
                    return _precondition_fail(action, drift_error)
                if current.cleanup_only and not current.completed:
                    try:
                        _finish_adoption_transaction(current.transaction)
                    except (OSError, SimctlError) as exc:
                        return _error(
                            action,
                            f"Failed to complete adoption transaction cleanup: {exc}",
                        )
                    return _adoption_success_result(current)
                if current.completed:
                    try:
                        _fsync_directory(current.destination.parent)
                    except OSError as exc:
                        return _error(
                            action,
                            "Failed to complete adoption transaction durability: "
                            f"{exc}",
                        )
                    return _adoption_success_result(current)
                apply_error = _forward_pending_adoption(current)
                if apply_error:
                    return _error(action, apply_error)
                return _adoption_success_result(current)
    except SubmissionLockError as exc:
        return _bundle_lock_failure(action, exc)
    except SimctlError as exc:
        return _error(action, f"Failed to lock the Run namespace: {exc}")


def _pending_adoption_run_paths(
    pending: _PendingAdoption,
) -> tuple[tuple[Path, ...] | None, str | None]:
    if pending.completed or pending.cleanup_only:
        completed_paths: list[Path] = []
        for run in pending.runs:
            current = pending.destination / run.relative_path
            if current.is_symlink() or not current.is_dir():
                return None, f"Receipt Run directory is missing or unsafe: {current}"
            try:
                manifest = read_manifest(current)
            except (OSError, SimctlError) as exc:
                return (
                    None,
                    f"Cannot read receipt Run {run.run_id} at {current}: {exc}",
                )
            if (
                str(manifest.run.get("id", "")) != run.run_id
                or str(manifest.run.get("status", "")) != run.state.value
            ):
                return (
                    None,
                    f"Receipt Run identity changed for {run.run_id} at {current}",
                )
            completed_paths.append(current.resolve())
        return _normalize_run_paths(iter(completed_paths)), None

    source_exists, error = _real_directory_state(pending.source, "source bundle")
    if error:
        return None, error
    destination_exists, error = _real_directory_state(
        pending.destination,
        "archive destination",
    )
    if error:
        return None, error
    staged_root = pending.transaction / _ADOPTION_STAGED_DIR
    staged_exists, error = _real_directory_state(staged_root, "staged adoption tree")
    if error:
        return None, error

    if source_exists and destination_exists and not staged_exists:
        phase = "receipt"
    elif source_exists and not destination_exists and staged_exists:
        phase = "destination_staged"
    elif not source_exists and destination_exists:
        phase = "source_moved"
    else:
        return (
            None,
            "Invalid pending adoption topology: "
            f"source_exists={source_exists}, "
            f"destination_exists={destination_exists}, "
            f"staged_exists={staged_exists}",
        )

    transaction_error = _validate_adoption_transaction_tree(pending, staged_exists)
    if transaction_error:
        return None, transaction_error

    source_root = pending.destination if phase == "source_moved" else pending.source
    source_identity_error = _validate_pending_source_tree(pending, source_root)
    if source_identity_error:
        return None, source_identity_error

    current_paths: list[Path] = []
    for run in pending.runs:
        if not run.adopted:
            current = (
                pending.destination / run.relative_path
                if phase == "source_moved"
                else pending.source / run.relative_path
            )
        elif phase == "receipt":
            current = pending.destination / run.relative_path
        elif phase == "destination_staged":
            current = staged_root / run.relative_path
        else:
            staged = staged_root / run.relative_path
            final = pending.destination / run.relative_path
            staged_run_exists = os.path.lexists(staged)
            final_run_exists = os.path.lexists(final)
            if staged_run_exists == final_run_exists:
                return (
                    None,
                    "Invalid adopted Run topology for "
                    f"{run.run_id}: staged_exists={staged_run_exists}, "
                    f"final_exists={final_run_exists}",
                )
            current = staged if staged_run_exists else final
        if current.is_symlink() or not current.is_dir():
            return None, f"Receipt Run directory is missing or unsafe: {current}"
        integrity_error = _validate_pending_run_tree(run, current)
        if integrity_error:
            return None, integrity_error
        current_paths.append(current.resolve())
    return _normalize_run_paths(iter(current_paths)), None


def _validate_pending_source_tree(
    pending: _PendingAdoption,
    current_root: Path,
) -> str | None:
    try:
        identity = _directory_identity(current_root, "source bundle")
    except (OSError, SimctlError) as exc:
        return f"Cannot verify receipt source tree {current_root}: {exc}"
    expected_identity = (
        pending.source_directory_device,
        pending.source_directory_inode,
    )
    if identity != expected_identity:
        return (
            "Receipt source directory identity changed at "
            f"{current_root}: expected {expected_identity}, found {identity}"
        )
    try:
        tree_identity = _bundle_scaffold_identity(
            current_root,
            tuple(run.relative_path for run in pending.runs),
        )
    except (OSError, SimctlError) as exc:
        return f"Cannot verify receipt source tree {current_root}: {exc}"
    if tree_identity != pending.source_tree_identity_sha256:
        return (
            "Receipt source tree contains a changed or unknown artifact at "
            f"{current_root}"
        )
    return None


def _validate_pending_run_tree(
    run: _AdoptionReceiptRun,
    current: Path,
) -> str | None:
    try:
        identity = _directory_identity(current, "Run directory")
    except (OSError, SimctlError) as exc:
        return f"Cannot verify receipt Run {run.run_id} at {current}: {exc}"
    expected_identity = (run.directory_device, run.directory_inode)
    if identity != expected_identity:
        return (
            f"Receipt Run directory identity changed for {run.run_id} at {current}: "
            f"expected {expected_identity}, found {identity}"
        )
    try:
        tree_identity = _run_tree_identity(current)
        manifest_bytes, _ = _read_bundle_marker(current / "manifest.toml")
        raw = tomllib.loads(manifest_bytes.decode("utf-8"))
        manifest = ManifestData.from_dict(raw)
    except (
        OSError,
        SimctlError,
        UnicodeDecodeError,
        tomllib.TOMLDecodeError,
    ) as exc:
        return f"Cannot verify receipt Run {run.run_id} at {current}: {exc}"
    if tree_identity != run.tree_identity_sha256:
        return (
            f"Receipt Run tree contains a changed or unknown artifact for "
            f"{run.run_id} at {current}"
        )
    manifest_digest = _sha256_bytes(manifest_bytes)
    if manifest_digest not in {
        run.manifest_preimage_sha256,
        run.manifest_postimage_sha256,
    }:
        return f"Receipt Run manifest digest changed for {run.run_id} at {current}"
    if (
        str(manifest.run.get("id", "")) != run.run_id
        or str(manifest.run.get("status", "")) != run.state.value
    ):
        return f"Receipt Run identity changed for {run.run_id} at {current}"
    return None


def _real_directory_state(path: Path, label: str) -> tuple[bool, str | None]:
    if not os.path.lexists(path):
        return False, None
    if path.is_symlink() or not path.is_dir():
        return False, f"Pending adoption {label} must be a real directory: {path}"
    return True, None


def _validate_adoption_transaction_tree(
    pending: _PendingAdoption,
    staged_exists: bool,
) -> str | None:
    allowed_entries = {_ADOPTION_RECEIPT_FILE}
    if staged_exists:
        allowed_entries.add(_ADOPTION_STAGED_DIR)
    try:
        entries = list(pending.transaction.iterdir())
    except OSError as exc:
        return f"Cannot inspect adoption transaction {pending.transaction}: {exc}"
    for entry in entries:
        if entry.name not in allowed_entries:
            return f"Adoption transaction contains an unowned path: {entry}"
    if not staged_exists:
        return None
    staged_root = pending.transaction / _ADOPTION_STAGED_DIR
    run_roots = [staged_root / run.relative_path for run in pending.adopted_runs]
    try:
        paths = list(staged_root.rglob("*"))
    except OSError as exc:
        return f"Cannot inspect staged adoption tree {staged_root}: {exc}"
    for path in paths:
        if path.is_symlink():
            return f"Staged adoption tree contains a symlink: {path}"
        if any(_is_relative_to(path, root) for root in run_roots):
            continue
        if path.is_dir() and any(_is_relative_to(root, path) for root in run_roots):
            continue
        return f"Staged adoption tree contains an unowned path: {path}"
    return None


def _forward_pending_adoption(pending: _PendingAdoption) -> str | None:
    staged_root = pending.transaction / _ADOPTION_STAGED_DIR
    try:
        source_exists = os.path.lexists(pending.source)
        destination_exists = os.path.lexists(pending.destination)
        staged_exists = os.path.lexists(staged_root)
        if source_exists and destination_exists and not staged_exists:
            move_directory_noreplace(pending.destination, staged_root)
            destination_exists = False
            staged_exists = True
        if source_exists and not destination_exists and staged_exists:
            move_directory_noreplace(pending.source, pending.destination)

        for run in pending.adopted_runs:
            staged = staged_root / run.relative_path
            final = pending.destination / run.relative_path
            if os.path.lexists(final) and not os.path.lexists(staged):
                continue
            if not os.path.lexists(staged) or os.path.lexists(final):
                raise SimctlError(
                    f"Cannot resume adopted Run {run.run_id}: invalid topology"
                )
            _create_missing_parents(final.parent, pending.destination)
            move_directory_noreplace(staged, final)

        _ensure_pending_bundle_marker(pending)
        _update_pending_adoption_manifests(pending)
        _, final_integrity_error = _pending_adoption_run_paths(pending)
        if final_integrity_error:
            raise SimctlError(
                "Cannot finalize adoption with changed receipt inputs: "
                f"{final_integrity_error}"
            )
        if os.path.lexists(staged_root):
            _remove_empty_tree(staged_root)
        _finish_adoption_transaction(pending.transaction)
    except (OSError, SimctlError) as exc:
        return f"Failed to resume archived Run adoption: {exc}"
    return None


def _ensure_pending_bundle_marker(pending: _PendingAdoption) -> None:
    marker = pending.destination / ARCHIVE_BUNDLE_METADATA_FILE
    expected = _pending_bundle_metadata(pending)
    if not os.path.lexists(marker):
        _write_toml_atomic(marker, expected)
        return
    payload, _ = _read_bundle_marker(marker)
    try:
        current = tomllib.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise SimctlError(f"Invalid existing bundle marker {marker}: {exc}") from exc
    if current != expected:
        raise SimctlError(f"Existing bundle marker does not match receipt: {marker}")


def _pending_bundle_metadata(pending: _PendingAdoption) -> dict[str, Any]:
    return {
        "bundle": {
            "format_version": 1,
            "archived_from": str(pending.source),
            "archived_at": pending.archived_at,
            "run_count": len(pending.runs),
            "adopted_run_ids": sorted(run.run_id for run in pending.adopted_runs),
        }
    }


def _update_pending_adoption_manifests(pending: _PendingAdoption) -> None:
    for run in pending.runs:
        final_run_dir = pending.destination / run.relative_path
        integrity_error = _validate_pending_run_tree(run, final_run_dir)
        if integrity_error:
            raise SimctlError(integrity_error)
        manifest = read_manifest(final_run_dir)
        if (
            str(manifest.run.get("id", "")) != run.run_id
            or str(manifest.run.get("status", "")) != run.state.value
        ):
            raise SimctlError(
                f"Receipt Run identity changed for {run.run_id} at {final_run_dir}"
            )
        _apply_bundle_archive_manifest_fields(
            manifest,
            final_run_dir=final_run_dir,
            original_source_path=run.original_source_path,
            adopted=run.adopted,
            archived_at=pending.archived_at,
        )
        write_manifest(final_run_dir, manifest)
        manifest_bytes, _ = _read_bundle_marker(final_run_dir / "manifest.toml")
        if _sha256_bytes(manifest_bytes) != run.manifest_postimage_sha256:
            raise SimctlError(
                f"Archived manifest postimage does not match receipt for {run.run_id}"
            )


def _adoption_success_result(pending: _PendingAdoption) -> ActionResult:
    adopted = pending.adopted_runs
    emit_event(
        "artifact_move",
        action="archive_bundle",
        summary=f"Archive bundle {pending.source.name}",
        path=pending.destination,
        data={
            "source_path": str(pending.source),
            "archive_path": str(pending.destination),
            "run_count": len(pending.runs),
            "adopted_run_count": len(adopted),
            "resumed": True,
        },
        requires_verbose=True,
    )
    return ActionResult(
        action="archive_bundle",
        status=ActionStatus.SUCCESS,
        message="Bundle adoption resumed and archived",
        data={
            "bundle_name": pending.source.name,
            "run_count": len(pending.runs),
            "source_path": str(pending.source),
            "archive_path": str(pending.destination),
            "adopted_run_count": len(adopted),
            "adopted_runs": [
                {"run_id": run.run_id, "status": run.state.value}
                for run in sorted(adopted, key=lambda item: item.run_id)
            ],
            "resumed": True,
        },
    )


@logged_action("restore_bundle")
def restore_bundle(bundle_dir: Path) -> ActionResult:
    """Restore an archived parent directory and preserve every run state."""
    action = "restore_bundle"
    pending, pending_error = _find_pending_bundle_transaction(
        bundle_dir,
        action="restore",
        archive_root=None,
    )
    if pending_error:
        return _precondition_fail(action, pending_error)
    if pending is not None:
        return _resume_bundle_transaction(pending)
    completed = _completed_bundle_transaction_retry(
        bundle_dir,
        action="restore",
        archive_root=None,
    )
    if completed is not None:
        return completed

    plan, plan_error = _build_restore_plan(bundle_dir)
    if plan_error:
        return _precondition_fail(action, plan_error)
    assert plan is not None
    lock_paths = _restore_plan_run_paths(plan)

    try:
        with _acquire_run_guards(lock_paths):
            project_root = _find_project_root_or_none(plan.source)
            namespace_guard = (
                run_namespace_guard(project_root)
                if project_root is not None
                else nullcontext()
            )
            with namespace_guard:
                pending, pending_error = _find_pending_bundle_transaction(
                    bundle_dir,
                    action="restore",
                    archive_root=None,
                )
                if pending_error:
                    return _precondition_fail(action, pending_error)
                if pending is not None:
                    return _resume_bundle_transaction_under_guards(pending)
                current_plan, plan_error = _build_restore_plan(bundle_dir)
                if plan_error:
                    return _precondition_fail(action, plan_error)
                assert current_plan is not None
                if (
                    current_plan.metadata_bytes != plan.metadata_bytes
                    or current_plan.metadata_identity != plan.metadata_identity
                    or current_plan.destination != plan.destination
                ):
                    return _precondition_fail(
                        action,
                        "Archived bundle marker changed while acquiring locks; retry",
                    )
                drift_error = _validate_locked_run_paths(
                    lock_paths,
                    _restore_plan_run_paths(current_plan),
                )
                if drift_error:
                    return _precondition_fail(action, drift_error)
                return _apply_bundle_restore(current_plan)
    except SubmissionLockError as exc:
        return _bundle_lock_failure(action, exc)
    except SimctlError as exc:
        return _error(action, f"Failed to lock the Run namespace: {exc}")


def _find_project_root_or_none(path: Path) -> Path | None:
    try:
        return find_project_root(path)
    except ProjectNotFoundError:
        return None


def _load_bundle_runs(bundle_dir: Path) -> tuple[list[_BundleRun], str | None]:
    runs: list[_BundleRun] = []
    try:
        records = collect_run_manifests_strict(bundle_dir)
    except SimctlError as exc:
        return [], f"Cannot safely inspect bundle Run namespace: {exc}"
    for run_dir, manifest in records:
        try:
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


def _archive_plan_run_paths(plan: _BundleArchivePlan) -> tuple[Path, ...]:
    return _normalize_run_paths(
        run.source_path for run in [*plan.source_runs, *plan.adopted_runs]
    )


def _restore_plan_run_paths(plan: _BundleRestorePlan) -> tuple[Path, ...]:
    return _normalize_run_paths(run.source_path for run in plan.runs)


def _normalize_run_paths(paths: Iterator[Path]) -> tuple[Path, ...]:
    return tuple(sorted({path.resolve() for path in paths}, key=str))


@contextmanager
def _acquire_run_guards(run_paths: tuple[Path, ...]) -> Iterator[None]:
    """Acquire all child Run guards in a deterministic deadlock-free order."""
    with ExitStack() as stack:
        for run_path in run_paths:
            stack.enter_context(submission_guard(run_path))
        yield


def _validate_locked_run_paths(
    locked_paths: tuple[Path, ...],
    current_paths: tuple[Path, ...],
) -> str | None:
    if locked_paths == current_paths:
        return None
    return (
        "Bundle child runs changed while acquiring locks; retry the operation "
        "so every current Run can be locked"
    )


def _bundle_lock_failure(action: str, exc: SubmissionLockError) -> ActionResult:
    return ActionResult(
        action=action,
        status=ActionStatus.PRECONDITION_FAILED,
        message=f"Failed to lock bundle child Run: {exc}",
        data={"lock_path": str(exc.lock_path)},
    )


def _build_restore_plan(
    bundle_dir: Path,
) -> tuple[_BundleRestorePlan | None, str | None]:
    source = bundle_dir.expanduser().resolve()
    metadata_path = source / ARCHIVE_BUNDLE_METADATA_FILE
    if not source.is_dir() or not os.path.lexists(metadata_path):
        return None, f"Archived bundle metadata not found: {metadata_path}"
    try:
        metadata_bytes, metadata_identity = _read_bundle_marker(metadata_path)
    except (OSError, SimctlError) as exc:
        return None, f"Cannot read archived bundle metadata {metadata_path}: {exc}"

    destination, metadata_error = _read_restore_destination(
        metadata_path,
        metadata_bytes,
    )
    if metadata_error:
        return None, metadata_error
    assert destination is not None

    destination_error = _validate_destination(source, destination, "Restore")
    if destination_error:
        return None, destination_error
    managed_destination_error = _validate_managed_restore_destination(
        source,
        destination,
    )
    if managed_destination_error:
        return None, managed_destination_error

    runs, load_error = _load_bundle_runs(source)
    if load_error:
        return None, load_error
    if not runs:
        return None, f"No runs found under bundle: {source}"

    return (
        _BundleRestorePlan(
            source=source,
            destination=destination,
            runs=runs,
            metadata_bytes=metadata_bytes,
            metadata_identity=metadata_identity,
        ),
        None,
    )


def _apply_bundle_restore(plan: _BundleRestorePlan) -> ActionResult:
    action = "restore_bundle"
    source = plan.source
    destination = plan.destination
    restored_at = datetime.now(tz=timezone.utc).isoformat()
    pending, receipt_error = _create_bundle_transaction(
        action="restore",
        source=source,
        destination=destination,
        transition_at=restored_at,
        runs=plan.runs,
        marker_preimage=plan.metadata_bytes,
        marker_postimage=None,
    )
    if receipt_error:
        return _error(action, receipt_error)
    assert pending is not None
    forward_error = _forward_bundle_transaction(pending)
    if forward_error:
        return _error(action, forward_error)

    emit_event(
        "artifact_move",
        action=action,
        summary=f"Restore bundle {source.name}",
        path=destination,
        data={
            "source_path": str(source),
            "restore_path": str(destination),
            "run_count": len(plan.runs),
        },
        requires_verbose=True,
    )
    return ActionResult(
        action=action,
        status=ActionStatus.SUCCESS,
        message="Bundle restored",
        data={
            "bundle_name": source.name,
            "run_count": len(plan.runs),
            "source_path": str(source),
            "restore_path": str(destination),
        },
    )


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

    source_ids = {run.run_id for run in source_runs}
    duplicate_ids = sorted(source_ids & {run.run_id for run in adopted_runs})
    if duplicate_ids:
        return (
            None,
            "Cannot adopt Runs whose IDs already exist in the source bundle: "
            + ", ".join(duplicate_ids),
        )

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


def _bundle_transaction_receipt_path(source: Path, action: str) -> Path:
    token = hashlib.sha256(f"{action}\0{source.resolve()}".encode()).hexdigest()[:20]
    return source.parent / f".runops-bundle-{action}-{token}.receipt.toml"


def _find_pending_bundle_transaction(
    bundle_dir: Path,
    *,
    action: str,
    archive_root: Path | None,
) -> tuple[_PendingBundleTransaction | None, str | None]:
    source = bundle_dir.expanduser().resolve()
    receipt_path = _bundle_transaction_receipt_path(source, action)
    if not os.path.lexists(receipt_path):
        return None, None
    pending, error = _load_bundle_transaction_receipt(receipt_path)
    if error:
        return None, error
    assert pending is not None
    if pending.action != action or pending.source != source:
        return (
            None,
            f"Pending bundle transaction does not match this retry: {receipt_path}",
        )
    if action == "archive":
        try:
            expected_destination = default_bundle_archive_destination(
                source,
                archive_root=archive_root,
            )
        except ValueError as exc:
            return None, str(exc)
        if pending.destination != expected_destination:
            return (
                None,
                "Pending bundle archive destination does not match this retry: "
                f"{pending.destination} != {expected_destination}",
            )
    return pending, None


def _completed_bundle_transaction_retry(
    bundle_dir: Path,
    *,
    action: str,
    archive_root: Path | None,
) -> ActionResult | None:
    source = bundle_dir.expanduser().resolve()
    if os.path.lexists(source):
        return None
    if action == "archive":
        try:
            destination = default_bundle_archive_destination(
                source,
                archive_root=archive_root,
            )
        except ValueError:
            return None
        marker = destination / ARCHIVE_BUNDLE_METADATA_FILE
        try:
            marker_bytes, _ = _read_bundle_marker(marker)
            raw = tomllib.loads(marker_bytes.decode("utf-8"))
        except (
            OSError,
            SimctlError,
            UnicodeDecodeError,
            tomllib.TOMLDecodeError,
        ):
            return None
        bundle = raw.get("bundle")
        if (
            set(raw) != {"bundle"}
            or not isinstance(bundle, dict)
            or bundle.get("format_version") != 1
            or bundle.get("archived_from") != str(source)
            or bundle.get("adopted_run_ids") != []
        ):
            return None
        expected_tier = "cold"
        expected_path_field = "bundle_archived_from"
        expected_path_root = source
        raw_run_count = bundle.get("run_count")
        if type(raw_run_count) is not int:
            return None
        expected_run_count: int | None = raw_run_count
    else:
        restore_destination = _completed_restore_destination(source)
        if restore_destination is None or os.path.lexists(
            restore_destination / ARCHIVE_BUNDLE_METADATA_FILE
        ):
            return None
        destination = restore_destination
        expected_tier = "hot"
        expected_path_field = "bundle_restored_from"
        expected_path_root = source
        expected_run_count = None
    if destination.is_symlink() or not destination.is_dir():
        return None
    try:
        records = collect_run_manifests_strict(destination)
    except SimctlError:
        return None
    if not records:
        return None
    if expected_run_count is not None and expected_run_count != len(records):
        return None
    for run_dir, manifest in records:
        relative = run_dir.relative_to(destination)
        if (
            manifest.path.get("run_dir") != str(run_dir.resolve())
            or manifest.path.get(expected_path_field)
            != str((expected_path_root / relative).resolve())
            or manifest.storage.get("tier") != expected_tier
        ):
            return None
    action_name = f"{action}_bundle"
    return ActionResult(
        action=action_name,
        status=ActionStatus.SUCCESS,
        message=f"Bundle {action} was already complete",
        data={
            "bundle_name": source.name,
            "run_count": len(records),
            "source_path": str(source),
            ("archive_path" if action == "archive" else "restore_path"): str(
                destination
            ),
            "adopted_run_count": 0,
            "adopted_runs": [],
            "resumed": True,
        },
    )


def _completed_restore_destination(source: Path) -> Path | None:
    parts = source.parts
    try:
        archive_index = len(parts) - 1 - parts[::-1].index(_ARCHIVE_DIR_NAME)
    except ValueError:
        return None
    if archive_index == 0 or archive_index == len(parts) - 1:
        return None
    return Path(*parts[:archive_index], *parts[archive_index + 1 :]).resolve()


def _create_bundle_transaction(
    *,
    action: str,
    source: Path,
    destination: Path,
    transition_at: str,
    runs: list[_BundleRun],
    marker_preimage: bytes | None,
    marker_postimage: bytes | None,
) -> tuple[_PendingBundleTransaction | None, str | None]:
    receipt_path = _bundle_transaction_receipt_path(source, action)
    if os.path.lexists(receipt_path):
        pending, error = _load_bundle_transaction_receipt(receipt_path)
        if error:
            return None, error
        assert pending is not None
        if (
            pending.action != action
            or pending.source != source.resolve()
            or pending.destination != destination.resolve()
        ):
            return None, (
                "Existing bundle receipt does not match the requested transaction: "
                f"{receipt_path}"
            )
        integrity_error = _validate_bundle_transaction_live(pending)
        if integrity_error:
            return None, integrity_error
        return pending, None
    try:
        payload = _bundle_transaction_receipt_data(
            action=action,
            receipt_path=receipt_path,
            source=source,
            destination=destination,
            transition_at=transition_at,
            runs=runs,
            marker_preimage=marker_preimage,
            marker_postimage=marker_postimage,
        )
        _write_toml_atomic(receipt_path, payload)
    except (OSError, SimctlError, ValueError) as exc:
        return None, f"Cannot create durable bundle {action} receipt: {exc}"
    pending, error = _load_bundle_transaction_receipt(receipt_path)
    if error:
        return None, f"Cannot verify durable bundle {action} receipt: {error}"
    assert pending is not None
    integrity_error = _validate_bundle_transaction_live(pending)
    if integrity_error:
        return None, (
            f"Bundle {action} inputs changed after the durable receipt was written: "
            f"{integrity_error}"
        )
    return pending, None


def _bundle_transaction_receipt_data(
    *,
    action: str,
    receipt_path: Path,
    source: Path,
    destination: Path,
    transition_at: str,
    runs: list[_BundleRun],
    marker_preimage: bytes | None,
    marker_postimage: bytes | None,
) -> dict[str, Any]:
    if action not in {"archive", "restore"}:
        raise ValueError(f"Unsupported bundle transaction action: {action}")
    source_identity = _directory_identity(source, "bundle source")
    relative_paths = tuple(run.relative_path for run in runs)
    source_tree_identity = _bundle_scaffold_identity(source, relative_paths)
    receipt_runs: list[dict[str, Any]] = []
    for run in runs:
        expected = ManifestData.from_dict(run.manifest.to_dict())
        if action == "archive":
            _apply_bundle_archive_manifest_fields(
                expected,
                final_run_dir=destination / run.relative_path,
                original_source_path=run.source_path,
                adopted=False,
                archived_at=transition_at,
            )
        else:
            _apply_bundle_restore_manifest_fields(
                expected,
                final_run_dir=destination / run.relative_path,
                archived_run_dir=run.source_path,
                restored_at=transition_at,
            )
        directory_identity = _directory_identity(run.source_path, "Run directory")
        receipt_runs.append(
            {
                "run_id": run.run_id,
                "relative_path": run.relative_path.as_posix(),
                "status": run.state.value,
                "manifest_preimage_base64": _encode_receipt_bytes(run.original_bytes),
                "manifest_preimage_sha256": _sha256_bytes(run.original_bytes),
                "manifest_postimage_base64": _encode_receipt_bytes(
                    tomli_w.dumps(expected.to_dict()).encode("utf-8")
                ),
                "manifest_postimage_sha256": _sha256_bytes(
                    tomli_w.dumps(expected.to_dict()).encode("utf-8")
                ),
                "directory_device": directory_identity[0],
                "directory_inode": directory_identity[1],
                "tree_identity_sha256": _run_tree_identity(run.source_path),
            }
        )
    return {
        "transaction": {
            "format_version": _BUNDLE_TRANSACTION_RECEIPT_VERSION,
            "action": action,
            "receipt_path": str(receipt_path.resolve()),
            "source_path": str(source.resolve()),
            "destination_path": str(destination.resolve()),
            "transition_at": transition_at,
            "run_count": len(receipt_runs),
            "source_directory_device": source_identity[0],
            "source_directory_inode": source_identity[1],
            "source_tree_identity_sha256": source_tree_identity,
            "marker_preimage_present": marker_preimage is not None,
            "marker_preimage_base64": _encode_receipt_bytes(marker_preimage or b""),
            "marker_postimage_present": marker_postimage is not None,
            "marker_postimage_base64": _encode_receipt_bytes(marker_postimage or b""),
        },
        "runs": receipt_runs,
    }


def _encode_receipt_bytes(payload: bytes) -> str:
    return base64.b64encode(payload).decode("ascii")


def _decode_receipt_bytes(value: object, field: str, path: Path) -> bytes:
    if not isinstance(value, str):
        raise ValueError(f"Invalid {field} in bundle receipt: {path}")
    try:
        return base64.b64decode(value.encode("ascii"), validate=True)
    except (UnicodeEncodeError, ValueError) as exc:
        raise ValueError(f"Invalid {field} in bundle receipt: {path}") from exc


def _load_bundle_transaction_receipt(
    receipt_path: Path,
) -> tuple[_PendingBundleTransaction | None, str | None]:
    try:
        payload, receipt_identity = _read_bundle_marker(receipt_path)
        raw = tomllib.loads(payload.decode("utf-8"))
    except (OSError, SimctlError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        return None, f"Cannot read pending bundle receipt {receipt_path}: {exc}"
    transaction = raw.get("transaction")
    raw_runs = raw.get("runs")
    expected_fields = {
        "format_version",
        "action",
        "receipt_path",
        "source_path",
        "destination_path",
        "transition_at",
        "run_count",
        "source_directory_device",
        "source_directory_inode",
        "source_tree_identity_sha256",
        "marker_preimage_present",
        "marker_preimage_base64",
        "marker_postimage_present",
        "marker_postimage_base64",
    }
    if (
        set(raw) != {"transaction", "runs"}
        or not isinstance(transaction, dict)
        or set(transaction) != expected_fields
        or not isinstance(raw_runs, list)
    ):
        return None, f"Invalid pending bundle receipt structure: {receipt_path}"
    version = transaction.get("format_version")
    if type(version) is not int or version != _BUNDLE_TRANSACTION_RECEIPT_VERSION:
        return None, f"Unsupported pending bundle receipt version: {receipt_path}"
    action = transaction.get("action")
    transition_at = transaction.get("transition_at")
    raw_count = transaction.get("run_count")
    raw_device = transaction.get("source_directory_device")
    raw_inode = transaction.get("source_directory_inode")
    raw_tree = transaction.get("source_tree_identity_sha256")
    pre_present = transaction.get("marker_preimage_present")
    post_present = transaction.get("marker_postimage_present")
    if (
        action not in {"archive", "restore"}
        or not isinstance(transition_at, str)
        or not transition_at
        or type(raw_count) is not int
        or raw_count < 1
        or type(raw_device) is not int
        or raw_device < 0
        or type(raw_inode) is not int
        or raw_inode <= 0
        or not _is_sha256(raw_tree)
        or type(pre_present) is not bool
        or type(post_present) is not bool
    ):
        return None, f"Invalid pending bundle receipt fields: {receipt_path}"
    try:
        timestamp = datetime.fromisoformat(transition_at)
    except ValueError:
        return None, f"Invalid transition_at in bundle receipt: {receipt_path}"
    if timestamp.tzinfo is None:
        return None, f"transition_at lacks timezone in bundle receipt: {receipt_path}"
    try:
        bound_receipt = _canonical_receipt_path(
            transaction.get("receipt_path"), "receipt_path", receipt_path
        )
        source = _canonical_receipt_path(
            transaction.get("source_path"), "source_path", receipt_path
        )
        destination = _canonical_receipt_path(
            transaction.get("destination_path"),
            "destination_path",
            receipt_path,
        )
        marker_preimage_payload = _decode_receipt_bytes(
            transaction.get("marker_preimage_base64"),
            "marker_preimage_base64",
            receipt_path,
        )
        marker_postimage_payload = _decode_receipt_bytes(
            transaction.get("marker_postimage_base64"),
            "marker_postimage_base64",
            receipt_path,
        )
    except ValueError as exc:
        return None, str(exc)
    if bound_receipt != receipt_path.resolve():
        return None, f"Bundle receipt path binding changed: {receipt_path}"
    if _bundle_transaction_receipt_path(source, str(action)) != receipt_path.resolve():
        return (
            None,
            f"Bundle receipt filename does not match its source: {receipt_path}",
        )
    marker_preimage = marker_preimage_payload if pre_present else None
    marker_postimage = marker_postimage_payload if post_present else None
    if (
        (not pre_present and marker_preimage_payload)
        or (not post_present and marker_postimage_payload)
        or (action == "archive" and (pre_present or not post_present))
        or (action == "restore" and (not pre_present or post_present))
    ):
        return None, f"Invalid marker images in bundle receipt: {receipt_path}"

    runs: list[_BundleTransactionRun] = []
    seen_ids: set[str] = set()
    seen_paths: set[Path] = set()
    expected_run_fields = {
        "run_id",
        "relative_path",
        "status",
        "manifest_preimage_base64",
        "manifest_preimage_sha256",
        "manifest_postimage_base64",
        "manifest_postimage_sha256",
        "directory_device",
        "directory_inode",
        "tree_identity_sha256",
    }
    for index, item in enumerate(raw_runs):
        if not isinstance(item, dict) or set(item) != expected_run_fields:
            return None, f"Invalid runs[{index}] in bundle receipt: {receipt_path}"
        run_id = item.get("run_id")
        raw_relative = item.get("relative_path")
        raw_status = item.get("status")
        if not isinstance(run_id, str) or not run_id or run_id in seen_ids:
            return None, f"Invalid Run ID in bundle receipt: {receipt_path}"
        try:
            relative = _canonical_relative_path(raw_relative)
            state = RunState(str(raw_status))
            preimage = _decode_receipt_bytes(
                item.get("manifest_preimage_base64"),
                "manifest_preimage_base64",
                receipt_path,
            )
            postimage = _decode_receipt_bytes(
                item.get("manifest_postimage_base64"),
                "manifest_postimage_base64",
                receipt_path,
            )
        except (ValueError, SimctlError) as exc:
            return None, f"Invalid Run in bundle receipt {receipt_path}: {exc}"
        if relative in seen_paths or any(
            _is_relative_to(relative, path) or _is_relative_to(path, relative)
            for path in seen_paths
        ):
            return None, f"Overlapping Run paths in bundle receipt: {receipt_path}"
        pre_digest = item.get("manifest_preimage_sha256")
        post_digest = item.get("manifest_postimage_sha256")
        directory_device = item.get("directory_device")
        directory_inode = item.get("directory_inode")
        tree_digest = item.get("tree_identity_sha256")
        if (
            not _is_sha256(pre_digest)
            or not _is_sha256(post_digest)
            or _sha256_bytes(preimage) != pre_digest
            or _sha256_bytes(postimage) != post_digest
            or type(directory_device) is not int
            or directory_device < 0
            or type(directory_inode) is not int
            or directory_inode <= 0
            or not _is_sha256(tree_digest)
        ):
            return None, f"Invalid Run image binding in bundle receipt: {receipt_path}"
        try:
            pre_manifest = ManifestData.from_dict(
                tomllib.loads(preimage.decode("utf-8"))
            )
            post_manifest = ManifestData.from_dict(
                tomllib.loads(postimage.decode("utf-8"))
            )
        except (
            UnicodeDecodeError,
            tomllib.TOMLDecodeError,
            SimctlError,
        ) as exc:
            return None, f"Invalid manifest image in bundle receipt: {exc}"
        if any(
            str(manifest.run.get("id", "")) != run_id
            or str(manifest.run.get("status", "")) != state.value
            for manifest in (pre_manifest, post_manifest)
        ):
            return None, f"Run identity changed in bundle receipt: {run_id}"
        seen_ids.add(run_id)
        seen_paths.add(relative)
        runs.append(
            _BundleTransactionRun(
                relative_path=relative,
                run_id=run_id,
                state=state,
                manifest_preimage=preimage,
                manifest_postimage=postimage,
                directory_device=directory_device,
                directory_inode=directory_inode,
                tree_identity_sha256=str(tree_digest),
            )
        )
    if len(runs) != raw_count:
        return None, f"Run count changed in bundle receipt: {receipt_path}"
    marker_error = _validate_bundle_receipt_marker_contract(
        action=str(action),
        source=source,
        destination=destination,
        transition_at=transition_at,
        marker_preimage=marker_preimage,
        marker_postimage=marker_postimage,
        run_count=len(runs),
        receipt_path=receipt_path,
    )
    if marker_error:
        return None, marker_error
    for run in runs:
        try:
            expected = ManifestData.from_dict(
                tomllib.loads(run.manifest_preimage.decode("utf-8"))
            )
            if action == "archive":
                _apply_bundle_archive_manifest_fields(
                    expected,
                    final_run_dir=destination / run.relative_path,
                    original_source_path=source / run.relative_path,
                    adopted=False,
                    archived_at=transition_at,
                )
            else:
                _apply_bundle_restore_manifest_fields(
                    expected,
                    final_run_dir=destination / run.relative_path,
                    archived_run_dir=source / run.relative_path,
                    restored_at=transition_at,
                )
            expected_postimage = tomli_w.dumps(expected.to_dict()).encode("utf-8")
        except (
            UnicodeDecodeError,
            tomllib.TOMLDecodeError,
            SimctlError,
        ) as exc:
            return None, f"Cannot derive bundle receipt postimage: {exc}"
        if run.manifest_postimage != expected_postimage:
            return None, (
                "Bundle receipt contains a non-deterministic manifest postimage for "
                f"{run.run_id}: {receipt_path}"
            )
    return (
        _PendingBundleTransaction(
            action=str(action),
            receipt_path=receipt_path.resolve(),
            source=source,
            destination=destination,
            transition_at=transition_at,
            source_directory_device=raw_device,
            source_directory_inode=raw_inode,
            source_tree_identity_sha256=str(raw_tree),
            marker_preimage=marker_preimage,
            marker_postimage=marker_postimage,
            runs=tuple(runs),
            receipt_bytes=payload,
            receipt_identity=receipt_identity,
        ),
        None,
    )


def _validate_bundle_receipt_marker_contract(
    *,
    action: str,
    source: Path,
    destination: Path,
    transition_at: str,
    marker_preimage: bytes | None,
    marker_postimage: bytes | None,
    run_count: int,
    receipt_path: Path,
) -> str | None:
    if action == "archive":
        expected = tomli_w.dumps(
            {
                "bundle": {
                    "format_version": 1,
                    "archived_from": str(source),
                    "archived_at": transition_at,
                    "run_count": run_count,
                    "adopted_run_ids": [],
                }
            }
        ).encode("utf-8")
        if marker_preimage is not None or marker_postimage != expected:
            return f"Bundle archive marker postimage changed in {receipt_path}"
        return None
    if marker_preimage is None or marker_postimage is not None:
        return f"Bundle restore marker image changed in {receipt_path}"
    try:
        raw = tomllib.loads(marker_preimage.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        return f"Invalid restore marker preimage in {receipt_path}: {exc}"
    bundle = raw.get("bundle")
    adopted_ids = bundle.get("adopted_run_ids") if isinstance(bundle, dict) else None
    if (
        set(raw) != {"bundle"}
        or not isinstance(bundle, dict)
        or set(bundle)
        != {
            "format_version",
            "archived_from",
            "archived_at",
            "run_count",
            "adopted_run_ids",
        }
        or type(bundle.get("format_version")) is not int
        or bundle.get("format_version") != 1
        or bundle.get("archived_from") != str(destination)
        or type(bundle.get("run_count")) is not int
        or bundle.get("run_count") != run_count
        or not isinstance(adopted_ids, list)
        or any(not isinstance(item, str) or not item for item in adopted_ids)
        or len(set(adopted_ids)) != len(adopted_ids)
    ):
        return f"Restore marker preimage does not match receipt: {receipt_path}"
    archived_at = bundle.get("archived_at")
    if not isinstance(archived_at, str):
        return f"Restore marker archived_at is invalid: {receipt_path}"
    try:
        timestamp = datetime.fromisoformat(archived_at)
    except ValueError:
        return f"Restore marker archived_at is invalid: {receipt_path}"
    if timestamp.tzinfo is None:
        return f"Restore marker archived_at lacks timezone: {receipt_path}"
    return None


def _canonical_receipt_path(value: object, field: str, receipt: Path) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"Invalid {field} in bundle receipt: {receipt}")
    path = Path(value).expanduser()
    if not path.is_absolute() or str(path.resolve()) != value:
        raise ValueError(f"Non-canonical {field} in bundle receipt: {receipt}")
    return path.resolve()


def _canonical_relative_path(value: object) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError("relative path is empty")
    path = Path(value)
    if path.is_absolute() or path == Path(".") or ".." in path.parts:
        raise ValueError(f"relative path is unsafe: {value!r}")
    if path.as_posix() != value:
        raise ValueError(f"relative path is not canonical: {value!r}")
    return path


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _archive_without_adoption(
    plan: _BundleArchivePlan,
    *,
    archived_at: str,
) -> str | None:
    marker_postimage = tomli_w.dumps(_bundle_metadata(plan, archived_at)).encode(
        "utf-8"
    )
    pending, receipt_error = _create_bundle_transaction(
        action="archive",
        source=plan.source,
        destination=plan.destination,
        transition_at=archived_at,
        runs=plan.source_runs,
        marker_preimage=None,
        marker_postimage=marker_postimage,
    )
    if receipt_error:
        return receipt_error
    assert pending is not None
    return _forward_bundle_transaction(pending)


def _archive_with_adoption(
    plan: _BundleArchivePlan,
    *,
    archived_at: str,
) -> str | None:
    transaction = _new_staging_path(plan.destination)
    staged_adopted = transaction / _ADOPTION_STAGED_DIR
    destination_staged = False
    source_moved = False
    moved_adopted: list[_BundleRun] = []
    created_parents: list[Path] = []
    transaction_created = False
    try:
        transaction.mkdir()
        transaction_created = True
        _fsync_directory(transaction.parent)
        _write_toml_atomic(
            transaction / _ADOPTION_RECEIPT_FILE,
            _adoption_receipt_data(plan, transaction, archived_at),
        )
        pending, receipt_error = _load_adoption_receipt(transaction)
        if receipt_error:
            return f"Cannot verify durable adoption receipt: {receipt_error}"
        assert pending is not None
        _, integrity_error = _pending_adoption_run_paths(pending)
        if integrity_error:
            return (
                "Adoption inputs changed after the durable receipt was written: "
                f"{integrity_error}"
            )
        move_directory_noreplace(plan.destination, staged_adopted)
        destination_staged = True
        move_directory_noreplace(plan.source, plan.destination)
        source_moved = True
        for run in plan.adopted_runs:
            target = plan.destination / run.relative_path
            created_parents.extend(
                _create_missing_parents(target.parent, plan.destination)
            )
            move_directory_noreplace(staged_adopted / run.relative_path, target)
            moved_adopted.append(run)
        _write_toml_atomic(
            plan.destination / ARCHIVE_BUNDLE_METADATA_FILE,
            _bundle_metadata(plan, archived_at),
        )
        _update_archived_manifests(plan, archived_at=archived_at)
        current, receipt_error = _load_adoption_receipt(transaction)
        if receipt_error:
            return (
                "Cannot finalize adoption with an unverifiable durable receipt: "
                f"{receipt_error}"
            )
        assert current is not None
        _, integrity_error = _pending_adoption_run_paths(current)
        if integrity_error:
            return (
                "Cannot finalize adoption with changed receipt inputs: "
                f"{integrity_error}"
            )
        _remove_empty_tree(staged_adopted)
        _finish_adoption_transaction(transaction)
    except (OSError, SimctlError) as exc:
        rollback_error = None
        if transaction_created:
            rollback_error = _rollback_adopted_archive(
                plan,
                transaction=transaction,
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
        _apply_bundle_archive_manifest_fields(
            manifest,
            final_run_dir=final_run_dir,
            original_source_path=run.source_path,
            adopted=id(run) in adopted_ids,
            archived_at=archived_at,
        )
        write_manifest(final_run_dir, manifest)


def _apply_bundle_archive_manifest_fields(
    manifest: ManifestData,
    *,
    final_run_dir: Path,
    original_source_path: Path,
    adopted: bool,
    archived_at: str,
) -> None:
    if "created_at_path" not in manifest.path:
        created_at_path = original_source_path
        if adopted:
            archived_from = manifest.path.get("archived_from")
            if not isinstance(archived_from, str) or not archived_from:
                raise SimctlError("Cannot adopt Run: path.archived_from is missing")
            candidate = Path(archived_from).expanduser()
            if not candidate.is_absolute():
                raise SimctlError(
                    "Cannot adopt Run: path.archived_from is not absolute"
                )
            created_at_path = candidate.resolve()
        manifest.path["created_at_path"] = str(created_at_path)
    manifest.path["run_dir"] = str(final_run_dir.resolve())
    manifest.path["bundle_archived_from"] = str(original_source_path)
    manifest.path["bundle_archived_at"] = archived_at
    manifest.storage["tier"] = "cold"
    manifest.storage.setdefault("form", "full")


def _apply_bundle_restore_manifest_fields(
    manifest: ManifestData,
    *,
    final_run_dir: Path,
    archived_run_dir: Path,
    restored_at: str,
) -> None:
    manifest.path["run_dir"] = str(final_run_dir.resolve())
    manifest.path["bundle_restored_from"] = str(archived_run_dir.resolve())
    manifest.path["bundle_restored_at"] = restored_at
    manifest.storage["tier"] = "hot"
    manifest.storage.setdefault("form", "full")


def _resume_bundle_transaction(
    pending: _PendingBundleTransaction,
) -> ActionResult:
    action_name = f"{pending.action}_bundle"
    paths, integrity_error = _bundle_transaction_run_paths(pending)
    if integrity_error:
        return _precondition_fail(
            action_name,
            "Pending bundle transaction changed; receipt and data were retained: "
            f"{integrity_error}",
        )
    assert paths is not None
    try:
        with _acquire_run_guards(paths):
            current_root = (
                pending.source
                if os.path.lexists(pending.source)
                else pending.destination
            )
            project_root = _find_project_root_or_none(current_root)
            namespace_guard = (
                run_namespace_guard(project_root)
                if project_root is not None
                else nullcontext()
            )
            with namespace_guard:
                return _resume_bundle_transaction_under_guards(pending)
    except SubmissionLockError as exc:
        return _bundle_lock_failure(action_name, exc)
    except SimctlError as exc:
        return _error(action_name, f"Failed to lock the Run namespace: {exc}")


def _resume_bundle_transaction_under_guards(
    pending: _PendingBundleTransaction,
) -> ActionResult:
    action_name = f"{pending.action}_bundle"
    current, receipt_error = _load_bundle_transaction_receipt(pending.receipt_path)
    if receipt_error:
        return _precondition_fail(action_name, receipt_error)
    assert current is not None
    if (
        current.receipt_bytes != pending.receipt_bytes
        or current.receipt_identity != pending.receipt_identity
    ):
        return _precondition_fail(
            action_name,
            "Pending bundle receipt changed while acquiring locks; no data was changed",
        )
    integrity_error = _validate_bundle_transaction_live(current)
    if integrity_error:
        return _precondition_fail(
            action_name,
            "Pending bundle transaction changed; receipt and data were retained: "
            f"{integrity_error}",
        )
    forward_error = _forward_bundle_transaction(current)
    if forward_error:
        return _error(action_name, forward_error)

    label = "archived" if current.action == "archive" else "restored"
    emit_event(
        "artifact_move",
        action=action_name,
        summary=f"Resume bundle {current.action} {current.source.name}",
        path=current.destination,
        data={
            "source_path": str(current.source),
            "destination_path": str(current.destination),
            "run_count": len(current.runs),
            "resumed": True,
        },
        requires_verbose=True,
    )
    return ActionResult(
        action=action_name,
        status=ActionStatus.SUCCESS,
        message=f"Bundle {label} after transaction recovery",
        data={
            "bundle_name": current.source.name,
            "run_count": len(current.runs),
            "source_path": str(current.source),
            ("archive_path" if current.action == "archive" else "restore_path"): str(
                current.destination
            ),
            "adopted_run_count": 0,
            "adopted_runs": [],
            "resumed": True,
        },
    )


def _bundle_transaction_run_paths(
    pending: _PendingBundleTransaction,
) -> tuple[tuple[Path, ...] | None, str | None]:
    integrity_error = _validate_bundle_transaction_live(pending)
    if integrity_error:
        return None, integrity_error
    root = pending.source if os.path.lexists(pending.source) else pending.destination
    return (
        _normalize_run_paths(iter(root / run.relative_path for run in pending.runs)),
        None,
    )


def _validate_bundle_transaction_live(
    pending: _PendingBundleTransaction,
    *,
    require_final: bool = False,
) -> str | None:
    source_exists, source_error = _real_bundle_directory(pending.source, "source")
    if source_error:
        return source_error
    destination_exists, destination_error = _real_bundle_directory(
        pending.destination, "destination"
    )
    if destination_error:
        return destination_error
    if source_exists == destination_exists:
        return (
            "invalid source/destination topology: "
            f"source_exists={source_exists}, destination_exists={destination_exists}"
        )
    at_destination = destination_exists
    root = pending.destination if at_destination else pending.source
    try:
        root_identity = _directory_identity(root, "bundle transaction tree")
        scaffold_identity = _bundle_scaffold_identity(
            root,
            tuple(run.relative_path for run in pending.runs),
        )
    except (OSError, SimctlError) as exc:
        return f"cannot verify bundle tree {root}: {exc}"
    expected_root_identity = (
        pending.source_directory_device,
        pending.source_directory_inode,
    )
    if root_identity != expected_root_identity:
        return (
            f"bundle directory identity changed at {root}: expected "
            f"{expected_root_identity}, found {root_identity}"
        )
    if scaffold_identity != pending.source_tree_identity_sha256:
        return f"bundle tree contains a changed or unknown artifact at {root}"

    manifest_phases: list[str] = []
    for run in pending.runs:
        run_dir = root / run.relative_path
        try:
            identity = _directory_identity(run_dir, "Run directory")
            tree_identity = _run_tree_identity(run_dir)
            manifest_bytes, _ = _read_bundle_marker(run_dir / "manifest.toml")
        except (OSError, SimctlError) as exc:
            return f"cannot verify receipt Run {run.run_id} at {run_dir}: {exc}"
        expected_identity = (run.directory_device, run.directory_inode)
        if identity != expected_identity:
            return (
                f"Run directory identity changed for {run.run_id} at {run_dir}: "
                f"expected {expected_identity}, found {identity}"
            )
        if tree_identity != run.tree_identity_sha256:
            return (
                f"Run tree contains a changed or unknown artifact for "
                f"{run.run_id} at {run_dir}"
            )
        if manifest_bytes == run.manifest_preimage:
            manifest_phases.append("pre")
        elif manifest_bytes == run.manifest_postimage:
            manifest_phases.append("post")
        else:
            return f"Run manifest image changed for {run.run_id} at {run_dir}"

    marker_path = root / ARCHIVE_BUNDLE_METADATA_FILE
    marker_bytes: bytes | None = None
    if os.path.lexists(marker_path):
        try:
            marker_bytes, _ = _read_bundle_marker(marker_path)
        except (OSError, SimctlError) as exc:
            return f"cannot verify bundle marker {marker_path}: {exc}"
    allowed_marker_images = {
        image
        for image in (pending.marker_preimage, pending.marker_postimage)
        if image is not None
    }
    if marker_bytes is not None and marker_bytes not in allowed_marker_images:
        return f"bundle marker image changed at {marker_path}"

    all_pre = all(phase == "pre" for phase in manifest_phases)
    all_post = all(phase == "post" for phase in manifest_phases)
    if not at_destination:
        if not all_pre:
            return "manifest postimages appeared before the bundle move"
        if pending.action == "archive" and marker_bytes not in {
            None,
            pending.marker_postimage,
        }:
            return "invalid archive marker before the bundle move"
        if pending.action == "restore" and marker_bytes != pending.marker_preimage:
            return "restore marker changed before the bundle move"
    elif pending.action == "archive":
        if marker_bytes != pending.marker_postimage:
            return "archive marker is missing after the bundle move"
    elif marker_bytes is None and not all_post:
        return "restore marker disappeared before all manifest postimages committed"
    elif marker_bytes not in {None, pending.marker_preimage}:
        return "invalid restore marker after the bundle move"

    if require_final:
        if not at_destination or not all_post:
            return "bundle transaction has not reached its final manifest image"
        if pending.action == "archive" and marker_bytes != pending.marker_postimage:
            return "archive marker has not reached its final image"
        if pending.action == "restore" and marker_bytes is not None:
            return "restore marker still exists after commit"
    return None


def _real_bundle_directory(path: Path, label: str) -> tuple[bool, str | None]:
    if not os.path.lexists(path):
        return False, None
    if path.is_symlink() or not path.is_dir():
        return False, f"bundle transaction {label} must be a real directory: {path}"
    return True, None


def _assert_bundle_receipt_current(pending: _PendingBundleTransaction) -> None:
    payload, identity = _read_bundle_marker(pending.receipt_path)
    if payload != pending.receipt_bytes or identity != pending.receipt_identity:
        raise SimctlError(f"bundle transaction receipt changed: {pending.receipt_path}")


def _forward_bundle_transaction(
    pending: _PendingBundleTransaction,
) -> str | None:
    try:
        _assert_bundle_receipt_current(pending)
        integrity_error = _validate_bundle_transaction_live(pending)
        if integrity_error:
            raise SimctlError(integrity_error)

        at_destination = os.path.lexists(pending.destination)
        if not at_destination:
            if pending.action == "archive":
                marker = pending.source / ARCHIVE_BUNDLE_METADATA_FILE
                if not os.path.lexists(marker):
                    assert pending.marker_postimage is not None
                    _write_bytes_atomic(marker, pending.marker_postimage)
                integrity_error = _validate_bundle_transaction_live(pending)
                if integrity_error:
                    raise SimctlError(integrity_error)
            _assert_bundle_receipt_current(pending)
            pending.destination.parent.mkdir(parents=True, exist_ok=True)
            move_directory_noreplace(pending.source, pending.destination)

        integrity_error = _validate_bundle_transaction_live(pending)
        if integrity_error:
            raise SimctlError(integrity_error)
        for run in pending.runs:
            run_dir = pending.destination / run.relative_path
            manifest_bytes, _ = _read_bundle_marker(run_dir / "manifest.toml")
            if manifest_bytes == run.manifest_postimage:
                continue
            if manifest_bytes != run.manifest_preimage:
                raise SimctlError(
                    f"Run manifest image changed for {run.run_id} at {run_dir}"
                )
            _assert_bundle_receipt_current(pending)
            _write_bytes_atomic(
                run_dir / "manifest.toml",
                run.manifest_postimage,
            )
            integrity_error = _validate_bundle_transaction_live(pending)
            if integrity_error:
                raise SimctlError(integrity_error)

        marker = pending.destination / ARCHIVE_BUNDLE_METADATA_FILE
        if pending.action == "restore" and os.path.lexists(marker):
            _assert_bundle_receipt_current(pending)
            _unlink_file_durable_with_retry(marker)

        integrity_error = _validate_bundle_transaction_live(
            pending,
            require_final=True,
        )
        if integrity_error:
            raise SimctlError(integrity_error)
        _assert_bundle_receipt_current(pending)
        integrity_error = _validate_bundle_transaction_live(
            pending,
            require_final=True,
        )
        if integrity_error:
            raise SimctlError(integrity_error)
        _unlink_file_durable_with_retry(pending.receipt_path)
    except (OSError, SimctlError) as exc:
        return (
            f"Failed to resume bundle {pending.action}; durable receipt and live "
            f"data were retained without rollback: {exc}"
        )
    return None


def _unlink_file_durable_with_retry(path: Path) -> None:
    try:
        _unlink_file_durable(path)
    except OSError:
        if os.path.lexists(path):
            raise
        _fsync_directory(path.parent)


def _rollback_adopted_archive(
    plan: _BundleArchivePlan,
    *,
    transaction: Path,
    destination_staged: bool,
    source_moved: bool,
    moved_adopted: list[_BundleRun],
    created_parents: list[Path],
) -> str | None:
    staged_adopted = transaction / _ADOPTION_STAGED_DIR
    try:
        moved_ids = {id(run) for run in moved_adopted}
        source_root = plan.destination if source_moved else plan.source
        for run in plan.source_runs:
            _write_bytes_atomic(
                source_root / run.relative_path / "manifest.toml",
                run.original_bytes,
            )
        for run in plan.adopted_runs:
            if id(run) in moved_ids:
                root = plan.destination
            elif destination_staged:
                root = staged_adopted
            else:
                root = plan.destination
            _write_bytes_atomic(
                root / run.relative_path / "manifest.toml",
                run.original_bytes,
            )
        if source_moved:
            _remove_file_durable_best_effort(
                plan.destination / ARCHIVE_BUNDLE_METADATA_FILE
            )
        if destination_staged:
            for run in reversed(moved_adopted):
                original = staged_adopted / run.relative_path
                original.parent.mkdir(parents=True, exist_ok=True)
                move_directory_noreplace(
                    plan.destination / run.relative_path,
                    original,
                )
            for parent in sorted(
                set(created_parents),
                key=lambda path: len(path.parts),
                reverse=True,
            ):
                with suppress(OSError):
                    parent.rmdir()
        if source_moved:
            move_directory_noreplace(plan.destination, plan.source)
        if destination_staged:
            move_directory_noreplace(staged_adopted, plan.destination)
        _finish_adoption_transaction(transaction)
    except (OSError, SimctlError) as exc:
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


def _adoption_receipt_data(
    plan: _BundleArchivePlan,
    transaction: Path,
    archived_at: str,
) -> dict[str, Any]:
    adopted_ids = {id(run) for run in plan.adopted_runs}
    all_runs = [*plan.source_runs, *plan.adopted_runs]
    source_identity = _directory_identity(plan.source, "source bundle")
    source_tree_identity = _bundle_scaffold_identity(
        plan.source,
        tuple(run.relative_path for run in all_runs),
    )
    runs = []
    for run in all_runs:
        adopted = id(run) in adopted_ids
        directory_identity = _directory_identity(run.source_path, "Run directory")
        expected = ManifestData.from_dict(run.manifest.to_dict())
        _apply_bundle_archive_manifest_fields(
            expected,
            final_run_dir=plan.destination / run.relative_path,
            original_source_path=run.source_path,
            adopted=adopted,
            archived_at=archived_at,
        )
        runs.append(
            {
                "run_id": run.run_id,
                "relative_path": run.relative_path.as_posix(),
                "original_source_path": str(run.source_path),
                "status": run.state.value,
                "adopted": adopted,
                "manifest_preimage_sha256": _sha256_bytes(run.original_bytes),
                "manifest_postimage_sha256": _sha256_bytes(
                    tomli_w.dumps(expected.to_dict()).encode("utf-8")
                ),
                "directory_device": directory_identity[0],
                "directory_inode": directory_identity[1],
                "tree_identity_sha256": _run_tree_identity(run.source_path),
            }
        )
    return {
        "adoption": {
            "format_version": _ADOPTION_RECEIPT_VERSION,
            "transaction_path": str(transaction.resolve()),
            "source_path": str(plan.source),
            "archive_path": str(plan.destination),
            "archived_at": archived_at,
            "run_count": len(runs),
            "source_run_count": len(plan.source_runs),
            "adopted_run_count": len(plan.adopted_runs),
            "source_directory_device": source_identity[0],
            "source_directory_inode": source_identity[1],
            "source_tree_identity_sha256": source_tree_identity,
        },
        "runs": runs,
    }


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _directory_identity(path: Path, label: str) -> tuple[int, int]:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise SimctlError(f"cannot inspect {label} {path}: {exc}") from exc
    if not stat.S_ISDIR(metadata.st_mode) or path.is_symlink():
        raise SimctlError(f"{label} must be a real directory: {path}")
    return metadata.st_dev, metadata.st_ino


def _run_tree_identity(run_dir: Path) -> str:
    return _tree_identity_digest(
        run_dir,
        skipped_paths=frozenset({Path("manifest.toml")}),
    )


def _bundle_scaffold_identity(
    bundle_dir: Path,
    run_paths: tuple[Path, ...],
) -> str:
    return _tree_identity_digest(
        bundle_dir,
        skipped_paths=frozenset({Path(ARCHIVE_BUNDLE_METADATA_FILE)}),
        skipped_subtrees=frozenset(run_paths),
        transparent_directories=frozenset(
            ancestor
            for run_path in run_paths
            for ancestor in run_path.parents
            if ancestor != Path(".")
        ),
    )


def _tree_identity_digest(
    root: Path,
    *,
    skipped_paths: frozenset[Path] = frozenset(),
    skipped_subtrees: frozenset[Path] = frozenset(),
    transparent_directories: frozenset[Path] = frozenset(),
) -> str:
    digest = hashlib.sha256()

    def visit(directory: Path, relative_parent: Path) -> None:
        try:
            with os.scandir(directory) as stream:
                entries = sorted(stream, key=lambda entry: os.fsencode(entry.name))
        except OSError as exc:
            raise SimctlError(
                f"cannot inspect tree identity under {directory}: {exc}"
            ) from exc
        for entry in entries:
            relative = relative_parent / entry.name
            if relative in skipped_paths or relative in skipped_subtrees:
                continue
            try:
                metadata = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise SimctlError(
                    f"cannot inspect tree identity for {entry.path}: {exc}"
                ) from exc
            is_directory = stat.S_ISDIR(metadata.st_mode)
            if relative not in transparent_directories:
                _update_tree_identity_digest(digest, relative, metadata, entry.path)
            if is_directory:
                visit(Path(entry.path), relative)

    visit(root, Path())
    return digest.hexdigest()


def _update_tree_identity_digest(
    digest: Any,
    relative: Path,
    metadata: os.stat_result,
    path: str,
) -> None:
    if stat.S_ISREG(metadata.st_mode):
        kind = "file"
    elif stat.S_ISDIR(metadata.st_mode):
        kind = "directory"
    elif stat.S_ISLNK(metadata.st_mode):
        kind = "symlink"
    else:
        kind = "other"
    fields: list[str | bytes | int] = [
        os.fsencode(relative.as_posix()),
        kind,
        metadata.st_dev,
        metadata.st_ino,
        stat.S_IMODE(metadata.st_mode),
        metadata.st_nlink,
    ]
    if not stat.S_ISDIR(metadata.st_mode):
        fields.extend((metadata.st_size, metadata.st_mtime_ns))
    if stat.S_ISLNK(metadata.st_mode):
        fields.append(os.fsencode(os.readlink(path)))
    for field in fields:
        payload = field if isinstance(field, bytes) else str(field).encode("ascii")
        digest.update(len(payload).to_bytes(8, byteorder="big"))
        digest.update(payload)


def _finish_adoption_transaction(transaction: Path) -> None:
    if not os.path.lexists(transaction):
        return
    if transaction.is_symlink() or not transaction.is_dir():
        raise SimctlError(
            f"adoption transaction must be a real directory: {transaction}"
        )
    staged_adopted = transaction / _ADOPTION_STAGED_DIR
    if os.path.lexists(staged_adopted):
        _remove_empty_tree(staged_adopted)
    receipt = transaction / _ADOPTION_RECEIPT_FILE
    if os.path.lexists(receipt):
        _unlink_file_durable(receipt)
    transaction.rmdir()
    _fsync_directory(transaction.parent)


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
            f".tmp-adopt-{destination.name}-{secrets.token_hex(6)}"
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


def _validate_managed_restore_destination(
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
        return f"Managed project bundles must be restored inside {runs_root}"
    if relative.parts and relative.parts[0] == _ARCHIVE_DIR_NAME:
        return "Managed project bundles must be restored to the active runs/ view"
    return None


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
        temporary = ""
        _fsync_directory(path.parent)
    except BaseException:
        if temporary:
            with suppress(OSError):
                os.unlink(temporary)
        raise


def _write_bytes_atomic(path: Path, payload: bytes) -> None:
    descriptor, temporary = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = ""
        _fsync_directory(path.parent)
    except BaseException:
        if temporary:
            with suppress(OSError):
                os.unlink(temporary)
        raise


def _unlink_file_durable(path: Path) -> None:
    path.unlink()
    _fsync_directory(path.parent)


def _remove_file_durable_best_effort(path: Path) -> None:
    with suppress(OSError):
        path.unlink()
    with suppress(OSError):
        _fsync_directory(path.parent)


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _read_restore_destination(
    path: Path,
    payload: bytes,
) -> tuple[Path | None, str | None]:
    try:
        raw = tomllib.loads(payload.decode("utf-8"))
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
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        return None, f"Invalid archived bundle metadata {path}: {exc}"


def _read_bundle_marker(path: Path) -> tuple[bytes, tuple[int, int, int, int]]:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise SimctlError(f"cannot inspect bundle marker {path}: {exc}") from exc
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise SimctlError(f"bundle marker must be a single-link regular file: {path}")
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            identity = (
                opened.st_dev,
                opened.st_ino,
                opened.st_size,
                opened.st_mtime_ns,
            )
            expected = (
                metadata.st_dev,
                metadata.st_ino,
                metadata.st_size,
                metadata.st_mtime_ns,
            )
            if (
                identity != expected
                or opened.st_nlink != 1
                or not stat.S_ISREG(opened.st_mode)
            ):
                raise SimctlError(f"bundle marker changed while opening: {path}")
            payload = stream.read()
    except OSError as exc:
        raise SimctlError(f"cannot read bundle marker {path}: {exc}") from exc
    return payload, identity
