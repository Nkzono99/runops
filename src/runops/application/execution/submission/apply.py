"""Effectful scheduler submission and persistence."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any, cast

from runops.application.execution.retry import get_attempt_count
from runops.application.ports.scheduler import (
    SchedulerOutcomeUnknownError,
    SchedulerRejectedError,
    Submitter,
)
from runops.core.exceptions import SimctlError
from runops.core.manifest import read_manifest, update_manifest
from runops.core.state import RunState, update_state

from .claim import (
    _read_submission_claim_from_descriptor,
    _submission_lock,
    _write_submission_claim,
)
from .models import (
    Clock,
    SubmissionBlockedError,
    SubmissionClaimError,
    SubmissionOutcomeUnknownError,
    SubmissionPersistenceError,
    SubmissionResult,
    SubmissionStaleError,
    SubmitPlan,
)
from .planning import _select_work_dir


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
