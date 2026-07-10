"""Log, analysis, collection, and publication-export actions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from runops.application.actions.helpers import (
    _error,
    _precondition_fail,
    _require_state,
)
from runops.application.actions.result import ActionResult, ActionStatus
from runops.core.event_log import logged_action
from runops.core.exceptions import SimctlError
from runops.core.state import RunState


@logged_action("show_log")
def show_log(run_dir: Path, *, lines: int = 50) -> ActionResult:
    """Read the latest job stdout log."""
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


@logged_action("summarize_run")
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
            "artifacts_path": (
                str(result.artifacts_path) if result.artifacts_path else ""
            ),
            "script_path": str(result.script_path) if result.script_path else "",
            "warnings": list(result.warnings),
        },
    )


@logged_action("collect_survey")
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
            "artifacts_path": str(result.artifacts_path),
            "report_path": str(result.report_path),
            "generated_summaries": result.generated_summaries,
            "missing_summaries": result.missing_summaries,
            "readiness_counts": result.readiness_counts,
            "readiness_issues": list(result.readiness_issues),
            "figure_count": len(result.figures),
            "artifact_count": len(result.artifacts),
            "warnings": list(result.warnings),
        },
    )


@logged_action("export_publication")
def export_publication(
    target_path: Path,
    paper_id: str,
    *,
    export_name: str = "",
    mode: str = "copy",
    include_figures: bool = True,
    include_plots: bool = True,
    paper_status: str = "",
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
            paper_status=paper_status,
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
