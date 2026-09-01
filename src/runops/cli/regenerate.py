"""CLI command for inspecting case-template drift of an immutable Run."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Optional

import typer

from runops.application.actions import ActionStatus, execute_action
from runops.cli.run_lookup import resolve_run_or_cwd


def regenerate(
    run: Annotated[
        Optional[str],
        typer.Argument(help="Run directory or run_id (defaults to cwd)."),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Inspect the file-level diff without mutating immutable input/.",
        ),
    ] = False,
) -> None:
    """Inspect recorded case drift; in-place regeneration is disabled.

    A formal Run's ``input/`` and scientific identity are frozen. Pass
    ``--dry-run`` to compare the recorded input with the current case template.
    To apply a parameter change, derive a new Run with ``runs clone --set``.
    """
    run_dir = resolve_run_or_cwd(run, search_dir=Path.cwd())
    result = execute_action(
        "inspect_regeneration",
        run_dir=run_dir,
        dry_run=dry_run,
    )
    if result.status is not ActionStatus.SUCCESS:
        typer.echo(f"Error: {result.message}", err=True)
        raise typer.Exit(code=1)

    _print_result(result.data)
    if bool(result.data.get("work_exists")):
        typer.echo(
            "\nWarning: work/ is non-empty — existing outputs may not "
            "correspond to the current case template.",
            err=True,
        )


def _print_result(data: dict[str, Any]) -> None:
    typer.echo(
        f"[dry-run] Would regenerate input for {data.get('run_id', '?')} "
        f"from case {data.get('case_name', '?')}"
    )
    if not bool(data.get("has_changes")):
        typer.echo("[dry-run] (no changes; input/ already matches the case template)")
        return

    for path in data.get("added", []):
        typer.echo(f"  + {path}")
    for path in data.get("modified", []):
        typer.echo(f"  ~ {path}")
    for path in data.get("removed", []):
        typer.echo(f"  - {path}")

    summary: list[str] = []
    for key, label in (
        ("added", "added"),
        ("modified", "modified"),
        ("removed", "removed"),
        ("unchanged", "unchanged"),
    ):
        values = data.get(key, [])
        if values:
            summary.append(f"{len(values)} {label}")
    typer.echo(f"  ({', '.join(summary)})")


__all__ = ["regenerate"]
