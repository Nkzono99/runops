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
    from runops.core.context import build_project_context

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

        sims = ctx.get("simulators", [])
        if sims:
            typer.echo(f"Simulators: {', '.join(sims)}")

        runs = ctx.get("runs", {})
        if runs.get("total", 0) > 0:
            parts = [f"{k}={v}" for k, v in runs.items()]
            typer.echo(f"Runs: {', '.join(parts)}")

        failures = ctx.get("recent_failures", [])
        if failures:
            typer.echo(f"Recent failures ({len(failures)}):")
            for f in failures:
                typer.echo(f"  {f['run_id']}: {f['reason']}")
