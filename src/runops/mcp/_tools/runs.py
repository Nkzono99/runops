"""Run inspection tools for the runops MCP server."""

from __future__ import annotations

from collections import Counter
from typing import Any

from runops.application.execution.readiness import (
    readiness_for_bulk_view,
    resolve_run_readiness,
)
from runops.core.discovery import discover_runs
from runops.core.exceptions import SimctlError
from runops.core.manifest import read_manifest
from runops.core.state import RunState
from runops.mcp._tools.common import (
    _find_latest_log,
    _resolve_project_root,
    _resolve_run_dir,
    _run_summary,
    _tail_text,
    _tool_start,
)
from runops.mcp.registry import tool_spec
from runops.mcp.schemas import blocked_envelope, envelope, warning


def run_list(
    project_root: str | None = None,
    status_filter: str | None = None,
    tag: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    """List runs under a project."""
    started_at, started_perf = _tool_start()
    spec = tool_spec("runops.run.list")
    inputs = {
        "project_root": project_root,
        "status_filter": status_filter,
        "tag": tag,
        "limit": limit,
    }
    try:
        root = _resolve_project_root(project_root)
        run_dirs = discover_runs(root / "runs")
    except SimctlError as exc:
        return blocked_envelope(
            tool=spec.name,
            safety=spec.safety,
            code="run_list_failed",
            message=str(exc),
            inputs=inputs,
        )

    rows: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    readiness_counts: Counter[str] = Counter()
    for run_dir in run_dirs:
        try:
            manifest = read_manifest(run_dir)
        except SimctlError:
            continue
        summary = _run_summary(run_dir, manifest, root)
        counts[str(summary["status"])] += 1
        readiness = readiness_for_bulk_view(run_dir, manifest=manifest)
        if readiness is not None:
            summary["readiness"] = readiness.to_summary_dict()
            readiness_counts[readiness.analysis_status] += 1
        if status_filter and summary["status"] != status_filter:
            continue
        if tag and tag not in summary["tags"]:
            continue
        rows.append(summary)

    rows.sort(key=lambda item: str(item["run_id"]))
    clipped = rows[: max(limit, 0)]
    warnings = []
    if len(rows) > len(clipped):
        warnings.append(
            warning(
                "result_limited",
                f"Returned {len(clipped)} of {len(rows)} matching runs.",
                severity="low",
            )
        )
    return envelope(
        tool=spec.name,
        safety=spec.safety,
        status="ok",
        summary=f"{len(rows)} run(s) matched.",
        data={
            "runs": clipped,
            "matched_count": len(rows),
            "total_count": len(run_dirs),
            "state_counts": dict(counts),
            "readiness_counts": dict(readiness_counts),
        },
        project_root=root,
        warnings=warnings,
        started_at=started_at,
        started_perf=started_perf,
        inputs=inputs,
    )


def run_inspect(run: str, project_root: str | None = None) -> dict[str, Any]:
    """Inspect one run."""
    started_at, started_perf = _tool_start()
    spec = tool_spec("runops.run.inspect")
    inputs = {"run": run, "project_root": project_root}
    try:
        root = _resolve_project_root(project_root)
        run_dir = _resolve_run_dir(run, root)
        manifest = read_manifest(run_dir)
    except SimctlError as exc:
        return blocked_envelope(
            tool=spec.name,
            safety=spec.safety,
            code="run_inspect_failed",
            message=str(exc),
            inputs=inputs,
        )

    readiness: dict[str, Any] | None = None
    if manifest.run.get("status") == RunState.COMPLETED.value:
        try:
            details = resolve_run_readiness(run_dir, manifest=manifest)
            readiness = {
                "analysis_status": details.analysis_status,
                "analysis_ready": details.analysis_ready,
                "missing_required_artifacts": list(details.missing_required_artifacts),
                "warnings": list(details.warnings),
                "reason_codes": list(details.reason_codes),
                "recommended_action": details.recommended_action,
                "recommended_command": details.recommended_command,
                "requires_human": details.requires_human,
                "evaluation_mode": details.evaluation_mode,
            }
        except SimctlError:
            readiness = None

    return envelope(
        tool=spec.name,
        safety=spec.safety,
        status="ok",
        summary=f"Run {manifest.run.get('id', run_dir.name)} inspected.",
        data={
            "run": _run_summary(run_dir, manifest, root),
            "manifest": manifest.to_dict(),
            "readiness": readiness,
        },
        project_root=root,
        started_at=started_at,
        started_perf=started_perf,
        inputs=inputs,
    )


def run_logs(
    run: str,
    project_root: str | None = None,
    lines: int = 50,
    stderr: bool = False,
) -> dict[str, Any]:
    """Return tail lines from the latest run log."""
    started_at, started_perf = _tool_start()
    spec = tool_spec("runops.run.logs")
    inputs = {
        "run": run,
        "project_root": project_root,
        "lines": lines,
        "stderr": stderr,
    }
    try:
        root = _resolve_project_root(project_root)
        run_dir = _resolve_run_dir(run, root)
        manifest = read_manifest(run_dir)
    except SimctlError as exc:
        return blocked_envelope(
            tool=spec.name,
            safety=spec.safety,
            code="run_logs_failed",
            message=str(exc),
            inputs=inputs,
        )

    job_id = str(manifest.job.get("job_id", ""))
    if stderr:
        patterns = [f"stderr.{job_id}.log", f"*.{job_id}.err", "*.err", "stderr*"]
        stream = "stderr"
    else:
        patterns = [
            f"stdout.{job_id}.log",
            f"*.{job_id}.out",
            "*.out",
            "stdout*",
            "*.log",
        ]
        stream = "stdout"
    log_file = _find_latest_log(run_dir / "work", patterns)
    if log_file is None:
        return blocked_envelope(
            tool=spec.name,
            safety=spec.safety,
            code="log_not_found",
            message=(
                f"No {stream} log found for {manifest.run.get('id', run_dir.name)}."
            ),
            project_root=root,
            inputs=inputs,
        )

    safe_lines = max(1, min(lines, 500))
    try:
        tail = _tail_text(log_file, safe_lines)
    except OSError as exc:
        return blocked_envelope(
            tool=spec.name,
            safety=spec.safety,
            code="log_read_failed",
            message=str(exc),
            project_root=root,
            inputs=inputs,
        )

    return envelope(
        tool=spec.name,
        safety=spec.safety,
        status="ok",
        summary=f"Last {len(tail)} line(s) from {log_file.name}.",
        data={
            "run_id": str(manifest.run.get("id", run_dir.name)),
            "stream": stream,
            "log_file": str(log_file),
            "lines": tail,
        },
        project_root=root,
        started_at=started_at,
        started_perf=started_perf,
        inputs=inputs,
    )
