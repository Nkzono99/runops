"""CLI command: runo context — project context bundle for agents."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from runops.core.project import find_project_root


def context(
    directory: Path = typer.Argument(
        Path("."),
        help="Project directory (default: cwd).",
        exists=True,
    ),
    output_json: bool = typer.Option(
        True,
        "--json/--no-json",
        help="Output as JSON (default: true).",
    ),
) -> None:
    """Show project context bundle (designed for AI agents)."""
    from runops.application.context import build_project_context

    root = find_project_root(directory)
    ctx = build_project_context(root)

    if output_json:
        typer.echo(json.dumps(ctx, indent=2, ensure_ascii=False))
    else:
        # Simple text summary
        proj = ctx.get("project", {})
        typer.echo(f"Project: {proj.get('name', '?')}")
        typer.echo(f"Root: {proj.get('root', '?')}")

        camp = ctx.get("campaign", {})
        if camp.get("hypothesis"):
            typer.echo(f"Hypothesis: {camp['hypothesis']}")

        agenda = ctx.get("research_agenda", {})
        if agenda.get("exists"):
            status = "template" if agenda.get("is_template") else "ready"
            typer.echo(
                "Research agenda: "
                f"{agenda.get('path', 'research/agenda.md')} "
                f"({status}, next_actions={agenda.get('next_actions_count', 0)})"
            )
            if agenda.get("current_decision"):
                typer.echo(f"Current decision: {agenda['current_decision']}")
        elif agenda:
            typer.echo(
                f"Research agenda: missing ({agenda.get('path', 'research/agenda.md')})"
            )

        notes = ctx.get("notes", {})
        if notes.get("latest_path"):
            typer.echo(f"Latest note: {notes['latest_path']}")

        sims = ctx.get("simulators", [])
        if sims:
            typer.echo(f"Simulators: {', '.join(sims)}")

        runs = ctx.get("runs", {})
        if runs.get("total", 0) > 0:
            parts = [f"{k}={v}" for k, v in runs.items() if k != "analysis_problems"]
            typer.echo(f"Runs: {', '.join(parts)}")
            analysis_problems = runs.get("analysis_problems", [])
            if analysis_problems:
                typer.echo(f"Analysis readiness issues ({len(analysis_problems)}):")
                for problem in analysis_problems:
                    warnings = problem.get("warnings", [])
                    summary = "; ".join(warnings) if warnings else "not ready"
                    typer.echo(f"  {problem.get('run_id', '?')}: {summary}")

        failures = ctx.get("recent_failures", [])
        if failures:
            typer.echo(f"Recent failures ({len(failures)}):")
            for f in failures:
                typer.echo(f"  {f['run_id']}: {f['reason']}")
