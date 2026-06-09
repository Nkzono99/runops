"""Run creation, submission, synchronization, and retry actions."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runops.core.actions.helpers import _error, _precondition_fail, _require_state
from runops.core.actions.result import ActionResult, ActionStatus
from runops.core.event_log import logged_action
from runops.core.exceptions import SimctlError
from runops.core.state import RunState


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
    from runops.core.project import load_project
    from runops.core.run_creation import create_case_run

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
    from runops.core.project import load_project
    from runops.core.run_creation import create_survey_runs

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


def _scheduler_from_manifest_job(job: dict[str, Any]) -> str:
    """Return the normalized scheduler name from a manifest job section."""
    return str(job.get("scheduler", "slurm")).lower()


def _scheduler_state_updates(scheduler: str, state: str) -> dict[str, str]:
    updates = {
        "last_scheduler_state": state,
        f"last_{scheduler}_state": state,
    }
    if scheduler == "slurm":
        updates["last_slurm_state"] = state
    elif scheduler == "pbs":
        updates["last_slurm_state"] = ""
    return updates


@logged_action("submit_run")
def submit_run(
    run_dir: Path,
    *,
    queue_name: str = "",
    qos: str = "",
    afterok: str = "",
    group_name: str = "",
) -> ActionResult:
    """Submit a run to the scheduler recorded in manifest.toml."""
    from runops.core.manifest import read_manifest, update_manifest
    from runops.core.retry import get_attempt_count
    from runops.core.state import update_state

    state_str, err = _require_state(run_dir, RunState.CREATED)
    if err:
        return _precondition_fail("submit_run", err)

    job_script = run_dir / "submit" / "job.sh"
    if not job_script.exists():
        return _precondition_fail("submit_run", f"Job script not found: {job_script}")

    input_dir = run_dir / "input"
    if not input_dir.is_dir() or not any(input_dir.iterdir()):
        return _precondition_fail(
            "submit_run",
            f"input/ directory is empty or missing in {run_dir}",
        )

    try:
        job_content = job_script.read_text(encoding="utf-8")
    except OSError as e:
        return _error("submit_run", f"Failed to read job script: {e}")

    manifest = read_manifest(run_dir)
    scheduler = _scheduler_from_manifest_job(manifest.job)
    expected_directive = "#PBS" if scheduler == "pbs" else "#SBATCH"

    if scheduler not in {"slurm", "pbs"}:
        return _precondition_fail(
            "submit_run",
            f"Unsupported scheduler in manifest: {scheduler!r}",
        )

    if expected_directive not in job_content:
        return _precondition_fail(
            "submit_run",
            f"job.sh does not contain expected {expected_directive} directives",
        )

    run_id = manifest.run.get("id", run_dir.name)
    warnings: list[str] = []
    tags = manifest.classification.get("tags", [])
    if "production" in tags and manifest.simulator_source.get("git_dirty", False):
        warnings.append("production run submitted with dirty git working tree")

    work_dir = run_dir / "work"
    if not work_dir.is_dir():
        work_dir = run_dir

    extra_args: list[str] = []
    if scheduler == "slurm":
        from runops.slurm.submit import (
            SlurmNotFoundError,
            SlurmSubmitError,
            sbatch_submit,
        )

        if queue_name:
            extra_args.append(f"--partition={queue_name}")
        if qos:
            extra_args.append(f"--qos={qos}")

        try:
            job_id = sbatch_submit(
                job_script,
                work_dir,
                extra_args=extra_args or None,
                afterok=afterok or None,
            )
        except (
            SlurmNotFoundError,
            SlurmSubmitError,
            FileNotFoundError,
            RuntimeError,
        ) as e:
            return _error("submit_run", f"sbatch failed: {e}")
    else:
        from runops.pbs.submit import PbsNotFoundError, PbsSubmitError, qsub_submit

        if qos:
            return _precondition_fail(
                "submit_run",
                "qos is Slurm-only; use --queue-name and --group for PBS",
            )
        if queue_name:
            extra_args.extend(["-q", queue_name])
        if group_name:
            extra_args.extend(["-W", f"group_list={group_name}"])

        try:
            job_id = qsub_submit(
                job_script,
                run_dir,
                extra_args=extra_args or None,
                afterok=afterok or None,
            )
        except (PbsNotFoundError, PbsSubmitError, FileNotFoundError, RuntimeError) as e:
            return _error("submit_run", f"qsub failed: {e}")

    now = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
    attempt = get_attempt_count(manifest.job) + 1
    existing_attempts: list[dict[str, str]] = list(manifest.job.get("attempts", []))
    attempt_record = {
        "scheduler": scheduler,
        "job_id": job_id,
        "submitted_at": now,
        "attempt": str(attempt),
    }
    if queue_name:
        attempt_record["partition"] = queue_name
        attempt_record["queue"] = queue_name
    if qos:
        attempt_record["qos"] = qos
    if afterok:
        attempt_record["afterok"] = afterok
    if group_name:
        attempt_record["group"] = group_name
    existing_attempts.append(attempt_record)
    job_updates: dict[str, Any] = {
        "scheduler": scheduler,
        "job_id": job_id,
        "submitted_at": now,
        "attempt": attempt,
        "attempts": existing_attempts,
        "queue": queue_name or manifest.job.get("queue", ""),
    }
    if queue_name:
        job_updates["partition"] = queue_name
        job_updates["queue"] = queue_name
    if qos:
        job_updates["qos"] = qos
    if afterok:
        job_updates["afterok"] = afterok
    if group_name:
        job_updates["group"] = group_name

    update_manifest(
        run_dir,
        {
            "run": _scheduler_state_updates(scheduler, ""),
            "job": job_updates,
        },
    )
    try:
        update_state(run_dir, RunState.SUBMITTED)
    except SimctlError as e:
        return _error("submit_run", f"State transition failed: {e}")

    return ActionResult(
        action="submit_run",
        status=ActionStatus.SUCCESS,
        message=f"Submitted job {job_id} (attempt {attempt})",
        data={
            "job_id": job_id,
            "scheduler": scheduler,
            "attempt": attempt,
            "run_id": run_id,
            "warnings": warnings,
        },
        state_before=state_str,
        state_after=RunState.SUBMITTED.value,
    )


@logged_action("sync_run")
def sync_run(run_dir: Path) -> ActionResult:
    """Synchronize run state with the recorded scheduler."""
    from runops.core.manifest import read_manifest, update_manifest
    from runops.core.state import update_state

    manifest = read_manifest(run_dir)
    run_id = manifest.run.get("id", run_dir.name)
    job_id = manifest.job.get("job_id", "")
    scheduler = _scheduler_from_manifest_job(manifest.job)
    if not job_id:
        return _precondition_fail("sync_run", "No job_id recorded in manifest")

    state_str, err = _require_state(run_dir, RunState.SUBMITTED, RunState.RUNNING)
    if err:
        return _precondition_fail("sync_run", err)

    if scheduler == "slurm":
        from runops.slurm.query import (
            SlurmQueryError,
        )
        from runops.slurm.query import (
            query_job_status as query_slurm_job_status,
        )

        try:
            slurm_status = query_slurm_job_status(job_id)
            scheduler_state = slurm_status.slurm_state
            new_state = slurm_status.run_state
            failure_reason = slurm_status.failure_reason
            exit_code = slurm_status.exit_code
        except (SlurmQueryError, RuntimeError) as e:
            return _error("sync_run", f"Slurm query failed: {e}")
    elif scheduler == "pbs":
        from runops.pbs.query import (
            PbsQueryError,
        )
        from runops.pbs.query import (
            query_job_status as query_pbs_job_status,
        )

        try:
            pbs_status = query_pbs_job_status(job_id)
            scheduler_state = pbs_status.pbs_state
            new_state = pbs_status.run_state
            failure_reason = pbs_status.failure_reason
            exit_code = pbs_status.exit_code
        except (PbsQueryError, RuntimeError) as e:
            return _error("sync_run", f"PBS query failed: {e}")
    else:
        return _precondition_fail(
            "sync_run",
            f"Unsupported scheduler in manifest: {scheduler!r}",
        )

    if new_state.value == state_str:
        try:
            update_manifest(
                run_dir,
                {"run": _scheduler_state_updates(scheduler, scheduler_state)},
            )
        except SimctlError as e:
            return _error("sync_run", f"State update failed: {e}")

        return ActionResult(
            action="sync_run",
            status=ActionStatus.SUCCESS,
            message=f"State unchanged: {state_str}",
            data={
                "run_id": run_id,
                "scheduler": scheduler,
                "scheduler_state": scheduler_state,
                "slurm_state": scheduler_state if scheduler == "slurm" else "",
                "pbs_state": scheduler_state if scheduler == "pbs" else "",
            },
            state_before=state_str,
            state_after=state_str,
        )

    try:
        update_state(
            run_dir,
            new_state,
            reconcile=True,
            reason=failure_reason,
            slurm_state=scheduler_state,
        )
        update_manifest(
            run_dir,
            {"run": _scheduler_state_updates(scheduler, scheduler_state)},
        )
    except SimctlError as e:
        return _error("sync_run", f"State update failed: {e}")

    return ActionResult(
        action="sync_run",
        status=ActionStatus.SUCCESS,
        message=f"State: {state_str} -> {new_state.value}",
        data={
            "run_id": run_id,
            "scheduler": scheduler,
            "scheduler_state": scheduler_state,
            "slurm_state": scheduler_state if scheduler == "slurm" else "",
            "pbs_state": scheduler_state if scheduler == "pbs" else "",
            "failure_reason": failure_reason,
            "exit_code": exit_code,
        },
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
    from runops.core.manifest import read_manifest, update_manifest
    from runops.core.retry import assess_retry_for_run

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
    from runops.core.manifest import read_manifest
    from runops.core.retry import assess_retry_for_run, get_attempt_count
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

    reset_state_for_retry(
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
