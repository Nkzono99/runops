"""CLI for adding semantic labels to legacy run directories."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer

from runops.application.actions import (
    ActionStatus,
    plan_run_relabel,
    relabel_run,
)
from runops.cli.run_lookup import resolve_run_targets


def relabel(
    runs: Annotated[
        Optional[list[str]],
        typer.Argument(
            help=(
                "Run identifiers, run directories, or directories containing runs. "
                "Defaults to cwd."
            )
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Preview directory relabeling."),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip confirmation prompt."),
    ] = False,
) -> None:
    """Add ``--display-name`` labels to legacy inactive run directories."""
    targets = resolve_run_targets(runs, search_dir=Path.cwd())
    plans = [plan_run_relabel(target) for target in targets]
    eligible = [
        plan
        for plan in plans
        if plan.status is ActionStatus.SUCCESS and bool(plan.data.get("changed"))
    ]
    skipped = [plan for plan in plans if plan not in eligible]

    summary = (
        f"Found {len(targets)} run(s): {len(eligible)} to relabel, "
        f"{len(skipped)} skipped."
    )
    typer.echo(summary)
    for plan in eligible:
        typer.echo(
            f"  {plan.data['run_id']}: "
            f"{Path(str(plan.data['source_path'])).name} -> "
            f"{Path(str(plan.data['destination_path'])).name}"
        )
    for plan in skipped:
        run_id = str(plan.data.get("run_id", "?"))
        typer.echo(f"  Skip {run_id}: {plan.message}")

    if dry_run or not eligible:
        return
    noun = "directory" if len(eligible) == 1 else "directories"
    if not yes and not typer.confirm(
        f"Relabel {len(eligible)} inactive run {noun}?", default=False
    ):
        typer.echo("Cancelled.")
        return

    failures = 0
    for plan in eligible:
        result = relabel_run(Path(str(plan.data["source_path"])))
        if result.status is ActionStatus.SUCCESS:
            typer.echo(f"  {result.message}")
        else:
            failures += 1
            typer.echo(f"  Error: {result.message}", err=True)
    if failures:
        raise typer.Exit(code=1)
