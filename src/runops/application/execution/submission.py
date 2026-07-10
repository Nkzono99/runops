"""Shared planning and application workflow for scheduler submission."""

from __future__ import annotations

import copy
import errno
import fcntl
import os
import stat
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, TypeVar, cast

from runops.application.execution.retry import get_attempt_count
from runops.application.ports.scheduler import (
    SchedulerOutcomeUnknownError,
    SchedulerRejectedError,
    Submitter,
)
from runops.core.exceptions import InvalidStateTransitionError, SimctlError
from runops.core.manifest import read_manifest, update_manifest
from runops.core.state import RunState, update_state

Clock = Callable[[], datetime]
PersistencePhase = Literal["claim", "manifest", "state"]
_ResetResult = TypeVar("_ResetResult")

_DIRTY_PRODUCTION_WARNING = "production run submitted with dirty git working tree"
_SUBMISSION_LOCK_FILE = ".runops-submit.lock"


@dataclass(frozen=True)
class SubmitRequest:
    """Inputs needed to construct one deterministic submission plan."""

    run_dir: Path
    queue_name: str = ""
    qos: str = ""
    afterok: str = ""


@dataclass(frozen=True)
class SubmitPrecondition:
    """One stable, named condition required before submission."""

    name: str
    passed: bool
    message: str


@dataclass(frozen=True)
class SubmitPlan:
    """Immutable description of exactly one scheduler submission."""

    run_id: str
    run_dir: Path
    state_before: str
    job_id_before: str
    claim_before: str
    job_script: Path
    work_dir: Path
    queue_name: str
    qos: str
    afterok: str
    command: tuple[str, ...]
    preconditions: tuple[SubmitPrecondition, ...]
    warnings: tuple[str, ...]

    @property
    def failed_preconditions(self) -> tuple[SubmitPrecondition, ...]:
        """Return failed checks in their stable evaluation order."""
        return tuple(check for check in self.preconditions if not check.passed)

    @property
    def ready(self) -> bool:
        """Whether this plan may be applied."""
        return not self.failed_preconditions


@dataclass(frozen=True)
class SubmissionResult:
    """Typed result of a successfully applied submission plan."""

    run_id: str
    job_id: str
    submitted_at: str
    attempt: int
    command: tuple[str, ...]
    warnings: tuple[str, ...]
    state_before: str
    state_after: str


class SubmissionBlockedError(RuntimeError):
    """Raised when an application is attempted for a blocked plan."""

    def __init__(self, failed: tuple[SubmitPrecondition, ...]) -> None:
        self.failed_preconditions = failed
        names = ", ".join(check.name for check in failed)
        super().__init__(f"Submission plan is blocked by: {names}")


class SubmissionStaleError(RuntimeError):
    """Raised when a submission snapshot changed after planning."""

    def __init__(
        self,
        *,
        planned_run_id: str,
        current_run_id: str,
        planned_state: str,
        current_state: str,
        planned_job_id: str,
        current_job_id: str,
        planned_work_dir: Path,
        current_work_dir: Path,
        planned_claim: str,
        current_claim: str,
    ) -> None:
        changes: list[str] = []
        if current_run_id != planned_run_id:
            changes.append(
                f"run_id changed from {planned_run_id!r} to {current_run_id!r}"
            )
        if current_state != planned_state:
            changes.append(f"state changed from {planned_state!r} to {current_state!r}")
        if current_job_id != planned_job_id:
            changes.append(
                f"job_id changed from {planned_job_id!r} to {current_job_id!r}"
            )
        if current_work_dir != planned_work_dir:
            changes.append(
                f"work_dir changed from {str(planned_work_dir)!r} "
                f"to {str(current_work_dir)!r}"
            )
        if current_claim != planned_claim:
            changes.append(f"claim changed from {planned_claim!r} to {current_claim!r}")
        super().__init__(f"Submission plan is stale: {'; '.join(changes)}")


class SubmissionLockError(RuntimeError):
    """Raised when the per-run process lock cannot be acquired."""

    def __init__(self, lock_path: Path, cause: OSError) -> None:
        self.lock_path = lock_path
        self.cause = cause
        super().__init__(f"Failed to lock {lock_path}: {cause}")


class SubmissionClaimError(RuntimeError):
    """Raised when durable submission-claim I/O fails."""

    def __init__(self, operation: str, cause: OSError) -> None:
        self.operation = operation
        self.cause = cause
        super().__init__(f"Failed to {operation}: {cause}")


