"""Slurm inspection and submission-planning tools for the runops MCP server."""

from __future__ import annotations

from typing import Any

from runops.application.execution.submission import SubmitRequest, plan_submit
from runops.core.discovery import discover_runs
from runops.core.exceptions import SimctlError
from runops.core.manifest import read_manifest
from runops.core.state import RunState
from runops.mcp._tools.common import (
    _resolve_project_root,
    _resolve_run_dir,
    _tool_start,
)
from runops.mcp.registry import tool_spec
from runops.mcp.schemas import blocked_envelope, envelope, error, warning
from runops.slurm.query import SlurmQueryError, query_job_status
from runops.slurm.submit import SlurmNotFoundError


def slurm_queue(
    project_root: str | None = None,
    all_states: bool = False,
    live: bool = False,
) -> dict[str, Any]:
    """List Slurm job records known to project manifests."""
    started_at, started_perf = _tool_start()
    spec = tool_spec("runops.slurm.queue")
    inputs = {"project_root": project_root, "all_states": all_states, "live": live}
    try:
        root = _resolve_project_root(project_root)
        run_dirs = discover_runs(root / "runs")
    except SimctlError as exc:
        return blocked_envelope(
            tool=spec.name,
            safety=spec.safety,
            code="slurm_queue_failed",
            message=str(exc),
            inputs=inputs,
        )

    active_states = {RunState.SUBMITTED.value, RunState.RUNNING.value}
    jobs: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for run_dir in run_dirs:
        try:
            manifest = read_manifest(run_dir)
        except SimctlError:
            continue
        run_status = str(manifest.run.get("status", "unknown"))
        job_id = str(manifest.job.get("job_id", ""))
        if not all_states and run_status not in active_states:
            continue
        if not job_id and not all_states:
            continue
        job: dict[str, Any] = {
            "job_id": job_id,
            "run_id": str(manifest.run.get("id", run_dir.name)),
            "run_status": run_status,
            "run_dir": str(run_dir),
            "submitted_at": str(manifest.job.get("submitted_at", "")),
            "partition": str(
                manifest.job.get("partition", manifest.job.get("queue", ""))
            ),
            "qos": str(manifest.job.get("qos", "")),
            "last_slurm_state": str(manifest.run.get("last_slurm_state", "")),
        }
        if live and job_id:
            try:
                live_status = query_job_status(job_id)
                job["live_slurm_state"] = live_status.slurm_state
                job["live_run_state"] = live_status.run_state.value
            except (SlurmNotFoundError, SlurmQueryError) as exc:
                warnings.append(
                    warning(
                        "slurm_query_failed",
                        f"{job_id}: {exc}",
                        severity="medium",
                    )
                )
        jobs.append(job)

    jobs.sort(key=lambda item: str(item["run_id"]))
    active = sum(1 for job in jobs if job["run_status"] in active_states)
    return envelope(
        tool=spec.name,
        safety=spec.safety,
        status="warning" if warnings else "ok",
        summary=f"{active} active job(s), {len(jobs)} listed.",
        data={"jobs": jobs, "active_count": active, "total_listed": len(jobs)},
        project_root=root,
        warnings=warnings,
        started_at=started_at,
        started_perf=started_perf,
        inputs=inputs,
    )


def slurm_job_inspect(job_id: str) -> dict[str, Any]:
    """Inspect a Slurm job through squeue/sacct."""
    started_at, started_perf = _tool_start()
    spec = tool_spec("runops.slurm.job.inspect")
    inputs = {"job_id": job_id}
    try:
        job_status = query_job_status(job_id)
    except (SlurmNotFoundError, SlurmQueryError) as exc:
        return blocked_envelope(
            tool=spec.name,
            safety=spec.safety,
            code="slurm_job_query_failed",
            message=str(exc),
            inputs=inputs,
        )

    return envelope(
        tool=spec.name,
        safety=spec.safety,
        status="ok",
        summary=f"Job {job_id} is {job_status.slurm_state}.",
        data={
            "job_id": job_id,
            "slurm_state": job_status.slurm_state,
            "run_state": job_status.run_state.value,
            "failure_reason": job_status.failure_reason,
            "exit_code": job_status.exit_code,
        },
        started_at=started_at,
        started_perf=started_perf,
        inputs=inputs,
    )


def job_plan_submit(
    run: str,
    project_root: str | None = None,
    queue_name: str | None = None,
    qos: str | None = None,
    afterok: str | None = None,
) -> dict[str, Any]:
    """Plan an sbatch submission command without submitting it."""
    started_at, started_perf = _tool_start()
    spec = tool_spec("runops.job.plan_submit")
    inputs = {
        "run": run,
        "project_root": project_root,
        "queue_name": queue_name,
        "qos": qos,
        "afterok": afterok,
    }
    try:
        root = _resolve_project_root(project_root)
        run_dir = _resolve_run_dir(run, root)
        plan = plan_submit(
            SubmitRequest(
                run_dir=run_dir,
                queue_name=queue_name or "",
                qos=qos or "",
                afterok=afterok or "",
            )
        )
    except SimctlError as exc:
        return blocked_envelope(
            tool=spec.name,
            safety=spec.safety,
            code="plan_submit_failed",
            message=str(exc),
            inputs=inputs,
        )

    preconditions = [
        {"name": check.name, "ok": check.passed, "message": check.message}
        for check in plan.preconditions
    ]
    data = {
        "run_id": plan.run_id,
        "run_dir": str(plan.run_dir),
        "job_script": str(plan.job_script),
        "work_dir": str(plan.work_dir),
        "command": list(plan.command),
        "preconditions": preconditions,
        "dry_run": True,
        "will_submit": plan.ready,
    }
    if not plan.ready:
        return envelope(
            tool=spec.name,
            safety=spec.safety,
            status="blocked",
            summary=(
                "Submission plan is blocked by "
                f"{len(plan.failed_preconditions)} precondition(s)."
            ),
            data=data,
            project_root=root,
            errors=[
                error(
                    "precondition_failed",
                    f"{check.name}: {check.message}",
                )
                for check in plan.failed_preconditions
            ],
            started_at=started_at,
            started_perf=started_perf,
            inputs=inputs,
        )

    return envelope(
        tool=spec.name,
        safety=spec.safety,
        status="ok",
        summary=f"Run {plan.run_id} is ready to submit.",
        data=data,
        project_root=root,
        next_actions=[
            {
                "title": "Submit the planned job",
                "kind": "apply",
                "tool": "runops.job.submit",
                "arguments": {
                    "run": plan.run_id,
                    "confirm": True,
                    "dry_run": False,
                },
                "requires_user": True,
            }
        ],
        started_at=started_at,
        started_perf=started_perf,
        inputs=inputs,
    )
