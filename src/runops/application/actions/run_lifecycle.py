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
    experiment_id: str = "",
    purpose: str = "",
    created_by: str = "human",
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
            experiment_id=experiment_id,
            purpose=purpose,
            created_by=created_by,
        )

        return ActionResult(
            action="create_run",
            status=ActionStatus.SUCCESS,
            message=(
                f"Reused equivalent Run {result.run_info.run_id}"
                if result.reused
                else f"Created run {result.run_info.run_id}"
            ),
            data={
                "run_id": result.run_info.run_id,
                "run_dir": str(result.run_info.run_dir),
                "display_name": result.run_info.display_name,
                "reused": result.reused,
                "warnings": list(result.warnings),
            },
            state_after="" if result.reused else RunState.CREATED.value,
        )
    except SimctlError as e:
        return _error("create_run", str(e))


@logged_action("create_survey")
def create_survey(
    project_root: Path,
    survey_dir: Path,
    *,
    expected_plan_hash: str,
    point_refs: tuple[str, ...] = (),
    all_points: bool = False,
) -> ActionResult:
    """Materialize explicitly selected points from an unchanged plan."""
    from runops.application.survey_materialization import materialize_survey_points
    from runops.core.project import load_project

    try:
        project = load_project(project_root)
        materialized = materialize_survey_points(
            project,
            survey_dir,
            expected_plan_hash=expected_plan_hash,
            point_refs=point_refs,
            all_points=all_points,
        )
    except SimctlError as e:
        return _error("create_survey", str(e))

    run_payload: list[dict[str, Any]] = []
    aggregated_warnings: list[dict[str, str]] = []
    for result in materialized.points:
        run_payload.append(
            {
                "ref": result.ref,
                "point_id": result.point_id,
                "ordinal": result.ordinal,
                "run_id": result.run_id,
                "run_dir": str(result.run_dir),
                "reused": result.reused,
                "warnings": list(result.warnings),
            }
        )
        for warning in result.warnings:
            aggregated_warnings.append(
                {
                    "point": result.ref,
                    "message": warning,
                }
            )

    return ActionResult(
        action="create_survey",
        status=ActionStatus.SUCCESS,
        message=(
            f"Materialized {materialized.created_count} and reused "
            f"{materialized.reused_count} runs"
        ),
        data={
            "survey_dir": str(survey_dir),
            "survey_id": materialized.survey_id,
            "plan_hash": materialized.plan_hash,
            "candidate_count": materialized.candidate_count,
            "created_count": materialized.created_count,
            "reused_count": materialized.reused_count,
            "runs": run_payload,
            "warnings": aggregated_warnings,
        },
        state_after=(RunState.CREATED.value if materialized.created_count else ""),
    )


