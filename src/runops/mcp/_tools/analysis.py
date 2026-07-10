"""Analysis artifact and survey tools for the runops MCP server."""

from __future__ import annotations

import json
import sys
from typing import Any

from runops.application.analysis.artifacts import read_artifacts_index
from runops.core.exceptions import SimctlError
from runops.mcp._tools.common import (
    _artifact_payload,
    _load_json_object,
    _relative_or_absolute,
    _resolve_project_root,
    _resolve_run_or_survey_target,
    _resolve_survey_dir,
    _safe_limit,
    _survey_plot_columns_from_aggregate,
    _tool_start,
)
from runops.mcp.registry import tool_spec
from runops.mcp.schemas import blocked_envelope, envelope, error, warning

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


def analysis_artifacts(
    target: str,
    project_root: str | None = None,
    kind: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Inspect run or survey analysis artifact rows without collecting outputs."""
    started_at, started_perf = _tool_start()
    spec = tool_spec("runops.analysis.artifacts")
    inputs = {
        "target": target,
        "project_root": project_root,
        "kind": kind,
        "limit": limit,
    }
    try:
        root = _resolve_project_root(project_root)
        target_kind, target_dir = _resolve_run_or_survey_target(target, root)
    except SimctlError as exc:
        return blocked_envelope(
            tool=spec.name,
            safety=spec.safety,
            code="target_not_found",
            message=str(exc),
            inputs=inputs,
        )

    if target_kind == "run":
        index_path = target_dir / "analysis" / "artifacts.toml"
        base_dir = target_dir / "analysis"
    else:
        index_path = target_dir / "summary" / "artifacts.toml"
        base_dir = target_dir / "summary"

    if not index_path.is_file():
        message = f"Artifact index not found: {_relative_or_absolute(index_path, root)}"
        return envelope(
            tool=spec.name,
            safety=spec.safety,
            status="warning",
            summary=message,
            data={
                "target_kind": target_kind,
                "target_path": _relative_or_absolute(target_dir, root),
                "artifacts": [],
                "matched_count": 0,
                "index_path": _relative_or_absolute(index_path, root),
            },
            project_root=root,
            warnings=[warning("artifacts_missing", message)],
            started_at=started_at,
            started_perf=started_perf,
            inputs=inputs,
        )

    try:
        raw_artifacts = read_artifacts_index(index_path)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        message = f"Invalid artifact index {index_path}: {exc}"
        return envelope(
            tool=spec.name,
            safety=spec.safety,
            status="warning",
            summary=message,
            data={"artifacts": [], "matched_count": 0},
            project_root=root,
            warnings=[warning("artifacts_invalid", message)],
            errors=[error("artifacts_invalid", message)],
            started_at=started_at,
            started_perf=started_perf,
            inputs=inputs,
        )

    normalized_kind = kind.strip() if kind else ""
    artifacts = [
        _artifact_payload(root, base_dir, item)
        for item in raw_artifacts
        if not normalized_kind or str(item.get("kind", "")) == normalized_kind
    ]
    safe_limit = _safe_limit(limit)
    clipped = artifacts[:safe_limit]
    warnings = []
    if len(artifacts) > len(clipped):
        warnings.append(
            warning(
                "result_limited",
                f"Returned {len(clipped)} of {len(artifacts)} artifacts.",
                severity="low",
            )
        )
    return envelope(
        tool=spec.name,
        safety=spec.safety,
        status="warning" if warnings else "ok",
        summary=f"{len(artifacts)} artifact(s) matched.",
        data={
            "target_kind": target_kind,
            "target_path": _relative_or_absolute(target_dir, root),
            "index_path": _relative_or_absolute(index_path, root),
            "artifacts": clipped,
            "matched_count": len(artifacts),
        },
        project_root=root,
        warnings=warnings,
        started_at=started_at,
        started_perf=started_perf,
        inputs=inputs,
    )


def survey_summary(
    survey: str,
    project_root: str | None = None,
    include_runs: bool = False,
    limit: int = 100,
) -> dict[str, Any]:
    """Inspect an existing survey_summary.json without collecting summaries."""
    started_at, started_perf = _tool_start()
    spec = tool_spec("runops.survey.summary")
    inputs = {
        "survey": survey,
        "project_root": project_root,
        "include_runs": include_runs,
        "limit": limit,
    }
    try:
        root = _resolve_project_root(project_root)
        survey_dir = _resolve_survey_dir(survey, root)
    except SimctlError as exc:
        return blocked_envelope(
            tool=spec.name,
            safety=spec.safety,
            code="survey_not_found",
            message=str(exc),
            inputs=inputs,
        )

    summary_path = survey_dir / "summary" / "survey_summary.json"
    if not summary_path.is_file():
        message = (
            f"Survey summary not found: {_relative_or_absolute(summary_path, root)}"
        )
        return envelope(
            tool=spec.name,
            safety=spec.safety,
            status="warning",
            summary=message,
            data={
                "survey_path": _relative_or_absolute(survey_dir, root),
                "summary_path": _relative_or_absolute(summary_path, root),
                "runs": [],
            },
            project_root=root,
            warnings=[warning("survey_summary_missing", message)],
            started_at=started_at,
            started_perf=started_perf,
            inputs=inputs,
        )

    try:
        aggregate = _load_json_object(summary_path)
    except (OSError, json.JSONDecodeError, SimctlError) as exc:
        message = f"Invalid survey summary {summary_path}: {exc}"
        return envelope(
            tool=spec.name,
            safety=spec.safety,
            status="warning",
            summary=message,
            data={"runs": []},
            project_root=root,
            warnings=[warning("survey_summary_invalid", message)],
            errors=[error("survey_summary_invalid", message)],
            started_at=started_at,
            started_perf=started_perf,
            inputs=inputs,
        )

    runs = aggregate.get("runs", [])
    if not isinstance(runs, list):
        runs = []
    safe_limit = _safe_limit(limit)
    summary_warnings = aggregate.get("warnings", [])
    if not isinstance(summary_warnings, list):
        summary_warnings = []
    warnings = [
        warning("survey_summary_warning", str(item), severity="low")
        for item in summary_warnings
    ]
    data = {
        "survey_path": _relative_or_absolute(survey_dir, root),
        "summary_path": _relative_or_absolute(summary_path, root),
        "total_runs": aggregate.get("total_runs", len(runs)),
        "summaries_collected": aggregate.get("summaries_collected", 0),
        "missing_summaries": aggregate.get("missing_summaries", 0),
        "state_counts": aggregate.get("state_counts", {}),
        "readiness_counts": aggregate.get("readiness_counts", {}),
        "numeric_stats": aggregate.get("numeric_stats", {}),
        "readiness_issues": aggregate.get("readiness_issues", []),
        "warning_count": len(summary_warnings),
        "run_count": len(runs),
    }
    if include_runs:
        data["runs"] = runs[:safe_limit]
        if len(runs) > safe_limit:
            warnings.append(
                warning(
                    "result_limited",
                    f"Returned {safe_limit} of {len(runs)} survey runs.",
                    severity="low",
                )
            )
    return envelope(
        tool=spec.name,
        safety=spec.safety,
        status="warning" if warnings else "ok",
        summary=f"Survey summary has {len(runs)} run row(s).",
        data=data,
        project_root=root,
        warnings=warnings,
        started_at=started_at,
        started_perf=started_perf,
        inputs=inputs,
    )


def analysis_plot_columns(
    survey: str,
    project_root: str | None = None,
) -> dict[str, Any]:
    """List plot columns from an existing survey_summary.json without collecting."""
    started_at, started_perf = _tool_start()
    spec = tool_spec("runops.analysis.plot_columns")
    inputs = {"survey": survey, "project_root": project_root}
    try:
        root = _resolve_project_root(project_root)
        survey_dir = _resolve_survey_dir(survey, root)
    except SimctlError as exc:
        return blocked_envelope(
            tool=spec.name,
            safety=spec.safety,
            code="survey_not_found",
            message=str(exc),
            inputs=inputs,
        )

    summary_path = survey_dir / "summary" / "survey_summary.json"
    if not summary_path.is_file():
        message = (
            f"Survey summary not found: {_relative_or_absolute(summary_path, root)}"
        )
        return envelope(
            tool=spec.name,
            safety=spec.safety,
            status="warning",
            summary=message,
            data={"columns": []},
            project_root=root,
            warnings=[warning("survey_summary_missing", message)],
            started_at=started_at,
            started_perf=started_perf,
            inputs=inputs,
        )

    try:
        aggregate = _load_json_object(summary_path)
    except (OSError, json.JSONDecodeError, SimctlError) as exc:
        message = f"Invalid survey summary {summary_path}: {exc}"
        return envelope(
            tool=spec.name,
            safety=spec.safety,
            status="warning",
            summary=message,
            data={"columns": []},
            project_root=root,
            warnings=[warning("survey_summary_invalid", message)],
            errors=[error("survey_summary_invalid", message)],
            started_at=started_at,
            started_perf=started_perf,
            inputs=inputs,
        )

    columns = _survey_plot_columns_from_aggregate(aggregate)
    return envelope(
        tool=spec.name,
        safety=spec.safety,
        status="ok",
        summary=f"{len(columns)} plot column(s) available.",
        data={
            "survey_path": _relative_or_absolute(survey_dir, root),
            "summary_path": _relative_or_absolute(summary_path, root),
            "columns": columns,
        },
        project_root=root,
        started_at=started_at,
        started_perf=started_perf,
        inputs=inputs,
    )
