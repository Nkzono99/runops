"""Lifecycle service for smoke/debug attempts outside the normal Run model."""

from __future__ import annotations

import contextlib
import copy
import fcntl
import hashlib
import inspect
import json
import os
import shutil
import stat
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

import tomli_w

from runops.adapters.base import SimulatorAdapter
from runops.application.run_creation import load_adapter_for_simulator
from runops.application.run_creation.staging import (
    commit_staged_directory,
    copy_case_files,
    move_directory_noreplace,
)
from runops.core.case import CaseData, load_case, resolve_case
from runops.core.exceptions import ParameterValidationError, SimctlError
from runops.core.project import load_project
from runops.core.test_attempt import (
    TEST_ATTEMPT_KINDS,
    TEST_ATTEMPT_TERMINAL_STATES,
    TEST_RECEIPT_FILE,
    TestAttemptData,
    TestAttemptError,
    build_test_attempt_cache_key,
    discover_test_attempts,
    load_test_attempt,
    parse_test_timestamp,
    write_test_attempt,
)

_LOCK_FILE = "test-attempt.lock"
_SEQUENCE_FILE = "test-id-sequence.toml"
_CLEANUP_RECEIPT_FILE = ".cleanup-pending.json"
_SHA256_PREFIX = "sha256:"


class TestAttemptWorkflowError(SimctlError):
    """Raised when a TestAttempt lifecycle operation cannot proceed safely."""


@dataclass(frozen=True)
class PreparedTestAttempt:
    """Result of preparing or cache-skipping one TestAttempt."""

    attempt: TestAttemptData
    path: Path
    cached: bool
    cache_age_seconds: float | None = None


@dataclass(frozen=True)
class TestAttemptCleanResult:
    """Result of an age-bounded terminal TestAttempt cleanup."""

    removed_ids: tuple[str, ...]


@dataclass(frozen=True)
class _CleanupEntry:
    attempt_id: str
    directory_device: int
    directory_inode: int
    tree_digest: str
    test_receipt_digest: str
    input_hash: str
    tree_entries: dict[str, str]


@dataclass(frozen=True)
class _CleanupTreeSnapshot:
    directory_device: int
    directory_inode: int
    tree_digest: str
    test_receipt_digest: str
    input_hash: str
    tree_entries: dict[str, str]


def hash_case_input(case_dir: Path) -> str:
    """Hash sorted ``case/input`` relative paths and raw contents canonically."""
    input_root = case_dir.absolute() / "input"
    return _hash_input_root(input_root)


def prepare_test_attempt(
    project_root: Path,
    case: str,
    *,
    kind: str,
    profile: str = "",
    source_commit: str = "",
    executable_hash: str = "",
    adapter: str = "",
    adapter_version: str = "",
    cache_ttl: timedelta = timedelta(hours=24),
    rerun: bool = False,
    now: datetime | None = None,
) -> PreparedTestAttempt:
    """Prepare a local receipt/input snapshot; never submit a scheduler job."""
    root = project_root.resolve()
    if kind not in TEST_ATTEMPT_KINDS:
        raise TestAttemptWorkflowError("TestAttempt kind must be smoke or debug")
    case_ref = case.strip()
    if not case_ref:
        raise TestAttemptWorkflowError("TestAttempt case must not be empty")
    if cache_ttl < timedelta(0):
        raise TestAttemptWorkflowError("TestAttempt cache TTL must not be negative")
    timestamp = _aware_now(now)

    try:
        case_dir = resolve_case(case_ref, root)
        case_data = load_case(case_dir)
    except SimctlError:
        raise
    selected_profile = profile.strip() or kind
    try:
        canonical_case = case_dir.relative_to(root / "cases").as_posix()
    except ValueError:
        canonical_case = case_data.name
    try:
        project = load_project(root)
        renderer = load_adapter_for_simulator(project, case_data.simulator)
        selected_adapter = renderer.name
        requested_adapter = adapter.strip()
        if requested_adapter and requested_adapter != selected_adapter:
            raise TestAttemptWorkflowError(
                f"requested adapter {requested_adapter!r} does not match "
                f"case adapter {selected_adapter!r}"
            )
        selected_adapter_version = (
            adapter_version.strip() or _adapter_implementation_hash(renderer)
        )
        selected_source_commit = source_commit.strip()
        selected_executable_hash = executable_hash.strip()
        if not selected_source_commit or not selected_executable_hash:
            simulator_config = dict(project.simulators.get(case_data.simulator, {}))
            runtime: dict[str, Any] = {}
            provenance: dict[str, Any] = {}
            if simulator_config:
                try:
                    runtime = renderer.resolve_runtime(
                        simulator_config,
                        str(simulator_config.get("resolver_mode", "package")),
                    )
                    provenance = renderer.collect_provenance(runtime)
                except (OSError, RuntimeError, TypeError, ValueError):
                    pass
                if not selected_source_commit:
                    selected_source_commit = str(
                        provenance.get("git_commit", runtime.get("git_commit", ""))
                    ).strip()
                if not selected_executable_hash:
                    selected_executable_hash = str(
                        provenance.get("exe_hash", runtime.get("exe_hash", ""))
                    ).strip()
        with _rendered_input_snapshot(root, case_data, renderer) as rendered_input:
            input_hash = _hash_input_root(rendered_input)
            cache_key = build_test_attempt_cache_key(
                kind=kind,
                case=canonical_case,
                profile=selected_profile,
                source_commit=selected_source_commit,
                executable_hash=selected_executable_hash,
                input_hash=input_hash,
                adapter=selected_adapter,
                adapter_version=selected_adapter_version,
            )
            cache_eligible = all(
                value.strip()
                for value in (
                    selected_source_commit,
                    selected_executable_hash,
                    selected_adapter_version,
                )
            )
            with _test_attempt_lock(root):
                test_root = _ensure_test_root(root, create=True)
                assert test_root is not None
                existing = discover_test_attempts(test_root)
                cached_match = None
                if not rerun and cache_eligible:
                    cached_match = _find_cached_pass(
                        existing,
                        cache_key,
                        cache_ttl=cache_ttl,
                        now=timestamp,
                    )
                if cached_match is not None:
                    cached_attempt, cache_age = cached_match
                    return PreparedTestAttempt(
                        attempt=cached_attempt,
                        path=cached_attempt.attempt_dir,
                        cached=True,
                        cache_age_seconds=cache_age.total_seconds(),
                    )
                attempt_id = _reserve_test_id_locked(root, timestamp, existing)
                observation = (
                    "Identity incomplete; cache disabled." if not cache_eligible else ""
                )
                payload: dict[str, Any] = {
                    "schema_version": 1,
                    "test": {
                        "id": attempt_id,
                        "kind": kind,
                        "state": "prepared",
                        "case": canonical_case,
                        "profile": selected_profile,
                        "source_commit": selected_source_commit,
                        "executable_hash": selected_executable_hash,
                        "input_hash": input_hash,
                        "adapter": selected_adapter,
                        "adapter_version": selected_adapter_version,
                        "cache_key": cache_key,
                        "created_at": timestamp.isoformat(),
                        "updated_at": timestamp.isoformat(),
                        "started_at": "",
                        "finished_at": "",
                        "observation": observation,
                        "cached_from": "",
                    },
                }
                path = _commit_prepared_attempt(
                    test_root,
                    attempt_id,
                    rendered_input=rendered_input,
                    expected_input_hash=input_hash,
                    payload=payload,
                )
                attempt = load_test_attempt(path)
    except TestAttemptWorkflowError:
        raise
    except (OSError, RuntimeError, TypeError, ValueError, TestAttemptError) as exc:
        raise TestAttemptWorkflowError(str(exc)) from exc
    return PreparedTestAttempt(attempt=attempt, path=path, cached=False)