@logged_action("plan_survey")
def plan_survey(
    project_root: Path,
    survey_dir: Path,
    *,
    offset: int = 0,
    limit: int = 50,
) -> ActionResult:
    """Preview a Survey without allocating IDs or creating directories."""
    from runops.application.survey_materialization import preview_survey_plan
    from runops.core.project import load_project

    try:
        preview = preview_survey_plan(
            load_project(project_root),
            survey_dir,
            offset=offset,
            limit=limit,
        )
    except SimctlError as exc:
        return _error("plan_survey", str(exc))

    plan = preview.plan
    return ActionResult(
        action="plan_survey",
        status=ActionStatus.SUCCESS,
        message=f"Planned {plan.candidate_count} candidates without materializing",
        data={
            "survey_dir": str(survey_dir),
            "survey_id": plan.survey_data.id,
            "experiment_id": plan.survey_data.experiment_id,
            "phase": plan.survey_data.phase,
            "purpose": plan.survey_data.intent.purpose,
            "plan_hash": plan.plan_hash,
            "candidate_count": plan.candidate_count,
            "estimated_core_hours": plan.estimated_core_hours,
            "offset": preview.offset,
            "limit": preview.limit,
            "admission_issues": list(preview.admission_issues),
            "points": [
                {
                    "ref": point.ref,
                    "point_id": point.point_id,
                    "ordinal": point.ordinal,
                    "params": point.params,
                    "display_name": point.display_name,
                    "directory_preview": point.directory_preview,
                }
                for point in preview.points
            ],
        },
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
    from runops.application.execution.submission import (
        SubmissionClaimError,
        SubmissionLockError,
        submission_guard,
    )
    from runops.application.experiments import experiment_lock
    from runops.application.run_namespace import run_namespace_guard
    from runops.core.exceptions import ProjectNotFoundError
    from runops.core.manifest import read_manifest
    from runops.core.project import find_project_root
    from runops.slurm.query import SlurmQueryError, query_job_status

    manifest = read_manifest(run_dir)
    run_id = str(manifest.run.get("id", run_dir.name))
    job_id = str(manifest.job.get("job_id", "") or "")
    if not job_id:
        return _precondition_fail("sync_run", "No job_id recorded in manifest")

    _, err = _require_state(run_dir, RunState.SUBMITTED, RunState.RUNNING)
    if err:
        return _precondition_fail("sync_run", err)

    try:
        job_status = query_job_status(job_id)
    except (SlurmQueryError, RuntimeError) as e:
        return _error("sync_run", f"Slurm query failed: {e}")

    new_state = job_status.run_state
    project_root: Path | None = None
    if new_state is RunState.COMPLETED:
        try:
            project_root = find_project_root(run_dir)
        except ProjectNotFoundError:
            project_root = None

    # Scheduler I/O stays outside the locks.  The observed result is persisted
    # only after taking the same global order used by managed clone, extend,
    # and retry: Experiment -> per-Run submission -> Run namespace.  In
    # particular, the namespace guard makes a completion (and therefore a new
    # unreviewed backlog item) linearizable with formal Run admission scans.
    try:
        if project_root is not None:
            with (
                experiment_lock(project_root),
                submission_guard(run_dir),
                run_namespace_guard(project_root),
            ):
                persisted = _persist_slurm_observation(
                    run_dir,
                    expected_run_id=run_id,
                    expected_job_id=job_id,
                    new_state=new_state,
                    slurm_state=job_status.slurm_state,
                    failure_reason=job_status.failure_reason,
                )
        else:
            with submission_guard(run_dir):
                persisted = _persist_slurm_observation(
                    run_dir,
                    expected_run_id=run_id,
                    expected_job_id=job_id,
                    new_state=new_state,
                    slurm_state=job_status.slurm_state,
                    failure_reason=job_status.failure_reason,
                )
    except (SubmissionClaimError, SubmissionLockError) as e:
        return _error("sync_run", f"State synchronization guard failed: {e}")
    except SimctlError as e:
        return _error("sync_run", f"State update failed: {e}")

    stale_result, run_id, state_before, state_after = persisted
    if stale_result is not None:
        return stale_result

    data: dict[str, Any] = {
        "run_id": run_id,
        "slurm_state": job_status.slurm_state,
    }
    if state_before != state_after:
        data.update(
            {
                "failure_reason": job_status.failure_reason,
                "exit_code": job_status.exit_code,
            }
        )
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

    if state_before == state_after:
        message = f"State unchanged: {state_before}"
    else:
        message = f"State: {state_before} -> {state_after}"

    return ActionResult(
        action="sync_run",
        status=ActionStatus.SUCCESS,
        message=message,
        data=data,
        state_before=state_before,
        state_after=state_after,
    )


def _persist_slurm_observation(
    run_dir: Path,
    *,
    expected_run_id: str,
    expected_job_id: str,
    new_state: RunState,
    slurm_state: str,
    failure_reason: str,
) -> tuple[ActionResult | None, str, str, str]:
    """Revalidate and persist one scheduler observation while locks are held."""
    from runops.core.manifest import read_manifest, update_manifest
    from runops.core.state import update_state

    current = read_manifest(run_dir)
    current_run_id = str(current.run.get("id", run_dir.name))
    current_job_id = str(current.job.get("job_id", "") or "")
    current_state_value = str(current.run.get("status", ""))
    if current_run_id != expected_run_id:
        return (
            _precondition_fail(
                "sync_run",
                "Run identity changed after Slurm query: "
                f"{expected_run_id!r} -> {current_run_id!r}",
            ),
            current_run_id,
            current_state_value,
            current_state_value,
        )
    if current_job_id != expected_job_id:
        return (
            _precondition_fail(
                "sync_run",
                "Run job_id changed after Slurm query: "
                f"{expected_job_id!r} -> {current_job_id!r}",
            ),
            current_run_id,
            current_state_value,
            current_state_value,
        )

    try:
        current_state = RunState(current_state_value)
    except ValueError:
        return (
            _precondition_fail(
                "sync_run",
                f"Unknown run state after Slurm query: {current_state_value!r}",
            ),
            current_run_id,
            current_state_value,
            current_state_value,
        )

    if current_state is new_state:
        update_manifest(
            run_dir,
            {"run": {"last_slurm_state": slurm_state}},
        )
        return None, current_run_id, current_state.value, current_state.value

    if current_state not in {RunState.SUBMITTED, RunState.RUNNING}:
        return (
            _precondition_fail(
                "sync_run",
                "Run state changed after Slurm query: "
                f"{current_state.value!r}; requires submitted or running",
            ),
            current_run_id,
            current_state.value,
            current_state.value,
        )

    update_state(
        run_dir,
        new_state,
        reconcile=True,
        reason=failure_reason,
        slurm_state=slurm_state,
    )
    return None, current_run_id, current_state.value, new_state.value


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
    from runops.application.experiments import experiment_lock, resolve_experiment
    from runops.application.run_budget import (
        declared_manifest_core_hours,
        enforce_project_unreviewed_completed_budget,
        persist_manifest_budget_usage,
        reserve_experiment_retry_budget,
    )
    from runops.application.run_creation import build_standalone_manifest_metadata
    from runops.application.run_namespace import run_namespace_guard
    from runops.core.experiment import load_experiment
    from runops.core.manifest import read_manifest
    from runops.core.project import find_project_root, load_project
    from runops.core.state import reset_state_for_retry

    state_str, err = _require_state(run_dir, RunState.FAILED, RunState.CANCELLED)
    if err:
        return _precondition_fail("retry_run", err)

    manifest = read_manifest(run_dir)
    attempt = get_attempt_count(manifest.job)
    raw_budget_attempts = manifest.job.get("budget_attempts", [])
    budget_attempts = (
        list(raw_budget_attempts) if isinstance(raw_budget_attempts, list) else []
    )
    if attempt + 1 not in budget_attempts:
        budget_attempts.append(attempt + 1)
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
                "budget_attempts": budget_attempts,
            },
        )

    budget_warning = ""
    try:
        experiment_id = str(manifest.intent.get("experiment_id", "")).strip()
        if experiment_id:
            project_root = find_project_root(run_dir)
            project = load_project(project_root)
            with experiment_lock(project_root):
                experiment = load_experiment(
                    resolve_experiment(project_root, experiment_id)
                )

                def budget_preflight() -> None:
                    refreshed = read_manifest(run_dir)
                    if (
                        str(refreshed.intent.get("experiment_id", "")).strip()
                        != experiment_id
                        or get_attempt_count(refreshed.job) != attempt
                    ):
                        raise SimctlError(
                            "Run identity or attempt changed while acquiring retry "
                            "transaction locks"
                        )
                    purpose = str(refreshed.intent.get("purpose", ""))
                    build_standalone_manifest_metadata(
                        project,
                        experiment_id=experiment_id,
                        purpose=purpose,
                        created_by="retry",
                    )
                    reserve_experiment_retry_budget(
                        project,
                        experiment,
                        manifest=refreshed,
                        next_attempt=attempt + 1,
                        persist=False,
                    )

                def resetter_and_commit_budget() -> RunState:
                    nonlocal budget_warning
                    reset_state = resetter()
                    try:
                        persist_manifest_budget_usage(
                            project_root,
                            run_dir,
                            read_manifest(run_dir),
                        )
                    except SimctlError as exc:
                        budget_warning = (
                            "retry reset committed; Experiment usage ledger will be "
                            f"rebuilt from the Run manifest ({exc})"
                        )
                    return reset_state

                reset_retry_under_submission_lock(
                    run_dir,
                    resetter_and_commit_budget,
                    mutation_guard=run_namespace_guard(project_root),
                    preflight=budget_preflight,
                )
        else:
            try:
                project_root = find_project_root(run_dir)
            except SimctlError:
                reset_retry_under_submission_lock(run_dir, resetter)
            else:
                with experiment_lock(project_root):

                    def ownerless_budget_preflight() -> None:
                        refreshed = read_manifest(run_dir)
                        if (
                            str(refreshed.intent.get("experiment_id", "")).strip()
                            or get_attempt_count(refreshed.job) != attempt
                        ):
                            raise SimctlError(
                                "Run identity or attempt changed while acquiring "
                                "retry transaction locks"
                            )
                        current_project = load_project(project_root)
                        build_standalone_manifest_metadata(
                            current_project,
                            experiment_id="",
                            purpose=str(refreshed.intent.get("purpose", "")),
                            created_by="retry",
                        )
                        declared_manifest_core_hours(refreshed)
                        enforce_project_unreviewed_completed_budget(current_project)

                    reset_retry_under_submission_lock(
                        run_dir,
                        resetter,
                        mutation_guard=run_namespace_guard(project_root),
                        preflight=ownerless_budget_preflight,
                    )
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
            "warnings": [budget_warning] if budget_warning else [],
        },
        state_before=state_str,
        state_after=RunState.CREATED.value,
    )
