"""Run creation, submission, synchronization, and retry actions."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from runops.application.actions.helpers import (
    _error,
    _precondition_fail,
    _require_state,
)
from runops.application.actions.result import ActionResult, ActionStatus
from runops.core.event_log import logged_action
from runops.core.exceptions import SimctlError
from runops.core.state import RunState

if TYPE_CHECKING:
    from runops.application.execution.submission import SubmitPlan


@logged_action("create_run")
def create_run(
    project_root: Path,
    case_name: str,
    *,
    dest_dir: Path | None = None,
    display_name: str = "",
    params: dict[str, Any] | None = None,
) -> ActionResult:
    """Create a new run directory from a case definition."""
    from runops.application.run_creation import create_case_run
    from runops.core.project import load_project

    try:
        project = load_project(project_root)
        result = create_case_run(
            project,
            case_name,
            dest_dir=dest_dir,
            display_name=display_name,
            params=params,
        )

        return ActionResult(
            action="create_run",
            status=ActionStatus.SUCCESS,
            message=f"Created run {result.run_info.run_id}",
            data={
                "run_id": result.run_info.run_id,
                "run_dir": str(result.run_info.run_dir),
                "display_name": result.run_info.display_name,
                "warnings": list(result.warnings),
            },
            state_after=RunState.CREATED.value,
        )
    except SimctlError as e:
        return _error("create_run", str(e))


@logged_action("create_survey")
def create_survey(project_root: Path, survey_dir: Path) -> ActionResult:
    """Expand a survey.toml into created run directories."""
    from runops.application.run_creation import create_survey_runs
    from runops.core.project import load_project

    try:
        project = load_project(project_root)
        created_runs = create_survey_runs(project, survey_dir)
    except SimctlError as e:
        return _error("create_survey", str(e))

    run_payload: list[dict[str, Any]] = []
    aggregated_warnings: list[dict[str, str]] = []
    for result in created_runs:
        run_payload.append(
            {
                "run_id": result.run_info.run_id,
                "run_dir": str(result.run_info.run_dir),
                "display_name": result.run_info.display_name,
                "warnings": list(result.warnings),
            }
        )
        for warning in result.warnings:
            aggregated_warnings.append(
                {
                    "display_name": result.run_info.display_name,
                    "message": warning,
                }
            )

    if not run_payload:
        return ActionResult(
            action="create_survey",
            status=ActionStatus.SUCCESS,
            message=f"No parameter combinations to expand in {survey_dir}",
            data={
                "survey_dir": str(survey_dir),
                "created_count": 0,
                "runs": [],
                "warnings": [],
            },
        )

    return ActionResult(
        action="create_survey",
        status=ActionStatus.SUCCESS,
        message=f"Created {len(run_payload)} runs",
        data={
            "survey_dir": str(survey_dir),
            "created_count": len(run_payload),
            "runs": run_payload,
            "warnings": aggregated_warnings,
        },
        state_after=RunState.CREATED.value,
    )


@logged_action("submit_run")
def submit_run(
    run_dir: Path,
    *,
    queue_name: str = "",
    qos: str = "",
    afterok: str = "",
) -> ActionResult:
    """Submit a run to Slurm via sbatch."""
    from runops.application.execution.submission import (
        SubmitRequest,
        plan_submit,
    )

    try:
        plan = plan_submit(
            SubmitRequest(
                run_dir=run_dir,
                queue_name=queue_name,
                qos=qos,
                afterok=afterok,
            )
        )
    except SimctlError as e:
        return _error("submit_run", str(e))

    return _apply_planned_submit(plan)


@logged_action("submit_run")
def submit_planned_run(plan: SubmitPlan) -> ActionResult:
    """Apply an existing plan without rebuilding its confirmed snapshot."""
    return _apply_planned_submit(plan)


def _apply_planned_submit(plan: SubmitPlan) -> ActionResult:
    """Map the shared submission apply result to the action envelope."""
    from runops.application.execution.submission import (
        SubmissionClaimError,
        SubmissionLockError,
        SubmissionOutcomeUnknownError,
        SubmissionPersistenceError,
        SubmissionStaleError,
        apply_submit,
    )
    from runops.slurm.submit import (
        SlurmNotFoundError,
        SlurmSubmitError,
        submit_command,
    )

    if not plan.ready:
        return _precondition_fail(
            "submit_run",
            plan.failed_preconditions[0].message,
        )

    try:
        result = apply_submit(plan, submit_command)
    except SubmissionPersistenceError as e:
        return ActionResult(
            action="submit_run",
            status=ActionStatus.ERROR,
            message=(
                f"Scheduler accepted job {e.job_id}; persistence failed during "
                f"{e.phase}; do not resubmit; reconcile local state. "
                f"Cause: {e.cause_type}: {e.cause_message}"
            ),
            data={
                "job_id": e.job_id,
                "attempt": e.attempt,
                "submitted_at": e.submitted_at,
                "phase": e.phase,
            },
            state_before=plan.state_before,
        )
    except SubmissionOutcomeUnknownError as e:
        return ActionResult(
            action="submit_run",
            status=ActionStatus.ERROR,
            message=(
                "Scheduler submission outcome is unknown; pending claim retained; "
                "do not resubmit; reconcile scheduler and local state. "
                f"Cause: {e.cause_type}: {e.cause_message}"
            ),
            data={
                "run_id": e.run_id,
                "attempt": e.attempt,
                "submitted_at": e.submitted_at,
                "claim": e.claim,
            },
            state_before=plan.state_before,
        )
    except SubmissionStaleError as e:
        return _precondition_fail("submit_run", str(e))
    except SubmissionClaimError as e:
        return _error("submit_run", f"Submission claim failed: {e}")
    except SubmissionLockError as e:
        return _error("submit_run", f"Submission lock failed: {e}")
    except (SlurmNotFoundError, SlurmSubmitError, FileNotFoundError, RuntimeError) as e:
        return _error("submit_run", f"sbatch failed: {e}")
    except SimctlError as e:
        return _error("submit_run", f"State transition failed: {e}")

    return ActionResult(
        action="submit_run",
        status=ActionStatus.SUCCESS,
        message=f"Submitted job {result.job_id} (attempt {result.attempt})",
        data={
            "job_id": result.job_id,
            "attempt": result.attempt,
            "run_id": result.run_id,
            "warnings": list(result.warnings),
        },
        state_before=result.state_before,
        state_after=result.state_after,
    )


@logged_action("sync_run")
def sync_run(run_dir: Path) -> ActionResult:
    """Synchronize run state with Slurm."""
    from runops.core.manifest import read_manifest, update_manifest
    from runops.core.state import update_state
    from runops.slurm.query import SlurmQueryError, query_job_status

    manifest = read_manifest(run_dir)
    run_id = manifest.run.get("id", run_dir.name)
    job_id = manifest.job.get("job_id", "")
    if not job_id:
        return _precondition_fail("sync_run", "No job_id recorded in manifest")

    state_str, err = _require_state(run_dir, RunState.SUBMITTED, RunState.RUNNING)
    if err:
        return _precondition_fail("sync_run", err)

    try:
        job_status = query_job_status(job_id)
    except (SlurmQueryError, RuntimeError) as e:
        return _error("sync_run", f"Slurm query failed: {e}")

    new_state = job_status.run_state
    if new_state.value == state_str:
        try:
            update_manifest(
                run_dir,
                {"run": {"last_slurm_state": job_status.slurm_state}},
            )
        except SimctlError as e:
            return _error("sync_run", f"State update failed: {e}")

        return ActionResult(
            action="sync_run",
            status=ActionStatus.SUCCESS,
            message=f"State unchanged: {state_str}",
            data={"run_id": run_id, "slurm_state": job_status.slurm_state},
            state_before=state_str,
            state_after=state_str,
        )

    try:
        update_state(
            run_dir,
            new_state,
            reconcile=True,
            reason=job_status.failure_reason,
            slurm_state=job_status.slurm_state,
        )
    except SimctlError as e:
        return _error("sync_run", f"State update failed: {e}")

    data: dict[str, Any] = {
        "run_id": run_id,
        "slurm_state": job_status.slurm_state,
        "failure_reason": job_status.failure_reason,
        "exit_code": job_status.exit_code,
    }
    if new_state is RunState.COMPLETED:
        from runops.application.execution.readiness import (
            probe_run_readiness,
            write_readiness_cache,
        )

        try:
            updated_manifest = read_manifest(run_dir)
            readiness = probe_run_readiness(run_dir, manifest=updated_manifest)
            cache_path = write_readiness_cache(
                run_dir,
                readiness,
                manifest=updated_manifest,
            )
            data.update(
                {
                    "readiness": readiness.to_dict(),
                    "recommended_action": readiness.recommended_action,
                    "recommended_command": readiness.recommended_command,
                    "requires_human": readiness.requires_human,
                    "readiness_cache": str(cache_path),
                }
            )
        except Exception as exc:  # pragma: no cover - optional diagnostic boundary
            data.update(
                {
                    "readiness": {
                        "analysis_status": "unknown",
                        "analysis_ready": False,
                        "reason_codes": ["readiness_probe_error"],
                        "warnings": [str(exc)],
                    },
                    "recommended_action": "deep_validate",
                    "recommended_command": f"runo runs status {run_id}",
                    "requires_human": False,
                }
            )

    return ActionResult(
        action="sync_run",
        status=ActionStatus.SUCCESS,
        message=f"State: {state_str} -> {new_state.value}",
        data=data,
        state_before=state_str,
        state_after=new_state.value,
    )


@logged_action("plan_retry")
def plan_retry(
    run_dir: Path,
    *,
    adjustments: dict[str, str] | None = None,
    reviewed_log: bool = False,
    note: str = "",
) -> ActionResult:
    """Record retry intent for a failed or cancelled run without resetting it."""
    from runops.application.execution.retry import assess_retry_for_run
    from runops.core.manifest import read_manifest, update_manifest

    state_str, err = _require_state(run_dir, RunState.FAILED, RunState.CANCELLED)
    if err:
        return _precondition_fail("plan_retry", err)

    manifest = read_manifest(run_dir)
    failure_reason = manifest.run.get("failure_reason", "")
    if failure_reason == "exit_error" and not reviewed_log:
        return _precondition_fail(
            "plan_retry",
            "failure_reason 'exit_error' requires log review before planning retry",
        )

    assessment = assess_retry_for_run(run_dir)
    if assessment.attempt >= assessment.max_attempts:
        return _precondition_fail(
            "plan_retry",
            f"Max attempts ({assessment.max_attempts}) reached. "
            "Manual inspection required.",
        )

    run_updates: dict[str, Any] = {
        "retry_status": "retry_planned",
        "partial_outputs": assessment.partial_outputs,
    }
    if note:
        run_updates["retry_note"] = note
    update_manifest(
        run_dir,
        {
            "run": run_updates,
            "job": {
                "retry_adjustments": adjustments or {},
                "next_attempt": assessment.attempt + 1,
            },
        },
    )

    planned = assess_retry_for_run(run_dir)
    return ActionResult(
        action="plan_retry",
        status=ActionStatus.SUCCESS,
        message=f"Planned retry for {planned.run_id} (attempt {planned.attempt + 1})",
        data={
            "assessment": planned.to_dict(),
            "adjustments": adjustments or {},
            "note": note,
        },
        state_before=state_str,
        state_after=state_str,
    )


@logged_action("retry_run")
def retry_run(
    run_dir: Path,
    *,
    adjustments: dict[str, Any] | None = None,
    reviewed_log: bool = False,
) -> ActionResult:
    """Resubmit a failed or cancelled run as a new attempt."""
    from runops.application.execution.retry import (
        assess_retry_for_run,
        get_attempt_count,
    )
    from runops.application.execution.submission import (
        SubmissionClaimError,
        SubmissionLockError,
        reset_retry_under_submission_lock,
    )
    from runops.core.manifest import read_manifest
    from runops.core.state import reset_state_for_retry

    state_str, err = _require_state(run_dir, RunState.FAILED, RunState.CANCELLED)
    if err:
        return _precondition_fail("retry_run", err)

    manifest = read_manifest(run_dir)
    attempt = get_attempt_count(manifest.job)
    failure_reason = manifest.run.get("failure_reason", "")
    assessment = assess_retry_for_run(run_dir)

    if attempt >= 3:
        return _precondition_fail(
            "retry_run",
            "Max attempts (3) reached. Manual inspection required.",
        )
    if failure_reason == "exit_error" and not reviewed_log:
        return _precondition_fail(
            "retry_run",
            "failure_reason 'exit_error' requires log review before retrying",
        )

    def resetter() -> RunState:
        return reset_state_for_retry(
            run_dir,
            run_updates={
                "retry_status": "retry_ready",
                "partial_outputs": assessment.partial_outputs,
            },
            job_updates={
                "attempt": attempt,
                "retry_adjustments": adjustments or {},
            },
        )

    try:
        reset_retry_under_submission_lock(run_dir, resetter)
    except (SubmissionClaimError, SubmissionLockError) as e:
        return _error("retry_run", f"Submission claim reconciliation failed: {e}")
    except SimctlError as e:
        return _precondition_fail("retry_run", str(e))

    return ActionResult(
        action="retry_run",
        status=ActionStatus.SUCCESS,
        message=f"Reset to created for retry (attempt {attempt + 1})",
        data={
            "previous_attempt": attempt,
            "next_attempt": attempt + 1,
            "adjustments": adjustments or {},
            "assessment": assessment.to_dict(),
        },
        state_before=state_str,
        state_after=RunState.CREATED.value,
    )