class SubmissionOutcomeUnknownError(RuntimeError):
    """Keep a fail-closed claim when scheduler acceptance cannot be determined."""

    def __init__(
        self,
        *,
        run_id: str,
        attempt: int,
        submitted_at: str,
        cause: Exception,
    ) -> None:
        self.run_id = run_id
        self.attempt = attempt
        self.submitted_at = submitted_at
        self.claim = "pending"
        self.cause = cause
        self.cause_type = type(cause).__name__
        self.cause_message = str(cause)
        super().__init__(
            f"Scheduler submission outcome is unknown for {run_id}; pending claim "
            f"retained; do not resubmit before reconciliation. Cause: "
            f"{self.cause_type}: {self.cause_message}"
        )


class SubmissionPersistenceError(RuntimeError):
    """Report a local persistence failure after scheduler acceptance."""

    def __init__(
        self,
        *,
        job_id: str,
        attempt: int,
        submitted_at: str,
        phase: PersistencePhase,
        cause: SimctlError | OSError | SubmissionClaimError,
    ) -> None:
        self.job_id = job_id
        self.attempt = attempt
        self.submitted_at = submitted_at
        self.phase = phase
        self.cause = cause
        self.cause_type = type(cause).__name__
        self.cause_message = str(cause)
        super().__init__(
            f"Scheduler accepted job {job_id}, but {phase} persistence failed: "
            f"{self.cause_type}: {self.cause_message}"
        )


def plan_submit(request: SubmitRequest) -> SubmitPlan:
    """Build a complete, read-only plan for one run submission."""
    run_dir = request.run_dir.resolve()
    manifest = read_manifest(run_dir)
    run_id = str(manifest.run.get("id", run_dir.name))
    state_before = str(manifest.run.get("status", ""))
    job_id_before = str(manifest.job.get("job_id", "") or "")
    try:
        claim_before = _read_submission_claim(run_dir)
    except (SubmissionLockError, SubmissionClaimError) as exc:
        claim_before = f"<unreadable: {type(exc).__name__}: {exc}>"
    job_script = run_dir / "submit" / "job.sh"
    input_dir = run_dir / "input"

    preconditions: list[SubmitPrecondition] = [
        SubmitPrecondition(
            name="state_created",
            passed=state_before == RunState.CREATED.value,
            message=(
                f"Run state is {state_before!r}; expected {RunState.CREATED.value!r}"
            ),
        )
    ]
    preconditions.append(
        SubmitPrecondition(
            name="job_id_empty",
            passed=not job_id_before,
            message=(
                "No accepted job_id is recorded"
                if not job_id_before
                else f"Accepted job_id is already recorded: {job_id_before}"
            ),
        )
    )
    preconditions.append(
        SubmitPrecondition(
            name="submission_claim_empty",
            passed=not claim_before,
            message=(
                "No durable submission claim is recorded"
                if not claim_before
                else f"Durable submission claim is recorded: {claim_before}"
            ),
        )
    )

    script_exists = _is_file(job_script)
    preconditions.append(
        SubmitPrecondition(
            name="job_script_exists",
            passed=script_exists,
            message=(
                f"Job script exists: {job_script}"
                if script_exists
                else f"Job script not found: {job_script}"
            ),
        )
    )

    job_content = ""
    script_readable = False
    read_error = ""
    if script_exists:
        try:
            job_content = job_script.read_text(encoding="utf-8")
            script_readable = True
        except (OSError, UnicodeError) as exc:
            read_error = str(exc)
    else:
        read_error = "job script does not exist"
    preconditions.append(
        SubmitPrecondition(
            name="job_script_readable",
            passed=script_readable,
            message=(
                f"Job script is readable: {job_script}"
                if script_readable
                else f"Failed to read job script {job_script}: {read_error}"
            ),
        )
    )

    has_sbatch = script_readable and "#SBATCH" in job_content
    if has_sbatch:
        sbatch_message = "job.sh contains expected #SBATCH directives"
    elif script_readable:
        sbatch_message = "job.sh does not contain expected #SBATCH directives"
    else:
        sbatch_message = "Cannot inspect #SBATCH directives in an unreadable job.sh"
    preconditions.append(
        SubmitPrecondition(
            name="job_script_has_sbatch",
            passed=has_sbatch,
            message=sbatch_message,
        )
    )

    input_ready, input_message = _check_input(input_dir)
    preconditions.append(
        SubmitPrecondition(
            name="input_ready",
            passed=input_ready,
            message=input_message,
        )
    )

    work_dir = _select_work_dir(run_dir)

    command = ["sbatch", f"--chdir={work_dir}"]
    if request.afterok:
        command.append(f"--dependency=afterok:{request.afterok}")
    if request.queue_name:
        command.append(f"--partition={request.queue_name}")
    if request.qos:
        command.append(f"--qos={request.qos}")
    command.append(str(job_script))

    warnings: tuple[str, ...] = ()
    tags = manifest.classification.get("tags", [])
    if "production" in tags and manifest.simulator_source.get("git_dirty", False):
        warnings = (_DIRTY_PRODUCTION_WARNING,)

    return SubmitPlan(
        run_id=run_id,
        run_dir=run_dir,
        state_before=state_before,
        job_id_before=job_id_before,
        claim_before=claim_before,
        job_script=job_script,
        work_dir=work_dir,
        queue_name=request.queue_name,
        qos=request.qos,
        afterok=request.afterok,
        command=tuple(command),
        preconditions=tuple(preconditions),
        warnings=warnings,
    )


