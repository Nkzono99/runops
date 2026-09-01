"""Durable submission claim and per-run locking."""

from __future__ import annotations

import errno
import fcntl
import os
import stat
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext, suppress
from pathlib import Path
from typing import TypeVar

from runops.core.exceptions import InvalidStateTransitionError
from runops.core.manifest import read_manifest
from runops.core.state import RunState

from .models import SubmissionClaimError, SubmissionGuard, SubmissionLockError

_ResetResult = TypeVar("_ResetResult")
_SUBMISSION_LOCK_FILE = ".runops-submit.lock"


def _read_submission_claim(run_dir: Path) -> str:
    lock_path = run_dir / _SUBMISSION_LOCK_FILE
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
    try:
        descriptor = os.open(lock_path, flags)
    except OSError as exc:
        if exc.errno == errno.ENOENT:
            return ""
        raise SubmissionLockError(lock_path, exc) from exc
    try:
        try:
            _validate_submission_lock(lock_path, descriptor)
        except OSError as exc:
            raise SubmissionLockError(lock_path, exc) from exc
        return _read_submission_claim_from_descriptor(descriptor)
    finally:
        with suppress(OSError):
            os.close(descriptor)


def _read_submission_claim_from_descriptor(descriptor: int) -> str:
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        payload = os.read(descriptor, 4096)
    except OSError as exc:
        raise SubmissionClaimError("read submission claim", exc) from exc
    if not payload:
        return ""
    claim = payload.decode("utf-8", errors="replace").strip()
    return claim or "<invalid-nonempty-claim>"


def _write_submission_claim(
    descriptor: int,
    claim: str,
    *,
    operation: str,
) -> None:
    payload = f"{claim}\n".encode() if claim else b""
    previous_claim = (
        _read_submission_claim_from_descriptor(descriptor) if not claim else ""
    )
    try:
        _replace_submission_claim_payload(descriptor, payload)
    except OSError as exc:
        if previous_claim:
            previous_payload = f"{previous_claim}\n".encode()
            with suppress(OSError):
                _replace_submission_claim_payload(descriptor, previous_payload)
        raise SubmissionClaimError(operation, exc) from exc


def _replace_submission_claim_payload(descriptor: int, payload: bytes) -> None:
    os.lseek(descriptor, 0, os.SEEK_SET)
    written = 0
    while written < len(payload):
        count = os.write(descriptor, payload[written:])
        if count == 0:
            raise OSError("zero-byte submission claim write")
        written += count
    os.ftruncate(descriptor, len(payload))
    os.fsync(descriptor)


@contextmanager
def _submission_lock(run_dir: Path) -> Iterator[int]:
    """Hold the persistent advisory lock for one run submission.

    The file is intentionally never unlinked: deleting it after unlock permits
    concurrent processes to lock different inodes for the same run.
    """
    lock_path = run_dir / _SUBMISSION_LOCK_FILE
    common_flags = os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW
    created = False
    try:
        descriptor = os.open(
            lock_path,
            common_flags | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        created = True
    except OSError as exc:
        if exc.errno != errno.EEXIST:
            raise SubmissionLockError(lock_path, exc) from exc
        try:
            descriptor = os.open(lock_path, common_flags)
        except OSError as open_exc:
            raise SubmissionLockError(lock_path, open_exc) from open_exc

    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        except OSError as exc:
            raise SubmissionLockError(lock_path, exc) from exc
        try:
            _validate_submission_lock(lock_path, descriptor)
            if created:
                os.fsync(descriptor)
            _fsync_directory(run_dir)
        except OSError as exc:
            raise SubmissionLockError(lock_path, exc) from exc
        yield descriptor
    finally:
        with suppress(OSError):
            os.close(descriptor)


def _validate_submission_lock(lock_path: Path, descriptor: int) -> None:
    descriptor_stat = os.fstat(descriptor)
    if not stat.S_ISREG(descriptor_stat.st_mode) or descriptor_stat.st_nlink != 1:
        raise OSError(
            errno.EINVAL,
            "submission lock must be a regular single-link file",
            lock_path,
        )
    path_stat = os.stat(lock_path, follow_symlinks=False)
    if (
        not stat.S_ISREG(path_stat.st_mode)
        or path_stat.st_dev != descriptor_stat.st_dev
        or path_stat.st_ino != descriptor_stat.st_ino
    ):
        raise OSError(
            errno.ESTALE,
            "submission lock path was replaced while acquiring the lock",
            lock_path,
        )


def _fsync_directory(directory: Path) -> None:
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open(directory, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def submission_guard(run_dir: Path) -> Iterator[SubmissionGuard]:
    """Serialize destructive lifecycle work with submission and expose its claim."""
    with _submission_lock(run_dir) as descriptor:
        yield SubmissionGuard(
            claim=_read_submission_claim_from_descriptor(descriptor),
        )


def reset_retry_under_submission_lock(
    run_dir: Path,
    resetter: Callable[[], _ResetResult],
    *,
    mutation_guard: AbstractContextManager[None] | None = None,
    preflight: Callable[[], None] | None = None,
) -> _ResetResult:
    """Validate, preflight, and reset under the Run then mutation lock order."""
    with (
        _submission_lock(run_dir) as lock_descriptor,
        mutation_guard or nullcontext(),
    ):
        manifest = read_manifest(run_dir)
        current_state = str(manifest.run.get("status", ""))
        if current_state not in {
            RunState.FAILED.value,
            RunState.CANCELLED.value,
        }:
            raise InvalidStateTransitionError(
                current_state,
                RunState.CREATED.value,
            )
        if preflight is not None:
            preflight()
        _write_submission_claim(
            lock_descriptor,
            "",
            operation="clear reconciled retry claim",
        )
        return resetter()
