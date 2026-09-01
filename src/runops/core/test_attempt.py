"""Typed receipt contract for smoke/debug attempts outside normal Runs.

TestAttempts deliberately use a separate ``T...`` identity namespace and live
under ``.runops/test-runs``.  A receipt is not a ``manifest.toml`` and cannot be
mistaken for scientific Run evidence by Run discovery.
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

import tomli_w

from runops.core.exceptions import SimctlError

TEST_RECEIPT_FILE = "test-receipt.toml"
TEST_ATTEMPT_KINDS = frozenset({"smoke", "debug"})
TEST_ATTEMPT_STATES = frozenset(
    {"prepared", "submitted", "passed", "failed", "skipped"}
)
TEST_ATTEMPT_TERMINAL_STATES = frozenset({"passed", "failed", "skipped"})

_ID_PATTERN = re.compile(r"^T\d{8}-\d{4}$")
_SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_REQUIRED_STRING_FIELDS = (
    "id",
    "kind",
    "state",
    "case",
    "profile",
    "source_commit",
    "executable_hash",
    "input_hash",
    "adapter",
    "adapter_version",
    "cache_key",
    "created_at",
    "updated_at",
    "started_at",
    "finished_at",
    "observation",
    "cached_from",
)


class TestAttemptError(SimctlError):
    """Raised when a TestAttempt receipt or path is unsafe or invalid."""


@dataclass(frozen=True)
class TestAttemptData:
    """Validated immutable view of ``test-receipt.toml``."""

    id: str
    kind: str
    state: str
    case: str
    profile: str
    source_commit: str
    executable_hash: str
    input_hash: str
    adapter: str
    adapter_version: str
    cache_key: str
    created_at: str
    updated_at: str
    started_at: str
    finished_at: str
    observation: str
    cached_from: str
    attempt_dir: Path
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


def load_test_attempt(attempt_dir: Path) -> TestAttemptData:
    """Load one receipt and reject symlinks, invalid TOML, and invalid fields."""
    directory = attempt_dir.absolute()
    if directory.is_symlink():
        raise TestAttemptError(
            f"TestAttempt directory must not be a symbolic link: {directory}"
        )
    if not directory.is_dir():
        raise TestAttemptError(f"TestAttempt directory not found: {directory}")

    receipt_path = directory / TEST_RECEIPT_FILE
    descriptor = _open_safe_receipt(receipt_path)
    try:
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            opened = os.fstat(stream.fileno())
            payload = tomllib.load(stream)
            after = os.fstat(stream.fileno())
        current = os.stat(receipt_path, follow_symlinks=False)
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise TestAttemptError(f"Failed to read {receipt_path}: {exc}") from exc
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
        raise TestAttemptError(
            f"TestAttempt receipt changed while being read: {receipt_path}"
        )
    return validate_test_attempt_payload(payload, directory)


def write_test_attempt(attempt_dir: Path, payload: dict[str, Any]) -> TestAttemptData:
    """Validate and atomically persist one TestAttempt receipt."""
    directory = attempt_dir.absolute()
    validated = validate_test_attempt_payload(payload, directory)

    if directory.is_symlink():
        raise TestAttemptError(
            f"TestAttempt directory must not be a symbolic link: {directory}"
        )
    if directory.exists() and not directory.is_dir():
        raise TestAttemptError(f"TestAttempt path must be a directory: {directory}")
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise TestAttemptError(
            f"Failed to create TestAttempt directory {directory}: {exc}"
        ) from exc

    receipt_path = directory / TEST_RECEIPT_FILE
    if os.path.lexists(receipt_path):
        existing = receipt_path.lstat()
        if not stat.S_ISREG(existing.st_mode) or existing.st_nlink != 1:
            raise TestAttemptError(
                "TestAttempt receipt must be a single-link regular file: "
                f"{receipt_path}"
            )

    descriptor = -1
    temporary = ""
    try:
        descriptor, temporary = tempfile.mkstemp(
            dir=str(directory),
            prefix=f".{TEST_RECEIPT_FILE}.",
            suffix=".tmp",
        )
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            tomli_w.dump(payload, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, receipt_path)
        temporary = ""
        _fsync_directory(directory)
    except (OSError, TypeError) as exc:
        raise TestAttemptError(f"Failed to write {receipt_path}: {exc}") from exc
    finally:
        if descriptor >= 0:
            with contextlib.suppress(OSError):
                os.close(descriptor)
        if temporary:
            with contextlib.suppress(OSError):
                os.unlink(temporary)
    return validated


def discover_test_attempts(test_root: Path) -> list[TestAttemptData]:
    """Discover direct child TestAttempts without traversing arbitrary paths."""
    root = test_root.absolute()
    if not root.exists():
        return []
    if root.is_symlink():
        raise TestAttemptError(f"TestAttempt root must not be a symbolic link: {root}")
    if not root.is_dir():
        raise TestAttemptError(f"TestAttempt root must be a directory: {root}")

    attempts: list[TestAttemptData] = []
    try:
        children = sorted(root.iterdir(), key=lambda path: path.name)
    except OSError as exc:
        raise TestAttemptError(f"Failed to inspect {root}: {exc}") from exc
    for child in children:
        if not _ID_PATTERN.fullmatch(child.name):
            continue
        if child.is_symlink():
            raise TestAttemptError(
                f"TestAttempt directory must not be a symbolic link: {child}"
            )
        attempts.append(load_test_attempt(child))
    return attempts


def validate_test_attempt_payload(
    payload: dict[str, Any],
    attempt_dir: Path,
) -> TestAttemptData:
    """Validate the stable receipt schema and return its typed view."""
    if not isinstance(payload, dict):
        raise TestAttemptError("TestAttempt receipt must be a TOML document")
    version = payload.get("schema_version")
    if type(version) is not int or version != 1:
        raise TestAttemptError(
            f"Unsupported TestAttempt schema_version {version!r}; expected 1"
        )
    section = payload.get("test")
    if not isinstance(section, dict):
        raise TestAttemptError("TestAttempt receipt requires a [test] table")

    strings: dict[str, str] = {}
    for key in _REQUIRED_STRING_FIELDS:
        value = section.get(key)
        if not isinstance(value, str):
            raise TestAttemptError(f"test.{key} must be a string")
        strings[key] = value

    attempt_id = strings["id"]
    if not _ID_PATTERN.fullmatch(attempt_id):
        raise TestAttemptError("test.id must match TYYYYMMDD-NNNN")
    if attempt_dir.name != attempt_id:
        raise TestAttemptError(
            f"test.id {attempt_id!r} does not match directory {attempt_dir.name!r}"
        )
    if strings["kind"] not in TEST_ATTEMPT_KINDS:
        raise TestAttemptError("test.kind must be smoke or debug")
    if strings["state"] not in TEST_ATTEMPT_STATES:
        raise TestAttemptError(
            "test.state must be prepared, submitted, passed, failed, or skipped"
        )
    for key in ("case", "profile", "adapter"):
        if not strings[key].strip():
            raise TestAttemptError(f"test.{key} must not be empty")

    _validate_optional_hash("executable_hash", strings["executable_hash"])
    _validate_required_hash("input_hash", strings["input_hash"])
    _validate_required_hash("cache_key", strings["cache_key"])
    expected_cache_key = build_test_attempt_cache_key(
        kind=strings["kind"],
        case=strings["case"],
        profile=strings["profile"],
        source_commit=strings["source_commit"],
        executable_hash=strings["executable_hash"],
        input_hash=strings["input_hash"],
        adapter=strings["adapter"],
        adapter_version=strings["adapter_version"],
    )
    if strings["cache_key"] != expected_cache_key:
        raise TestAttemptError(
            "test.cache_key does not match the canonical TestAttempt identity"
        )
    for key in ("created_at", "updated_at"):
        _validate_timestamp(key, strings[key], allow_empty=False)
    for key in ("started_at", "finished_at"):
        _validate_timestamp(key, strings[key], allow_empty=True)

    cached_from = strings["cached_from"]
    if cached_from and not _ID_PATTERN.fullmatch(cached_from):
        raise TestAttemptError("test.cached_from must be empty or a T ID")
    if strings["state"] in TEST_ATTEMPT_TERMINAL_STATES and not strings["finished_at"]:
        raise TestAttemptError("test.finished_at is required for a terminal state")

    return TestAttemptData(
        id=attempt_id,
        kind=strings["kind"],
        state=strings["state"],
        case=strings["case"],
        profile=strings["profile"],
        source_commit=strings["source_commit"],
        executable_hash=strings["executable_hash"],
        input_hash=strings["input_hash"],
        adapter=strings["adapter"],
        adapter_version=strings["adapter_version"],
        cache_key=strings["cache_key"],
        created_at=strings["created_at"],
        updated_at=strings["updated_at"],
        started_at=strings["started_at"],
        finished_at=strings["finished_at"],
        observation=strings["observation"],
        cached_from=cached_from,
        attempt_dir=attempt_dir.absolute(),
        raw=copy.deepcopy(payload),
    )


def parse_test_timestamp(value: str) -> datetime:
    """Parse one previously validated aware ISO-8601 receipt timestamp."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise TestAttemptError("TestAttempt timestamp must include a UTC offset")
    return parsed


