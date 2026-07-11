"""Submission plans, results, guards, and errors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from runops.core.exceptions import SimctlError

Clock = Callable[[], datetime]
PersistencePhase = Literal["claim", "manifest", "state"]


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


@dataclass(frozen=True)
class SubmissionGuard:
    """Snapshot exposed while the caller holds a run's submission lock."""

    claim: str