def list_test_attempts(project_root: Path) -> list[TestAttemptData]:
    """List TestAttempts without consulting or mutating the normal Run tree."""
    root = project_root.resolve()
    try:
        test_root = _ensure_test_root(root, create=False)
        if test_root is None:
            return []
        return discover_test_attempts(test_root)
    except (OSError, TestAttemptError) as exc:
        raise TestAttemptWorkflowError(str(exc)) from exc


def record_test_result(
    project_root: Path,
    attempt_id: str,
    *,
    result: str,
    observation: str = "",
    now: datetime | None = None,
) -> TestAttemptData:
    """Record one terminal result on a prepared/submitted TestAttempt."""
    if result not in TEST_ATTEMPT_TERMINAL_STATES:
        raise TestAttemptWorkflowError(
            "TestAttempt result must be passed, failed, or skipped"
        )
    timestamp = _aware_now(now)
    root = project_root.resolve()
    try:
        with _test_attempt_lock(root):
            test_root = _ensure_test_root(root, create=False)
            if test_root is None:
                raise TestAttemptWorkflowError("No TestAttempts have been prepared")
            attempt = _load_attempt_by_id(test_root, attempt_id)
            if attempt.state in TEST_ATTEMPT_TERMINAL_STATES:
                raise TestAttemptWorkflowError(
                    f"TestAttempt {attempt.id} is already terminal ({attempt.state})"
                )
            if attempt.state not in {"prepared", "submitted"}:
                raise TestAttemptWorkflowError(
                    f"TestAttempt {attempt.id} cannot record a result from "
                    f"state {attempt.state}"
                )
            _assert_attempt_input_integrity(attempt)
            payload = copy.deepcopy(attempt.raw)
            section = payload.get("test")
            if not isinstance(section, dict):
                raise TestAttemptWorkflowError(
                    f"TestAttempt {attempt.id} has no valid [test] table"
                )
            section["state"] = result
            section["updated_at"] = timestamp.isoformat()
            section["finished_at"] = timestamp.isoformat()
            section["observation"] = observation
            return write_test_attempt(attempt.attempt_dir, payload)
    except (OSError, TestAttemptError) as exc:
        raise TestAttemptWorkflowError(str(exc)) from exc


def clean_test_attempts(
    project_root: Path,
    *,
    older_than_days: int,
    now: datetime | None = None,
) -> TestAttemptCleanResult:
    """Delete only old terminal attempts after a no-mutation safety preflight."""
    if isinstance(older_than_days, bool) or older_than_days < 0:
        raise TestAttemptWorkflowError("older_than_days must be non-negative")
    timestamp = _aware_now(now)
    cutoff = timestamp - timedelta(days=older_than_days)
    root = project_root.resolve()

    try:
        with _test_attempt_lock(root):
            test_root = _ensure_test_root(root, create=False)
            if test_root is None:
                return TestAttemptCleanResult(removed_ids=())
            resumed_ids = _resume_pending_cleanup(test_root)
            attempts = discover_test_attempts(test_root)
            old_attempts = [
                attempt
                for attempt in attempts
                if _attempt_age_timestamp(attempt) <= cutoff
            ]
            active = [
                attempt
                for attempt in old_attempts
                if attempt.state not in TEST_ATTEMPT_TERMINAL_STATES
            ]
            if active:
                details = ", ".join(
                    f"{attempt.id} ({attempt.state})" for attempt in active
                )
                raise TestAttemptWorkflowError(
                    "Refusing TestAttempt cleanup because old active attempts "
                    f"exist: {details}"
                )

            candidates = [
                attempt
                for attempt in old_attempts
                if attempt.state in TEST_ATTEMPT_TERMINAL_STATES
            ]
            cleanup_entries = tuple(
                _capture_cleanup_entry(test_root, attempt) for attempt in candidates
            )

            candidate_ids = tuple(attempt.id for attempt in candidates)
            if not candidates:
                return TestAttemptCleanResult(removed_ids=resumed_ids)
            cleanup_receipt = test_root / _CLEANUP_RECEIPT_FILE
            _write_cleanup_receipt(
                cleanup_receipt,
                phase="staging",
                entries=cleanup_entries,
                create=True,
            )
            entries_by_id = {entry.attempt_id: entry for entry in cleanup_entries}
            tombstones: list[tuple[TestAttemptData, Path]] = []
            try:
                for attempt in candidates:
                    entry = entries_by_id[attempt.id]
                    _validate_cleanup_location(
                        test_root,
                        attempt.attempt_dir,
                        entry,
                    )
                    tombstone = test_root / f".delete-{attempt.id}"
                    if tombstone.exists() or tombstone.is_symlink():
                        raise TestAttemptWorkflowError(
                            f"Cleanup tombstone already exists: {tombstone}"
                        )
                    commit_staged_directory(attempt.attempt_dir, tombstone)
                    _validate_cleanup_location(test_root, tombstone, entry)
                    tombstones.append((attempt, tombstone))
            except (OSError, SimctlError) as exc:
                rollback_errors = _rollback_cleanup_staging(
                    test_root,
                    candidates,
                    entries=entries_by_id,
                    staged_ids={attempt.id for attempt, _path in tombstones},
                )
                if not rollback_errors:
                    _remove_cleanup_receipt(cleanup_receipt)
                detail = (
                    f"; rollback failures: {'; '.join(rollback_errors)}"
                    if rollback_errors
                    else ""
                )
                if isinstance(exc, FileExistsError):
                    message = f"Cleanup tombstone was claimed concurrently: {tombstone}"
                else:
                    message = f"Failed to stage TestAttempt cleanup: {exc}"
                raise TestAttemptWorkflowError(message + detail) from exc

            _write_cleanup_receipt(
                cleanup_receipt,
                phase="deleting",
                entries=cleanup_entries,
                create=False,
            )
            try:
                for attempt, tombstone in tombstones:
                    _validate_cleanup_deletion_target(
                        test_root,
                        tombstone,
                        entries_by_id[attempt.id],
                    )
                    shutil.rmtree(tombstone)
                    _fsync_directory(test_root)
            except (OSError, SimctlError) as exc:
                raise TestAttemptWorkflowError(
                    "TestAttempt cleanup deletion failed; the pending cleanup "
                    f"receipt was preserved at {cleanup_receipt}. "
                    f"rerun the same `runo test clean` command to finish: {exc}"
                ) from exc
            _assert_cleanup_paths_absent(test_root, cleanup_entries)
            _remove_cleanup_receipt(cleanup_receipt)
            return TestAttemptCleanResult(removed_ids=resumed_ids + candidate_ids)
    except TestAttemptWorkflowError:
        raise
    except (OSError, TestAttemptError) as exc:
        raise TestAttemptWorkflowError(str(exc)) from exc