def apply_submit(
    plan: SubmitPlan,
    submitter: Submitter,
    *,
    now: Clock | None = None,
) -> SubmissionResult:
    """Apply a valid plan and record state only after scheduler success."""
    if not plan.ready:
        raise SubmissionBlockedError(plan.failed_preconditions)

    submitted_at_datetime = (now or _utc_now)()
    if (
        submitted_at_datetime.tzinfo is None
        or submitted_at_datetime.utcoffset() is None
    ):
        raise ValueError("submission clock must return a timezone-aware datetime")
    submitted_at_datetime = submitted_at_datetime.astimezone(timezone.utc)
    with _submission_lock(plan.run_dir) as lock_descriptor:
        return _apply_submit_locked(
            plan,
            submitter,
            submitted_at_datetime=submitted_at_datetime,
            lock_descriptor=lock_descriptor,
        )


def _apply_submit_locked(
    plan: SubmitPlan,
    submitter: Submitter,
    *,
    submitted_at_datetime: datetime,
    lock_descriptor: int,
) -> SubmissionResult:
    """Apply one plan while the caller holds its per-run process lock."""
    submitted_at = submitted_at_datetime.isoformat()

    manifest = read_manifest(plan.run_dir)
    current_run_id = str(manifest.run.get("id", plan.run_dir.name))
    current_state = str(manifest.run.get("status", ""))
    current_job_id = str(manifest.job.get("job_id", "") or "")
    current_work_dir = _select_work_dir(plan.run_dir)
    current_claim = _read_submission_claim_from_descriptor(lock_descriptor)
    if (
        current_run_id != plan.run_id
        or current_state != plan.state_before
        or current_job_id != plan.job_id_before
        or current_work_dir != plan.work_dir
        or current_claim != plan.claim_before
    ):
        raise SubmissionStaleError(
            planned_run_id=plan.run_id,
            current_run_id=current_run_id,
            planned_state=plan.state_before,
            current_state=current_state,
            planned_job_id=plan.job_id_before,
            current_job_id=current_job_id,
            planned_work_dir=plan.work_dir,
            current_work_dir=current_work_dir,
            planned_claim=plan.claim_before,
            current_claim=current_claim,
        )

    attempt = get_attempt_count(manifest.job) + 1
    existing_attempts = copy.deepcopy(
        cast("list[dict[str, str]]", manifest.job.get("attempts", []))
    )
    attempt_record = _attempt_record(
        plan,
        job_id="",
        submitted_at=submitted_at,
        attempt=attempt,
    )
    existing_attempts.append(attempt_record)

    job_updates: dict[str, Any] = {
        "job_id": "",
        "submitted_at": submitted_at,
        "attempt": attempt,
        "attempts": existing_attempts,
        "queue": plan.queue_name or manifest.job.get("queue", ""),
    }
    if plan.queue_name:
        job_updates["partition"] = plan.queue_name
    if plan.qos:
        job_updates["qos"] = plan.qos
    if plan.afterok:
        job_updates["afterok"] = plan.afterok

    _write_submission_claim(
        lock_descriptor, "pending", operation="record pending claim"
    )
    try:
        job_id = submitter(plan.command)
    except SchedulerRejectedError as scheduler_error:
        try:
            _write_submission_claim(
                lock_descriptor,
                "",
                operation="clear rejected submission claim",
            )
        except SubmissionClaimError as claim_error:
            raise claim_error from scheduler_error
        raise
    except SchedulerOutcomeUnknownError as scheduler_error:
        raise SubmissionOutcomeUnknownError(
            run_id=plan.run_id,
            attempt=attempt,
            submitted_at=submitted_at,
            cause=scheduler_error,
        ) from scheduler_error
    except Exception as scheduler_error:
        raise SubmissionOutcomeUnknownError(
            run_id=plan.run_id,
            attempt=attempt,
            submitted_at=submitted_at,
            cause=scheduler_error,
        ) from scheduler_error

    if not isinstance(job_id, str) or not job_id.strip():
        invalid_result = ValueError("scheduler returned an empty job ID")
        raise SubmissionOutcomeUnknownError(
            run_id=plan.run_id,
            attempt=attempt,
            submitted_at=submitted_at,
            cause=invalid_result,
        ) from invalid_result
    job_id = job_id.strip()

    accepted_claim = f"accepted:{job_id}"
    try:
        _write_submission_claim(
            lock_descriptor,
            accepted_claim,
            operation="record accepted submission claim",
        )
    except SubmissionClaimError as exc:
        raise SubmissionPersistenceError(
            job_id=job_id,
            attempt=attempt,
            submitted_at=submitted_at,
            phase="claim",
            cause=exc,
        ) from exc
    attempt_record["job_id"] = job_id
    job_updates["job_id"] = job_id

    try:
        update_manifest(
            plan.run_dir,
            {
                "run": {"last_slurm_state": ""},
                "job": job_updates,
            },
        )
    except (SimctlError, OSError) as exc:
        raise SubmissionPersistenceError(
            job_id=job_id,
            attempt=attempt,
            submitted_at=submitted_at,
            phase="manifest",
            cause=exc,
        ) from exc

    try:
        update_state(
            plan.run_dir,
            RunState.SUBMITTED,
            timestamp=submitted_at_datetime,
        )
    except (SimctlError, OSError) as exc:
        raise SubmissionPersistenceError(
            job_id=job_id,
            attempt=attempt,
            submitted_at=submitted_at,
            phase="state",
            cause=exc,
        ) from exc

    try:
        _write_submission_claim(
            lock_descriptor,
            "",
            operation="clear persisted submission claim",
        )
    except SubmissionClaimError as exc:
        raise SubmissionPersistenceError(
            job_id=job_id,
            attempt=attempt,
            submitted_at=submitted_at,
            phase="claim",
            cause=exc,
        ) from exc

    return SubmissionResult(
        run_id=plan.run_id,
        job_id=job_id,
        submitted_at=submitted_at,
        attempt=attempt,
        command=plan.command,
        warnings=plan.warnings,
        state_before=plan.state_before,
        state_after=RunState.SUBMITTED.value,
    )


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _is_file(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False


def _is_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def _select_work_dir(run_dir: Path) -> Path:
    work_dir = run_dir / "work"
    return work_dir if _is_dir(work_dir) else run_dir


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


@dataclass(frozen=True)
class SubmissionGuard:
    """Snapshot exposed while the caller holds a run's submission lock."""

    claim: str


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
) -> _ResetResult:
    """Validate terminal state, durably clear its claim, then reset under lock."""
    with _submission_lock(run_dir) as lock_descriptor:
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
        _write_submission_claim(
            lock_descriptor,
            "",
            operation="clear reconciled retry claim",
        )
        return resetter()


