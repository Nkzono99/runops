"""Read-only Experiment and Survey admission tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from runops.application.survey_materialization import preview_survey_plan
from runops.core.exceptions import SimctlError
from runops.core.experiment import discover_experiments
from runops.core.project import load_project
from runops.mcp._tools.common import _resolve_project_root, _tool_start
from runops.mcp.registry import tool_spec
from runops.mcp.schemas import blocked_envelope, envelope


def experiment_list(
    project_root: str | None = None,
    lifecycle: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """List bounded Experiment admission units without inspecting Run trees."""
    started_at, started_perf = _tool_start()
    spec = tool_spec("runops.experiment.list")
    inputs = {
        "project_root": project_root,
        "lifecycle": lifecycle,
        "limit": limit,
    }
    try:
        root = _resolve_project_root(project_root)
        experiments = discover_experiments(root)
    except SimctlError as exc:
        return blocked_envelope(
            tool=spec.name,
            safety=spec.safety,
            code="experiment_list_failed",
            message=str(exc),
            inputs=inputs,
        )
    if lifecycle:
        experiments = tuple(item for item in experiments if item.lifecycle == lifecycle)
    rows = [
        {
            "id": item.id,
            "title": item.title,
            "question": item.question,
            "lifecycle": item.lifecycle,
            "intent": item.intent,
            "decision": item.decision,
            "outcome": item.outcome,
            "path": item.experiment_file.relative_to(root).as_posix(),
            "budget": {
                "max_planned_points": item.budget.max_planned_points,
                "max_materialized_runs": item.budget.max_materialized_runs,
                "max_active_runs": item.budget.max_active_runs,
                "max_core_hours": item.budget.max_core_hours,
                "max_unreviewed_runs": item.budget.max_unreviewed_runs,
                "expires_at": item.budget.expires_at,
            },
        }
        for item in experiments[: max(0, min(limit, 1000))]
    ]
    return envelope(
        tool=spec.name,
        safety=spec.safety,
        status="ok",
        summary=f"{len(experiments)} Experiment(s) matched.",
        data={"experiments": rows, "matched_count": len(experiments)},
        project_root=root,
        started_at=started_at,
        started_perf=started_perf,
        inputs=inputs,
    )


def survey_plan(
    survey: str,
    project_root: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> dict[str, Any]:
    """Preview lazy Survey candidates without allocating IDs or directories."""
    started_at, started_perf = _tool_start()
    spec = tool_spec("runops.survey.plan")
    inputs = {
        "survey": survey,
        "project_root": project_root,
        "offset": offset,
        "limit": limit,
    }
    try:
        root = _resolve_project_root(project_root)
        survey_dir = _resolve_survey_dir(root, survey)
        preview = preview_survey_plan(
            load_project(root),
            survey_dir,
            offset=offset,
            limit=limit,
        )
    except (OSError, SimctlError, ValueError) as exc:
        return blocked_envelope(
            tool=spec.name,
            safety=spec.safety,
            code="survey_plan_failed",
            message=str(exc),
            inputs=inputs,
        )
    plan = preview.plan
    return envelope(
        tool=spec.name,
        safety=spec.safety,
        status="ok",
        summary=(f"Planned {plan.candidate_count} candidates; no directories created."),
        data={
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
        project_root=root,
        started_at=started_at,
        started_perf=started_perf,
        inputs=inputs,
    )


def _resolve_survey_dir(project_root: Path, value: str) -> Path:
    raw = Path(value).expanduser()
    candidates = (
        (raw,)
        if raw.is_absolute()
        else (project_root / raw, project_root / "runs" / raw)
    )
    for candidate in candidates:
        if candidate.is_symlink():
            raise SimctlError(f"Survey path must not be a symlink: {candidate}")
        resolved = candidate.resolve()
        try:
            resolved.relative_to(project_root)
        except ValueError:
            continue
        if (resolved / "survey.toml").is_file():
            return resolved
    raise SimctlError(f"Survey directory not found inside project: {value}")


__all__ = ["experiment_list", "survey_plan"]
