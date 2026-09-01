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

        research = ctx.get("research", {})
        if research.get("exists"):
            typer.echo(
                "Research: "
                f"current={research.get('current_chars', 0)} chars, "
                f"journal={research.get('journal_chars', 0)} chars, "
                f"active_results={research.get('active_result_count', 0)}, "
                f"status={'ok' if research.get('ok') else 'check required'}"
            )
            typer.echo(
                "Research guidance: "
                f"current_lines={research.get('current_lines', 0)}, "
                f"current_paths={research.get('current_path_references', 0)}, "
                "current_chronology="
                f"{research.get('current_chronological_headings', 0)}"
            )

        sims = ctx.get("simulators", [])
        if sims:
            typer.echo(f"Simulators: {', '.join(sims)}")

        runs = ctx.get("runs", {})
        if runs.get("namespace_available") is False or runs.get("total") is None:
            typer.echo("Runs: unavailable")
        elif runs.get("total", 0) > 0:
            parts = [
                f"{key}={value}"
                for key, value in runs.items()
                if key not in {"analysis_problems", "namespace_available"}
            ]
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