def _check_input(input_dir: Path) -> tuple[bool, str]:
    try:
        if not input_dir.is_dir():
            return False, f"input/ directory is missing in {input_dir.parent}"
        if not any(input_dir.iterdir()):
            return False, f"input/ directory is empty in {input_dir.parent}"
    except OSError as exc:
        return False, f"Failed to inspect input/ directory {input_dir}: {exc}"
    return True, f"input/ directory contains submission inputs: {input_dir}"


def _attempt_record(
    plan: SubmitPlan,
    *,
    job_id: str,
    submitted_at: str,
    attempt: int,
) -> dict[str, str]:
    record = {
        "job_id": job_id,
        "submitted_at": submitted_at,
        "attempt": str(attempt),
    }
    if plan.queue_name:
        record["partition"] = plan.queue_name
        record["queue"] = plan.queue_name
    if plan.qos:
        record["qos"] = plan.qos
    if plan.afterok:
        record["afterok"] = plan.afterok
    return record


__all__ = [
    "SubmissionBlockedError",
    "SubmissionClaimError",
    "SubmissionGuard",
    "SubmissionLockError",
    "SubmissionOutcomeUnknownError",
    "SubmissionPersistenceError",
    "SubmissionResult",
    "SubmissionStaleError",
    "SubmitPlan",
    "SubmitPrecondition",
    "SubmitRequest",
    "apply_submit",
    "plan_submit",
    "reset_retry_under_submission_lock",
    "submission_guard",
]
