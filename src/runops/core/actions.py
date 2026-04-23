"""Action registry: normalized execution interface for AI agents.

Provides a fixed set of named actions with explicit input schemas,
preconditions, and structured results.  Unlike the CLI (designed for humans),
the action registry is designed for programmatic consumption where inputs
and outputs are typed dictionaries.

Each action wraps existing core functions -- no new domain logic lives here.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runops.core.action_admin import (
    archive_run as archive_run,
)
from runops.core.action_admin import (
    cancel_run as cancel_run,
)
from runops.core.action_admin import (
    delete_run as delete_run,
)
from runops.core.action_admin import (
    purge_work as purge_work,
)
from runops.core.action_helpers import (
    _error,
    _precondition_fail,
    _require_state,
)
from runops.core.action_knowledge import (
    add_fact as add_fact,
)
from runops.core.action_knowledge import (
    promote_fact as promote_fact,
)
from runops.core.action_knowledge import (
    save_insight as save_insight,
)
from runops.core.action_result import (
    ActionResult as ActionResult,
)
from runops.core.action_result import (
    ActionStatus as ActionStatus,
)
from runops.core.action_specs import (
    ACTION_SPECS as ACTION_SPECS,
)
from runops.core.action_specs import (
    ActionSpec as ActionSpec,
)
from runops.core.action_specs import (
    get_action_spec as get_action_spec,
)
from runops.core.action_specs import (
    list_actions as list_actions,
)
from runops.core.exceptions import SimctlError
from runops.core.state import RunState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Action implementations
# ---------------------------------------------------------------------------


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


def submit_run(
    run_dir: Path,
    *,
    queue_name: str = "",
    qos: str = "",
    afterok: str = "",
) -> ActionResult:
    """Submit a run to Slurm via sbatch."""
    from runops.core.manifest import read_manifest, update_manifest
    from runops.core.retry import get_attempt_count
    from runops.core.state import update_state
    from runops.slurm.submit import (
        SlurmNotFoundError,
        SlurmSubmitError,
        sbatch_submit,
    )

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

    if "#SBATCH" not in job_content:
        return _precondition_fail(
            "submit_run",
            "job.sh does not contain expected #SBATCH directives",
        )

    manifest = read_manifest(run_dir)
    run_id = manifest.run.get("id", run_dir.name)
    warnings: list[str] = []
    tags = manifest.classification.get("tags", [])
    if "production" in tags and manifest.simulator_source.get("git_dirty", False):
        warnings.append("production run submitted with dirty git working tree")

    work_dir = run_dir / "work"
    if not work_dir.is_dir():
        work_dir = run_dir

    extra_args: list[str] = []
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
    except (SlurmNotFoundError, SlurmSubmitError, FileNotFoundError, RuntimeError) as e:
        return _error("submit_run", f"sbatch failed: {e}")

    # Update manifest
    now = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
    attempt = get_attempt_count(manifest.job) + 1
    existing_attempts: list[dict[str, str]] = list(manifest.job.get("attempts", []))
    existing_attempts.append(
        {
            "job_id": job_id,
            "submitted_at": now,
            "attempt": str(attempt),
        }
    )
    update_manifest(
        run_dir,
        {
            "run": {
                "last_slurm_state": "",
            },
            "job": {
                "job_id": job_id,
                "submitted_at": now,
                "attempt": attempt,
                "attempts": existing_attempts,
                "queue": queue_name or manifest.job.get("queue", ""),
            },
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
            "attempt": attempt,
            "run_id": run_id,
            "warnings": warnings,
        },
        state_before=state_str,
        state_after=RunState.SUBMITTED.value,
    )


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

    return ActionResult(
        action="sync_run",
        status=ActionStatus.SUCCESS,
        message=f"State: {state_str} -> {new_state.value}",
        data={
            "run_id": run_id,
            "slurm_state": job_status.slurm_state,
            "failure_reason": job_status.failure_reason,
            "exit_code": job_status.exit_code,
        },
        state_before=state_str,
        state_after=new_state.value,
    )


def show_log(run_dir: Path, *, lines: int = 50) -> ActionResult:
    """Read the latest job stdout log."""
    # Look for common log file patterns
    work_dir = run_dir / "work"
    log_candidates = [
        *sorted(work_dir.glob("slurm-*.out"), reverse=True),
        *sorted(work_dir.glob("*.log"), reverse=True),
        *sorted(work_dir.glob("*.out"), reverse=True),
    ]

    if not log_candidates:
        return _precondition_fail("show_log", "No log files found in work/")

    log_file = log_candidates[0]
    try:
        all_lines = log_file.read_text(encoding="utf-8").splitlines()
        tail = all_lines[-lines:] if len(all_lines) > lines else all_lines
    except OSError as e:
        return _error("show_log", f"Failed to read log: {e}")

    return ActionResult(
        action="show_log",
        status=ActionStatus.SUCCESS,
        message=f"Last {len(tail)} lines from {log_file.name}",
        data={
            "log_file": str(log_file),
            "total_lines": len(all_lines),
            "lines": tail,
        },
    )


def summarize_run(run_dir: Path) -> ActionResult:
    """Generate an analysis summary for a completed run."""
    _state_str, err = _require_state(run_dir, RunState.COMPLETED)
    if err:
        return _precondition_fail("summarize_run", err)

    try:
        from runops.core.analysis import generate_run_summary

        result = generate_run_summary(run_dir)
    except (KeyError, OSError, TypeError, json.JSONDecodeError, SimctlError) as e:
        return _error("summarize_run", str(e))

    return ActionResult(
        action="summarize_run",
        status=ActionStatus.SUCCESS,
        message=f"Summary written to {result.summary_path}",
        data={
            "run_id": result.run_id,
            "summary": result.summary,
            "summary_path": str(result.summary_path),
            "script_path": str(result.script_path) if result.script_path else "",
            "warnings": list(result.warnings),
        },
    )


def collect_survey(survey_dir: Path) -> ActionResult:
    """Aggregate results across all runs in a survey directory."""
    from runops.core.discovery import discover_runs
    from runops.core.manifest import read_manifest

    run_dirs = discover_runs(survey_dir)
    if not run_dirs:
        return _precondition_fail("collect_survey", f"No runs found under {survey_dir}")

    summary: dict[str, int] = {s.value: 0 for s in RunState}
    run_data: list[dict[str, Any]] = []
    for rd in run_dirs:
        try:
            m = read_manifest(rd)
            state = m.run.get("status", "unknown")
            summary[state] = summary.get(state, 0) + 1
            run_data.append(
                {
                    "run_id": m.run.get("id", ""),
                    "status": state,
                    "display_name": m.run.get("display_name", ""),
                }
            )
        except SimctlError:
            continue

    if summary.get(RunState.COMPLETED.value, 0) == 0:
        return _precondition_fail(
            "collect_survey",
            f"No completed runs found under {survey_dir}",
        )

    try:
        from runops.core.analysis import collect_survey_summaries

        result = collect_survey_summaries(survey_dir)
    except (OSError, TypeError, json.JSONDecodeError, SimctlError) as e:
        return _error("collect_survey", str(e))

    return ActionResult(
        action="collect_survey",
        status=ActionStatus.SUCCESS,
        message=f"Collected {result.summaries_collected} summaries",
        data={
            "total_runs": len(run_data),
            "state_counts": {k: v for k, v in summary.items() if v > 0},
            "csv_path": str(result.csv_path),
            "json_path": str(result.json_path),
            "figures_path": str(result.figures_path),
            "report_path": str(result.report_path),
            "generated_summaries": result.generated_summaries,
            "missing_summaries": result.missing_summaries,
            "figure_count": len(result.figures),
            "warnings": list(result.warnings),
        },
    )


def export_publication(
    target_path: Path,
    paper_id: str,
    *,
    export_name: str = "",
    mode: str = "copy",
    include_figures: bool = True,
    include_plots: bool = True,
    force: bool = False,
) -> ActionResult:
    """Create a project-side publication export bundle."""
    from runops.core.publication import export_publication_bundle

    try:
        result = export_publication_bundle(
            target_path,
            paper_id=paper_id,
            name=export_name,
            mode=mode,
            include_figures=include_figures,
            include_plots=include_plots,
            force=force,
        )
    except SimctlError as e:
        return _error("export_publication", str(e))

    return ActionResult(
        action="export_publication",
        status=ActionStatus.SUCCESS,
        message=(
            f"Exported {result.target_kind} bundle for paper {paper_id!r} "
            f"to {result.export_dir}"
        ),
        data={
            "paper_id": result.paper_id,
            "export_name": result.export_name,
            "target_kind": result.target_kind,
            "target_path": str(result.target_path),
            "export_dir": str(result.export_dir),
            "manifest_path": str(result.manifest_path),
            "readme_path": str(result.readme_path),
            "mode": result.mode,
            "source_run_ids": list(result.source_run_ids),
            "file_count": len(result.files),
            "warnings": list(result.warnings),
        },
    )


def retry_run(
    run_dir: Path,
    *,
    adjustments: dict[str, Any] | None = None,
    reviewed_log: bool = False,
) -> ActionResult:
    """Resubmit a failed or cancelled run as a new attempt."""
    from runops.core.manifest import read_manifest
    from runops.core.retry import get_attempt_count
    from runops.core.state import reset_state_for_retry

    state_str, err = _require_state(run_dir, RunState.FAILED, RunState.CANCELLED)
    if err:
        return _precondition_fail("retry_run", err)

    manifest = read_manifest(run_dir)
    attempt = get_attempt_count(manifest.job)
    failure_reason = manifest.run.get("failure_reason", "")

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
        },
        state_before=state_str,
        state_after=RunState.CREATED.value,
    )


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

#: Map action name -> callable.
_DISPATCH: dict[str, Any] = {
    "create_run": create_run,
    "create_survey": create_survey,
    "submit_run": submit_run,
    "sync_run": sync_run,
    "show_log": show_log,
    "summarize_run": summarize_run,
    "collect_survey": collect_survey,
    "export_publication": export_publication,
    "retry_run": retry_run,
    "archive_run": archive_run,
    "purge_work": purge_work,
    "cancel_run": cancel_run,
    "delete_run": delete_run,
    "save_insight": save_insight,
    "add_fact": add_fact,
    "promote_fact": promote_fact,
}


def execute_action(name: str, **kwargs: Any) -> ActionResult:
    """Execute a named action with keyword arguments.

    This is the primary entry point for agents.

    Args:
        name: Action name (must be in ACTION_SPECS).
        **kwargs: Arguments matching the action's parameter spec.

    Returns:
        ActionResult with status, message, and data.
    """
    if name not in _DISPATCH:
        return ActionResult(
            action=name,
            status=ActionStatus.ERROR,
            message=f"Unknown action: {name!r}. Available: {sorted(_DISPATCH)}",
        )

    fn = _DISPATCH[name]
    try:
        result: ActionResult = fn(**kwargs)
        return result
    except TypeError as e:
        return ActionResult(
            action=name,
            status=ActionStatus.ERROR,
            message=f"Invalid arguments for {name}: {e}",
        )
    except Exception as e:
        logger.exception("Unexpected error in action %s", name)
        return ActionResult(
            action=name,
            status=ActionStatus.ERROR,
            message=f"Unexpected error: {e}",
        )
