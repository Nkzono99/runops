"""Shared planning and application workflow for scheduler submission."""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, cast

from runops.application.execution.retry import get_attempt_count
from runops.application.ports.scheduler import Submitter
from runops.core.exceptions import SimctlError
from runops.core.manifest import read_manifest, update_manifest
from runops.core.state import RunState, update_state

Clock = Callable[[], datetime]
PersistencePhase = Literal["manifest", "state"]

_DIRTY_PRODUCTION_WARNING = "production run submitted with dirty git working tree"


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
    """Raised when run identity or state changed after planning."""

    def __init__(
        self,
        *,
        planned_run_id: str,
        current_run_id: str,
        planned_state: str,
        current_state: str,
    ) -> None:
        changes: list[str] = []
        if current_run_id != planned_run_id:
            changes.append(
                f"run_id changed from {planned_run_id!r} to {current_run_id!r}"
            )
        if current_state != planned_state:
            changes.append(f"state changed from {planned_state!r} to {current_state!r}")
        super().__init__(f"Submission plan is stale: {'; '.join(changes)}")


class SubmissionPersistenceError(RuntimeError):
    """Report a local persistence failure after scheduler acceptance."""

    def __init__(
        self,
        *,
        job_id: str,
        attempt: int,
        submitted_at: str,
        phase: PersistencePhase,
        cause: SimctlError | OSError,
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

    work_dir = run_dir / "work"
    if not _is_dir(work_dir):
        work_dir = run_dir

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
    submitted_at = submitted_at_datetime.isoformat(timespec="seconds")

    manifest = read_manifest(plan.run_dir)
    current_run_id = str(manifest.run.get("id", plan.run_dir.name))
    current_state = str(manifest.run.get("status", ""))
    if current_run_id != plan.run_id or current_state != plan.state_before:
        raise SubmissionStaleError(
            planned_run_id=plan.run_id,
            current_run_id=current_run_id,
            planned_state=plan.state_before,
            current_state=current_state,
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

    job_id = submitter(plan.command)
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
    "SubmissionPersistenceError",
    "SubmissionResult",
    "SubmissionStaleError",
    "SubmitPlan",
    "SubmitPrecondition",
    "SubmitRequest",
    "apply_submit",
    "plan_submit",
]