def _write_cleanup_receipt(
    path: Path,
    *,
    phase: str,
    entries: tuple[_CleanupEntry, ...],
    create: bool,
) -> None:
    unsigned_payload: dict[str, Any] = {
        "schema_version": 2,
        "phase": phase,
        "attempts": [
            {
                "attempt_id": entry.attempt_id,
                "directory_device": entry.directory_device,
                "directory_inode": entry.directory_inode,
                "tree_digest": entry.tree_digest,
                "test_receipt_digest": entry.test_receipt_digest,
                "input_hash": entry.input_hash,
                "tree_entries": dict(entry.tree_entries),
            }
            for entry in entries
        ],
    }
    payload = dict(unsigned_payload)
    payload["receipt_sha256"] = _canonical_json_digest(unsigned_payload)
    encoded = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    descriptor, temporary = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        if create:
            os.link(temporary, path, follow_symlinks=False)
            os.unlink(temporary)
            temporary = ""
        else:
            _require_safe_cleanup_receipt(path)
            os.replace(temporary, path)
            temporary = ""
        _fsync_directory(path.parent)
    except (OSError, TypeError, ValueError) as exc:
        raise TestAttemptWorkflowError(
            f"Failed to persist pending TestAttempt cleanup receipt {path}: {exc}"
        ) from exc
    finally:
        if temporary:
            with contextlib.suppress(OSError):
                os.unlink(temporary)