def _open_safe_receipt(path: Path) -> int:
    """Open one immutable receipt identity without following path swaps."""
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise TestAttemptError(
            f"{TEST_RECEIPT_FILE} not found in {path.parent}"
        ) from exc
    except OSError as exc:
        raise TestAttemptError(f"Failed to inspect {path}: {exc}") from exc
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise TestAttemptError(
            f"TestAttempt receipt must be a single-link regular file: {path}"
        )
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
    descriptor = -1
    try:
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
    except OSError as exc:
        if descriptor >= 0:
            os.close(descriptor)
        raise TestAttemptError(f"Failed to safely open {path}: {exc}") from exc
    if (
        not stat.S_ISREG(opened.st_mode)
        or opened.st_nlink != 1
        or (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino)
    ):
        os.close(descriptor)
        raise TestAttemptError(f"TestAttempt receipt changed while opening: {path}")
    return descriptor


def build_test_attempt_cache_key(
    *,
    kind: str,
    case: str,
    profile: str,
    source_commit: str,
    executable_hash: str,
    input_hash: str,
    adapter: str,
    adapter_version: str,
) -> str:
    """Return the canonical cache identity recorded in every receipt."""
    identity = {
        "schema_version": 1,
        "kind": kind,
        "case": case,
        "profile": profile,
        "source_commit": source_commit,
        "executable_hash": executable_hash,
        "input_hash": input_hash,
        "adapter": adapter,
        "adapter_version": adapter_version,
    }
    encoded = json.dumps(
        identity,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _validate_optional_hash(key: str, value: str) -> None:
    if value:
        _validate_required_hash(key, value)


def _validate_required_hash(key: str, value: str) -> None:
    if not _SHA256_PATTERN.fullmatch(value):
        raise TestAttemptError(f"test.{key} must be a sha256:<64 lowercase hex> hash")


def _validate_timestamp(key: str, value: str, *, allow_empty: bool) -> None:
    if allow_empty and not value:
        return
    if not value:
        raise TestAttemptError(f"test.{key} must not be empty")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise TestAttemptError(f"test.{key} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise TestAttemptError(f"test.{key} must include a UTC offset")


def _fsync_directory(directory: Path) -> None:
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open(directory, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "TEST_ATTEMPT_KINDS",
    "TEST_ATTEMPT_STATES",
    "TEST_ATTEMPT_TERMINAL_STATES",
    "TEST_RECEIPT_FILE",
    "TestAttemptData",
    "TestAttemptError",
    "build_test_attempt_cache_key",
    "discover_test_attempts",
    "load_test_attempt",
    "parse_test_timestamp",
    "validate_test_attempt_payload",
    "write_test_attempt",
]