def _read_cleanup_receipt(path: Path) -> tuple[str, tuple[_CleanupEntry, ...]]:
    metadata = _require_safe_cleanup_receipt(path)
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
            raise TestAttemptWorkflowError(
                f"Pending cleanup receipt changed while opening: {path}"
            )
        with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
            descriptor = -1
            payload = json.load(stream)
            after = os.fstat(stream.fileno())
        current = os.stat(path, follow_symlinks=False)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TestAttemptWorkflowError(
            f"Failed to read pending TestAttempt cleanup receipt {path}: {exc}"
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
        raise TestAttemptWorkflowError(
            f"Pending cleanup receipt changed while being read: {path}"
        )
    if (
        not isinstance(payload, dict)
        or type(payload.get("schema_version")) is not int
        or payload.get("schema_version") != 2
    ):
        raise TestAttemptWorkflowError(
            f"Unsupported pending TestAttempt cleanup receipt schema in {path}"
        )
    phase = payload.get("phase")
    raw_entries = payload.get("attempts")
    if not isinstance(phase, str) or phase not in {"staging", "deleting"}:
        raise TestAttemptWorkflowError(
            f"Invalid pending TestAttempt cleanup phase in {path}: {phase!r}"
        )
    if not isinstance(raw_entries, list) or not raw_entries:
        raise TestAttemptWorkflowError(
            f"Pending TestAttempt cleanup receipt has no attempt entries: {path}"
        )
    receipt_sha256 = payload.get("receipt_sha256")
    unsigned_payload = dict(payload)
    unsigned_payload.pop("receipt_sha256", None)
    if not isinstance(receipt_sha256, str) or receipt_sha256 != _canonical_json_digest(
        unsigned_payload
    ):
        raise TestAttemptWorkflowError(
            f"Pending TestAttempt cleanup receipt integrity mismatch: {path}"
        )

    entries: list[_CleanupEntry] = []
    seen_ids: set[str] = set()
    required_keys = {
        "attempt_id",
        "directory_device",
        "directory_inode",
        "tree_digest",
        "test_receipt_digest",
        "input_hash",
        "tree_entries",
    }
    for value in raw_entries:
        if not isinstance(value, dict) or set(value) != required_keys:
            raise TestAttemptWorkflowError(
                "Invalid TestAttempt entry in pending cleanup receipt "
                f"{path}: {value!r}"
            )
        attempt_id = value.get("attempt_id")
        if not isinstance(attempt_id, str) or not _is_test_attempt_id(attempt_id):
            raise TestAttemptWorkflowError(
                f"Invalid TestAttempt ID in pending cleanup receipt {path}: {value!r}"
            )
        if attempt_id in seen_ids:
            raise TestAttemptWorkflowError(
                "Duplicate TestAttempt ID in pending cleanup receipt "
                f"{path}: {attempt_id}"
            )
        directory_device = value.get("directory_device")
        directory_inode = value.get("directory_inode")
        if (
            type(directory_device) is not int
            or directory_device < 0
            or type(directory_inode) is not int
            or directory_inode <= 0
        ):
            raise TestAttemptWorkflowError(
                f"Invalid directory identity for {attempt_id} in {path}"
            )
        digests = {
            key: value.get(key)
            for key in ("tree_digest", "test_receipt_digest", "input_hash")
        }
        if any(
            not isinstance(digest, str) or not _is_sha256_digest(digest)
            for digest in digests.values()
        ):
            raise TestAttemptWorkflowError(
                f"Invalid integrity digest for {attempt_id} in {path}"
            )
        tree_entries = value.get("tree_entries")
        if (
            not isinstance(tree_entries, dict)
            or not tree_entries
            or any(
                not isinstance(relative, str)
                or not _is_safe_cleanup_relative_path(relative)
                or not isinstance(digest, str)
                or not _is_sha256_digest(digest)
                for relative, digest in tree_entries.items()
            )
        ):
            raise TestAttemptWorkflowError(
                f"Invalid tree entry fingerprints for {attempt_id} in {path}"
            )
        seen_ids.add(attempt_id)
        entries.append(
            _CleanupEntry(
                attempt_id=attempt_id,
                directory_device=directory_device,
                directory_inode=directory_inode,
                tree_digest=str(digests["tree_digest"]),
                test_receipt_digest=str(digests["test_receipt_digest"]),
                input_hash=str(digests["input_hash"]),
                tree_entries={
                    str(relative): str(digest)
                    for relative, digest in tree_entries.items()
                },
            )
        )
    return phase, tuple(entries)


def _remove_cleanup_receipt(path: Path) -> None:
    _require_safe_cleanup_receipt(path)
    try:
        path.unlink()
        _fsync_directory(path.parent)
    except OSError as exc:
        raise TestAttemptWorkflowError(
            f"Failed to remove pending TestAttempt cleanup receipt {path}: {exc}"
        ) from exc


def _require_safe_cleanup_receipt(path: Path) -> os.stat_result:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise TestAttemptWorkflowError(
            f"Pending cleanup receipt is not a safe regular file: {path}: {exc}"
        ) from exc
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise TestAttemptWorkflowError(
            f"Pending cleanup receipt is not a safe single-link regular file: {path}"
        )
    return metadata


def _rollback_cleanup_staging(
    test_root: Path,
    candidates: list[TestAttemptData],
    *,
    entries: dict[str, _CleanupEntry],
    staged_ids: set[str],
) -> list[str]:
    errors: list[str] = []
    for attempt in reversed(candidates):
        original = attempt.attempt_dir
        tombstone = test_root / f".delete-{attempt.id}"
        original_exists = os.path.lexists(original)
        tombstone_exists = os.path.lexists(tombstone)
        if original_exists and tombstone_exists:
            if attempt.id in staged_ids:
                errors.append(f"{attempt.id}: original and tombstone both exist")
            continue
        if original_exists:
            try:
                _validate_cleanup_location(test_root, original, entries[attempt.id])
            except (OSError, SimctlError) as exc:
                errors.append(f"{attempt.id}: {exc}")
            continue
        if not tombstone_exists:
            errors.append(f"{attempt.id}: both original and tombstone are missing")
            continue
        try:
            _validate_cleanup_location(
                test_root,
                tombstone,
                entries[attempt.id],
            )
            commit_staged_directory(tombstone, original)
            _validate_cleanup_location(
                test_root,
                original,
                entries[attempt.id],
            )
        except (OSError, SimctlError) as exc:
            errors.append(f"{attempt.id}: {exc}")
    return errors


def _resume_pending_cleanup(test_root: Path) -> tuple[str, ...]:
    receipt = test_root / _CLEANUP_RECEIPT_FILE
    if not os.path.lexists(receipt):
        return ()
    phase, entries = _read_cleanup_receipt(receipt)
    if phase == "staging":
        errors: list[str] = []
        for entry in reversed(entries):
            attempt_id = entry.attempt_id
            original = test_root / attempt_id
            tombstone = test_root / f".delete-{attempt_id}"
            original_exists = os.path.lexists(original)
            tombstone_exists = os.path.lexists(tombstone)
            if original_exists and tombstone_exists:
                errors.append(f"{attempt_id}: original and tombstone both exist")
                continue
            if original_exists:
                try:
                    _validate_cleanup_location(test_root, original, entry)
                except (OSError, SimctlError) as exc:
                    errors.append(f"{attempt_id}: {exc}")
                continue
            if not tombstone_exists:
                errors.append(f"{attempt_id}: both original and tombstone are missing")
                continue
            try:
                _validate_cleanup_location(test_root, tombstone, entry)
                commit_staged_directory(tombstone, original)
                _validate_cleanup_location(test_root, original, entry)
            except (OSError, SimctlError) as exc:
                errors.append(f"{attempt_id}: {exc}")
        if errors:
            raise TestAttemptWorkflowError(
                "Failed to resume TestAttempt cleanup staging rollback; "
                f"pending receipt preserved at {receipt}: {'; '.join(errors)}"
            )
        _remove_cleanup_receipt(receipt)
        return ()

    for entry in entries:
        attempt_id = entry.attempt_id
        original = test_root / attempt_id
        tombstone = test_root / f".delete-{attempt_id}"
        if os.path.lexists(original):
            raise TestAttemptWorkflowError(
                "Cannot resume TestAttempt cleanup because the original and pending "
                f"transaction conflict for {attempt_id}: {original}"
            )
        if not os.path.lexists(tombstone):
            continue
        try:
            _validate_cleanup_deletion_remainder(test_root, tombstone, entry)
            shutil.rmtree(tombstone)
            _fsync_directory(test_root)
        except (OSError, SimctlError) as exc:
            raise TestAttemptWorkflowError(
                "Pending TestAttempt cleanup deletion failed again; "
                f"receipt remains at {receipt}. rerun `runo test clean`: {exc}"
            ) from exc
    _assert_cleanup_paths_absent(test_root, entries)
    _remove_cleanup_receipt(receipt)
    return tuple(entry.attempt_id for entry in entries)


def _assert_attempt_input_integrity(attempt: TestAttemptData) -> None:
    actual_hash = _hash_input_root(attempt.attempt_dir / "input")
    if actual_hash != attempt.input_hash:
        raise TestAttemptWorkflowError(
            f"TestAttempt {attempt.id} input snapshot integrity mismatch: "
            f"receipt records {attempt.input_hash}, actual input is {actual_hash}"
        )


def _capture_cleanup_entry(
    test_root: Path,
    attempt: TestAttemptData,
) -> _CleanupEntry:
    _assert_attempt_input_integrity(attempt)
    snapshot = _snapshot_cleanup_tree(test_root, attempt.attempt_dir)
    if snapshot.input_hash != attempt.input_hash:
        raise TestAttemptWorkflowError(
            f"TestAttempt {attempt.id} input snapshot integrity mismatch during "
            "cleanup preflight"
        )
    return _CleanupEntry(
        attempt_id=attempt.id,
        directory_device=snapshot.directory_device,
        directory_inode=snapshot.directory_inode,
        tree_digest=snapshot.tree_digest,
        test_receipt_digest=snapshot.test_receipt_digest,
        input_hash=snapshot.input_hash,
        tree_entries=dict(snapshot.tree_entries),
    )


def _validate_cleanup_location(
    test_root: Path,
    directory: Path,
    entry: _CleanupEntry,
) -> None:
    snapshot = _snapshot_cleanup_tree(test_root, directory)
    if (
        snapshot.directory_device,
        snapshot.directory_inode,
    ) != (entry.directory_device, entry.directory_inode):
        raise TestAttemptWorkflowError(
            f"TestAttempt {entry.attempt_id} cleanup directory identity mismatch "
            f"at {directory}"
        )
    if snapshot.input_hash != entry.input_hash:
        raise TestAttemptWorkflowError(
            f"TestAttempt {entry.attempt_id} cleanup input snapshot integrity "
            f"mismatch at {directory}"
        )
    if snapshot.test_receipt_digest != entry.test_receipt_digest:
        raise TestAttemptWorkflowError(
            f"TestAttempt {entry.attempt_id} cleanup test receipt integrity "
            f"mismatch at {directory}"
        )
    if snapshot.tree_digest != entry.tree_digest:
        raise TestAttemptWorkflowError(
            f"TestAttempt {entry.attempt_id} cleanup tree digest mismatch at "
            f"{directory}"
        )


def _validate_cleanup_deletion_target(
    test_root: Path,
    tombstone: Path,
    entry: _CleanupEntry,
) -> None:
    original = test_root / entry.attempt_id
    if os.path.lexists(original):
        raise TestAttemptWorkflowError(
            "Cannot delete pending TestAttempt cleanup tombstone while the original "
            f"path exists for {entry.attempt_id}: {original}"
        )
    _validate_cleanup_location(test_root, tombstone, entry)
    current = tombstone.stat(follow_symlinks=False)
    if (current.st_dev, current.st_ino) != (
        entry.directory_device,
        entry.directory_inode,
    ):
        raise TestAttemptWorkflowError(
            f"TestAttempt {entry.attempt_id} cleanup directory identity changed "
            f"immediately before deletion: {tombstone}"
        )


def _validate_cleanup_deletion_remainder(
    test_root: Path,
    tombstone: Path,
    entry: _CleanupEntry,
) -> None:
    """Accept only unchanged survivors of a receipt-owned partial deletion."""
    original = test_root / entry.attempt_id
    if os.path.lexists(original):
        raise TestAttemptWorkflowError(
            "Cannot delete pending TestAttempt cleanup tombstone while the original "
            f"path exists for {entry.attempt_id}: {original}"
        )
    actual_device, actual_inode, survivors = _snapshot_cleanup_remainder(
        test_root,
        tombstone,
    )
    if (actual_device, actual_inode) != (
        entry.directory_device,
        entry.directory_inode,
    ):
        raise TestAttemptWorkflowError(
            f"TestAttempt {entry.attempt_id} cleanup directory identity mismatch "
            f"at {tombstone}"
        )
    for relative, actual_digest in survivors.items():
        expected_digest = entry.tree_entries.get(relative)
        if expected_digest is None:
            raise TestAttemptWorkflowError(
                f"TestAttempt {entry.attempt_id} cleanup tree digest has an "
                f"unexpected surviving entry at {tombstone / relative}"
            )
        if actual_digest == expected_digest:
            continue
        if relative == TEST_RECEIPT_FILE:
            detail = "test receipt integrity"
        elif relative == "input" or relative.startswith("input/"):
            detail = "input snapshot integrity"
        else:
            detail = "tree digest"
        raise TestAttemptWorkflowError(
            f"TestAttempt {entry.attempt_id} cleanup {detail} mismatch at "
            f"{tombstone / relative}"
        )


def _assert_cleanup_paths_absent(
    test_root: Path,
    entries: tuple[_CleanupEntry, ...],
) -> None:
    conflicts: list[str] = []
    for entry in entries:
        original = test_root / entry.attempt_id
        tombstone = test_root / f".delete-{entry.attempt_id}"
        if os.path.lexists(original):
            conflicts.append(str(original))
        if os.path.lexists(tombstone):
            conflicts.append(str(tombstone))
    if conflicts:
        raise TestAttemptWorkflowError(
            "TestAttempt cleanup paths reappeared before receipt cleanup: "
            + ", ".join(conflicts)
        )


def _snapshot_cleanup_tree(
    test_root: Path,
    directory: Path,
) -> _CleanupTreeSnapshot:
    _assert_safe_attempt_tree(test_root, directory)
    root_before = directory.stat(follow_symlinks=False)
    input_root = directory / "input"
    if input_root.is_symlink() or not input_root.is_dir():
        raise TestAttemptWorkflowError(
            f"TestAttempt cleanup input snapshot must be a directory: {input_root}"
        )

    try:
        paths_before = sorted(directory.rglob("*"), key=lambda path: path.as_posix())
    except OSError as exc:
        raise TestAttemptWorkflowError(
            f"Failed to enumerate TestAttempt cleanup tree {directory}: {exc}"
        ) from exc
    tree_digest = hashlib.sha256()
    input_digest = hashlib.sha256()
    receipt_digest = ""
    recorded_stats: dict[str, tuple[int, ...]] = {}
    tree_entries: dict[str, str] = {}

    for path in paths_before:
        relative = path.relative_to(directory).as_posix()
        try:
            metadata = path.stat(follow_symlinks=False)
        except OSError as exc:
            raise TestAttemptWorkflowError(
                f"Failed to inspect TestAttempt cleanup tree entry {path}: {exc}"
            ) from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise TestAttemptWorkflowError(
                f"Refusing cleanup containing symbolic link: {path}"
            )
        if metadata.st_dev != root_before.st_dev:
            raise TestAttemptWorkflowError(
                f"Refusing cleanup across a filesystem boundary: {path}"
            )
        if stat.S_ISDIR(metadata.st_mode):
            kind = "directory"
            content = b""
        elif stat.S_ISREG(metadata.st_mode):
            kind = "file"
            metadata, content = _read_stable_regular_file(path, metadata)
        else:
            raise TestAttemptWorkflowError(
                f"Refusing unsupported TestAttempt cleanup tree entry: {path}"
            )
        stat_identity = _cleanup_stat_identity(metadata)
        recorded_stats[relative] = stat_identity
        tree_entries[relative] = _cleanup_entry_fingerprint(
            relative,
            kind=kind,
            metadata=metadata,
            content=content,
        )
        record = json.dumps(
            {
                "path": relative,
                "kind": kind,
                "stat": stat_identity,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        tree_digest.update(len(record).to_bytes(8, byteorder="big"))
        tree_digest.update(record)
        tree_digest.update(len(content).to_bytes(8, byteorder="big"))
        tree_digest.update(content)

        if kind == "file" and relative.startswith("input/"):
            input_relative = relative.removeprefix("input/").encode("utf-8")
            input_digest.update(len(input_relative).to_bytes(8, byteorder="big"))
            input_digest.update(input_relative)
            input_digest.update(len(content).to_bytes(8, byteorder="big"))
            input_digest.update(content)
        if relative == TEST_RECEIPT_FILE:
            receipt_digest = _SHA256_PREFIX + hashlib.sha256(content).hexdigest()

    try:
        paths_after = sorted(directory.rglob("*"), key=lambda path: path.as_posix())
        root_after = directory.stat(follow_symlinks=False)
    except OSError as exc:
        raise TestAttemptWorkflowError(
            f"TestAttempt cleanup tree changed while being hashed: {directory}: {exc}"
        ) from exc
    relative_after = [path.relative_to(directory).as_posix() for path in paths_after]
    if relative_after != list(recorded_stats):
        raise TestAttemptWorkflowError(
            f"TestAttempt cleanup tree changed while being hashed: {directory}"
        )
    for path, relative in zip(paths_after, relative_after, strict=True):
        try:
            current = path.stat(follow_symlinks=False)
        except OSError as exc:
            raise TestAttemptWorkflowError(
                f"TestAttempt cleanup tree changed while being hashed: {path}: {exc}"
            ) from exc
        if _cleanup_stat_identity(current) != recorded_stats[relative]:
            raise TestAttemptWorkflowError(
                f"TestAttempt cleanup tree changed while being hashed: {path}"
            )
    if (
        root_after.st_dev,
        root_after.st_ino,
        stat.S_IFMT(root_after.st_mode),
        root_after.st_mtime_ns,
    ) != (
        root_before.st_dev,
        root_before.st_ino,
        stat.S_IFMT(root_before.st_mode),
        root_before.st_mtime_ns,
    ):
        raise TestAttemptWorkflowError(
            f"TestAttempt cleanup directory changed while being hashed: {directory}"
        )
    if not receipt_digest:
        raise TestAttemptWorkflowError(
            f"TestAttempt cleanup tree has no {TEST_RECEIPT_FILE}: {directory}"
        )
    return _CleanupTreeSnapshot(
        directory_device=root_before.st_dev,
        directory_inode=root_before.st_ino,
        tree_digest=_SHA256_PREFIX + tree_digest.hexdigest(),
        test_receipt_digest=receipt_digest,
        input_hash=_SHA256_PREFIX + input_digest.hexdigest(),
        tree_entries=tree_entries,
    )


def _snapshot_cleanup_remainder(
    test_root: Path,
    directory: Path,
) -> tuple[int, int, dict[str, str]]:
    """Fingerprint every survivor without requiring already-deleted entries."""
    _assert_safe_attempt_tree(test_root, directory)
    root_before = directory.stat(follow_symlinks=False)
    try:
        paths_before = sorted(directory.rglob("*"), key=lambda path: path.as_posix())
    except OSError as exc:
        raise TestAttemptWorkflowError(
            f"Failed to enumerate TestAttempt cleanup remainder {directory}: {exc}"
        ) from exc

    recorded_stats: dict[str, tuple[int, ...]] = {}
    survivors: dict[str, str] = {}
    for path in paths_before:
        relative = path.relative_to(directory).as_posix()
        try:
            metadata = path.stat(follow_symlinks=False)
        except OSError as exc:
            raise TestAttemptWorkflowError(
                f"Failed to inspect TestAttempt cleanup remainder {path}: {exc}"
            ) from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise TestAttemptWorkflowError(
                f"Refusing cleanup containing symbolic link: {path}"
            )
        if metadata.st_dev != root_before.st_dev:
            raise TestAttemptWorkflowError(
                f"Refusing cleanup across a filesystem boundary: {path}"
            )
        if stat.S_ISDIR(metadata.st_mode):
            kind = "directory"
            content = b""
        elif stat.S_ISREG(metadata.st_mode):
            kind = "file"
            metadata, content = _read_stable_regular_file(path, metadata)
        else:
            raise TestAttemptWorkflowError(
                f"Refusing unsupported TestAttempt cleanup tree entry: {path}"
            )
        recorded_stats[relative] = _cleanup_stat_identity(metadata)
        survivors[relative] = _cleanup_entry_fingerprint(
            relative,
            kind=kind,
            metadata=metadata,
            content=content,
        )

    try:
        paths_after = sorted(directory.rglob("*"), key=lambda path: path.as_posix())
        root_after = directory.stat(follow_symlinks=False)
    except OSError as exc:
        raise TestAttemptWorkflowError(
            f"TestAttempt cleanup remainder changed while being hashed: {exc}"
        ) from exc
    relative_after = [path.relative_to(directory).as_posix() for path in paths_after]
    if relative_after != list(recorded_stats):
        raise TestAttemptWorkflowError(
            f"TestAttempt cleanup remainder changed while being hashed: {directory}"
        )
    for path, relative in zip(paths_after, relative_after, strict=True):
        try:
            current = path.stat(follow_symlinks=False)
        except OSError as exc:
            raise TestAttemptWorkflowError(
                f"TestAttempt cleanup remainder changed while being hashed: {path}"
            ) from exc
        if _cleanup_stat_identity(current) != recorded_stats[relative]:
            raise TestAttemptWorkflowError(
                f"TestAttempt cleanup remainder changed while being hashed: {path}"
            )
    if (
        root_after.st_dev,
        root_after.st_ino,
        stat.S_IFMT(root_after.st_mode),
        root_after.st_mtime_ns,
    ) != (
        root_before.st_dev,
        root_before.st_ino,
        stat.S_IFMT(root_before.st_mode),
        root_before.st_mtime_ns,
    ):
        raise TestAttemptWorkflowError(
            f"TestAttempt cleanup remainder changed while being hashed: {directory}"
        )
    return root_before.st_dev, root_before.st_ino, survivors


def _cleanup_entry_fingerprint(
    relative: str,
    *,
    kind: str,
    metadata: os.stat_result,
    content: bytes,
) -> str:
    """Fingerprint immutable survivor attributes; omit deletion-mutated dir times."""
    record = json.dumps(
        {
            "path": relative,
            "kind": kind,
            "device": metadata.st_dev,
            "inode": metadata.st_ino,
            "mode": metadata.st_mode,
            "size": len(content) if kind == "file" else None,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256()
    digest.update(len(record).to_bytes(8, byteorder="big"))
    digest.update(record)
    digest.update(len(content).to_bytes(8, byteorder="big"))
    digest.update(content)
    return _SHA256_PREFIX + digest.hexdigest()


def _read_stable_regular_file(
    path: Path,
    expected: os.stat_result,
) -> tuple[os.stat_result, bytes]:
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
    descriptor = -1
    try:
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if _cleanup_stat_identity(opened) != _cleanup_stat_identity(expected):
            raise TestAttemptWorkflowError(
                f"TestAttempt cleanup file changed while opening: {path}"
            )
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
        current = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise TestAttemptWorkflowError(
            f"Failed to safely hash TestAttempt cleanup file {path}: {exc}"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    identity = _cleanup_stat_identity(opened)
    if (
        _cleanup_stat_identity(after) != identity
        or _cleanup_stat_identity(current) != identity
    ):
        raise TestAttemptWorkflowError(
            f"TestAttempt cleanup file changed while being hashed: {path}"
        )
    return opened, b"".join(chunks)


def _cleanup_stat_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _canonical_json_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _SHA256_PREFIX + hashlib.sha256(encoded).hexdigest()


def _is_sha256_digest(value: str) -> bool:
    return (
        len(value) == len(_SHA256_PREFIX) + 64
        and value.startswith(_SHA256_PREFIX)
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def _is_safe_cleanup_relative_path(value: str) -> bool:
    parts = value.split("/")
    return bool(
        value
        and not value.startswith("/")
        and "\\" not in value
        and all(part not in {"", ".", ".."} for part in parts)
    )


def _is_test_attempt_id(value: str) -> bool:
    return (
        len(value) == 14
        and value.startswith("T")
        and value[1:9].isdigit()
        and value[9] == "-"
        and value[10:].isdigit()
    )


def _find_cached_pass(
    attempts: list[TestAttemptData],
    cache_key: str,
    *,
    cache_ttl: timedelta,
    now: datetime,
) -> tuple[TestAttemptData, timedelta] | None:
    if cache_ttl <= timedelta(0):
        return None
    matches: list[tuple[datetime, TestAttemptData, timedelta]] = []
    for attempt in attempts:
        if attempt.state != "passed" or attempt.cache_key != cache_key:
            continue
        _assert_attempt_input_integrity(attempt)
        completed = parse_test_timestamp(attempt.finished_at or attempt.updated_at)
        age = now - completed.astimezone(now.tzinfo)
        if timedelta(0) <= age <= cache_ttl:
            matches.append((completed, attempt, age))
    if not matches:
        return None
    _completed, attempt, age = max(matches, key=lambda item: item[0])
    return attempt, age


def _commit_prepared_attempt(
    test_root: Path,
    attempt_id: str,
    *,
    rendered_input: Path,
    expected_input_hash: str,
    payload: dict[str, Any],
) -> Path:
    final = test_root / attempt_id
    if final.exists() or final.is_symlink():
        raise TestAttemptWorkflowError(f"TestAttempt ID already exists: {attempt_id}")

    staging_parent = Path(
        tempfile.mkdtemp(prefix=f".tmp-{attempt_id}-", dir=str(test_root))
    )
    staging_attempt = staging_parent / attempt_id
    committed = False
    try:
        staging_attempt.mkdir()
        for name in ("input", "work", "status"):
            (staging_attempt / name).mkdir()
        _copy_input_snapshot(rendered_input, staging_attempt / "input")
        actual_hash = _hash_input_root(staging_attempt / "input")
        if actual_hash != expected_input_hash:
            raise TestAttemptWorkflowError(
                "case/input changed while the TestAttempt snapshot was prepared"
            )
        write_test_attempt(staging_attempt, payload)
        try:
            move_directory_noreplace(staging_attempt, final)
        except FileExistsError as exc:
            raise TestAttemptWorkflowError(
                f"TestAttempt ID already exists: {attempt_id}"
            ) from exc
        committed = True
        return final
    finally:
        if not committed and staging_attempt.exists():
            shutil.rmtree(staging_attempt, ignore_errors=True)
        with contextlib.suppress(OSError):
            staging_parent.rmdir()


@contextmanager
def _rendered_input_snapshot(
    project_root: Path,
    case_data: CaseData,
    adapter: SimulatorAdapter,
) -> Iterator[Path]:
    """Render the same adapter inputs as a formal Run into an ephemeral tree."""
    state_dir = _ensure_state_dir(project_root, create=True)
    assert state_dir is not None
    cache_root = _ensure_cache_root(project_root, state_dir)
    with tempfile.TemporaryDirectory(prefix=".test-render-", dir=cache_root) as raw:
        render_root = Path(raw)
        copy_case_files(case_data.case_dir, render_root / "input")
        case_section = {
            **case_data.raw.get("case", {}),
            "case_dir": str(case_data.case_dir),
        }
        validation_data = {"case": case_section, "params": dict(case_data.params)}
        issues = adapter.validate_params(validation_data)
        errors = [issue for issue in issues if issue.severity == "error"]
        if errors:
            raise ParameterValidationError(issues)
        adapter.render_inputs(validation_data, render_root)
        input_root = render_root / "input"
        input_root.mkdir(exist_ok=True)
        yield input_root


def _ensure_cache_root(project_root: Path, state_dir: Path) -> Path:
    cache_root = state_dir / "cache"
    if cache_root.is_symlink():
        raise TestAttemptWorkflowError(
            f"TestAttempt cache root must not be a symbolic link: {cache_root}"
        )
    if not cache_root.exists():
        try:
            cache_root.mkdir(mode=0o700)
            _fsync_directory(state_dir)
        except OSError as exc:
            raise TestAttemptWorkflowError(
                f"Failed to create TestAttempt cache root {cache_root}: {exc}"
            ) from exc
    if not cache_root.is_dir():
        raise TestAttemptWorkflowError(
            f"TestAttempt cache root must be a directory: {cache_root}"
        )
    _assert_within(project_root.resolve(), cache_root)
    return cache_root


def _adapter_implementation_hash(adapter: SimulatorAdapter) -> str:
    """Hash adapter source so cache reuse changes when its renderer changes."""
    try:
        source = inspect.getsource(type(adapter)).encode("utf-8")
    except (OSError, TypeError):
        return ""
    return _SHA256_PREFIX + hashlib.sha256(source).hexdigest()


def _hash_input_root(input_root: Path) -> str:
    digest = hashlib.sha256()
    for path in _safe_input_files(input_root):
        relative = path.relative_to(input_root).as_posix().encode("utf-8")
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise TestAttemptWorkflowError(
                f"Failed to read case input file {path}: {exc}"
            ) from exc
        digest.update(len(relative).to_bytes(8, byteorder="big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, byteorder="big"))
        digest.update(content)
    return _SHA256_PREFIX + digest.hexdigest()


def _safe_input_files(input_root: Path) -> list[Path]:
    if input_root.is_symlink():
        raise TestAttemptWorkflowError(
            f"case/input must not be a symbolic link: {input_root}"
        )
    if not input_root.exists():
        return []
    if not input_root.is_dir():
        raise TestAttemptWorkflowError(f"case/input must be a directory: {input_root}")
    files: list[Path] = []
    try:
        paths = sorted(input_root.rglob("*"), key=lambda path: path.as_posix())
    except OSError as exc:
        raise TestAttemptWorkflowError(
            f"Failed to inspect case/input {input_root}: {exc}"
        ) from exc
    for path in paths:
        if path.is_symlink():
            raise TestAttemptWorkflowError(
                f"case/input must not contain symbolic links: {path}"
            )
        if path.is_dir():
            continue
        if not path.is_file():
            raise TestAttemptWorkflowError(
                f"case/input must contain only regular files: {path}"
            )
        files.append(path)
    return files


def _copy_input_snapshot(source_root: Path, destination_root: Path) -> None:
    for source in _safe_input_files(source_root):
        relative = source.relative_to(source_root)
        destination = destination_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(source, destination, follow_symlinks=False)
        except OSError as exc:
            raise TestAttemptWorkflowError(
                f"Failed to copy case input file {source}: {exc}"
            ) from exc


def _load_attempt_by_id(test_root: Path, attempt_id: str) -> TestAttemptData:
    if not attempt_id.startswith("T") or "/" in attempt_id or "\\" in attempt_id:
        raise TestAttemptWorkflowError(f"Invalid TestAttempt ID: {attempt_id!r}")
    path = test_root / attempt_id
    return load_test_attempt(path)


def _attempt_age_timestamp(attempt: TestAttemptData) -> datetime:
    value = attempt.finished_at or attempt.updated_at
    return parse_test_timestamp(value)


def _aware_now(value: datetime | None) -> datetime:
    selected = value or datetime.now(tz=timezone.utc)
    if selected.tzinfo is None or selected.utcoffset() is None:
        raise TestAttemptWorkflowError("TestAttempt clock must include a UTC offset")
    return selected


@contextmanager
def _test_attempt_lock(project_root: Path) -> Iterator[None]:
    state_dir = _ensure_state_dir(project_root, create=True)
    assert state_dir is not None
    lock_path = state_dir / _LOCK_FILE
    flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise TestAttemptWorkflowError(
            f"Failed to open TestAttempt lock {lock_path}: {exc}"
        ) from exc
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        except OSError as exc:
            raise TestAttemptWorkflowError(
                f"Failed to lock TestAttempt state {lock_path}: {exc}"
            ) from exc
        yield
    finally:
        with contextlib.suppress(OSError):
            os.close(descriptor)


def _reserve_test_id_locked(
    project_root: Path,
    now: datetime,
    existing: list[TestAttemptData],
) -> str:
    state_dir = _ensure_state_dir(project_root, create=True)
    assert state_dir is not None
    ledger_path = state_dir / _SEQUENCE_FILE
    ledger = _read_sequence_ledger(ledger_path)
    dates = ledger.setdefault("dates", {})
    if not isinstance(dates, dict):
        raise TestAttemptWorkflowError(
            f"Invalid [{_SEQUENCE_FILE}] dates table in {ledger_path}"
        )
    date_key = now.strftime("%Y%m%d")
    stored = dates.get(date_key, 0)
    if isinstance(stored, bool) or not isinstance(stored, int) or stored < 0:
        raise TestAttemptWorkflowError(
            f"Invalid TestAttempt sequence for {date_key!r} in {ledger_path}"
        )
    prefix = f"T{date_key}-"
    observed = 0
    for attempt in existing:
        if not attempt.id.startswith(prefix):
            continue
        try:
            observed = max(observed, int(attempt.id[len(prefix) :]))
        except ValueError:
            continue
    sequence = max(stored, observed) + 1
    if sequence > 9999:
        raise TestAttemptWorkflowError(
            f"TestAttempt sequence overflow for {date_key}: maximum 9999"
        )
    dates[date_key] = sequence
    _write_sequence_ledger(ledger_path, ledger)
    return f"T{date_key}-{sequence:04d}"


def _read_sequence_ledger(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise TestAttemptWorkflowError(
            f"TestAttempt sequence ledger must not be a symbolic link: {path}"
        )
    if not path.exists():
        return {"schema_version": 1, "dates": {}}
    if not path.is_file():
        raise TestAttemptWorkflowError(
            f"TestAttempt sequence ledger must be a regular file: {path}"
        )
    try:
        with path.open("rb") as stream:
            payload = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise TestAttemptWorkflowError(
            f"Failed to read TestAttempt sequence ledger {path}: {exc}"
        ) from exc
    version = payload.get("schema_version")
    if type(version) is not int or version != 1:
        raise TestAttemptWorkflowError(
            f"Unsupported TestAttempt sequence ledger schema in {path}"
        )
    return dict(payload)


def _write_sequence_ledger(path: Path, payload: dict[str, Any]) -> None:
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
        _fsync_directory(path.parent)
    except (OSError, TypeError) as exc:
        raise TestAttemptWorkflowError(
            f"Failed to persist TestAttempt sequence ledger {path}: {exc}"
        ) from exc
    finally:
        if temporary:
            with contextlib.suppress(OSError):
                os.unlink(temporary)


def _ensure_state_dir(project_root: Path, *, create: bool) -> Path | None:
    root = project_root.resolve()
    state_dir = root / ".runops"
    if state_dir.is_symlink():
        raise TestAttemptWorkflowError(
            f".runops must not be a symbolic link: {state_dir}"
        )
    if not state_dir.exists():
        if not create:
            return None
        state_dir.mkdir(mode=0o700)
        _fsync_directory(root)
    if not state_dir.is_dir():
        raise TestAttemptWorkflowError(f".runops must be a directory: {state_dir}")
    _assert_within(root, state_dir)
    return state_dir


def _ensure_test_root(project_root: Path, *, create: bool) -> Path | None:
    state_dir = _ensure_state_dir(project_root, create=create)
    if state_dir is None:
        return None
    test_root = state_dir / "test-runs"
    if test_root.is_symlink():
        raise TestAttemptWorkflowError(
            f"TestAttempt root must not be a symbolic link: {test_root}"
        )
    if not test_root.exists():
        if not create:
            return None
        test_root.mkdir(mode=0o700)
        _fsync_directory(state_dir)
    if not test_root.is_dir():
        raise TestAttemptWorkflowError(
            f"TestAttempt root must be a directory: {test_root}"
        )
    _assert_within(project_root.resolve(), test_root)
    return test_root


def _assert_safe_attempt_tree(test_root: Path, attempt_dir: Path) -> None:
    root = test_root.absolute()
    candidate = attempt_dir.absolute()
    if candidate.parent != root:
        raise TestAttemptWorkflowError(
            f"Refusing cleanup outside TestAttempt root: {candidate}"
        )
    if candidate.is_symlink():
        raise TestAttemptWorkflowError(
            f"Refusing cleanup of symbolic link: {candidate}"
        )
    _assert_within(root, candidate)
    root_device = candidate.stat(follow_symlinks=False).st_dev
    stack = [candidate]
    while stack:
        directory = stack.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError as exc:
            raise TestAttemptWorkflowError(
                f"Failed to inspect cleanup candidate {directory}: {exc}"
            ) from exc
        for entry in entries:
            path = Path(entry.path)
            if entry.is_symlink():
                raise TestAttemptWorkflowError(
                    f"Refusing cleanup containing symbolic link: {path}"
                )
            stat_result = entry.stat(follow_symlinks=False)
            if stat_result.st_dev != root_device:
                raise TestAttemptWorkflowError(
                    f"Refusing cleanup across a filesystem boundary: {path}"
                )
            _assert_within(root, path)
            if entry.is_dir(follow_symlinks=False):
                stack.append(path)


def _assert_within(root: Path, candidate: Path) -> None:
    try:
        candidate.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise TestAttemptWorkflowError(
            f"Path escapes its TestAttempt root: {candidate}"
        ) from exc


def _fsync_directory(directory: Path) -> None:
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open(directory, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "PreparedTestAttempt",
    "TestAttemptCleanResult",
    "TestAttemptWorkflowError",
    "clean_test_attempts",
    "hash_case_input",
    "list_test_attempts",
    "prepare_test_attempt",
    "record_test_result",
]
