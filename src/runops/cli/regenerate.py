"""CLI command for regenerating a run's input/ from its case template."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer

from runops.application.run_creation import RegenerateResult, regenerate_run
from runops.cli.run_lookup import resolve_run_or_cwd
from runops.core.exceptions import ProjectConfigError, SimctlError
from runops.core.project import find_project_root, load_project


def regenerate(
    run: Annotated[
        Optional[str],
        typer.Argument(help="Run directory or run_id (defaults to cwd)."),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Show the file-level diff without mutating input/.",
        ),
    ] = False,
) -> None:
    """Regenerate ``input/`` for a run from its recorded case + params.

    Preserves the ``run_id``, ``manifest.toml``, and ``analysis/`` of the
    existing run. Only allowed for runs in the ``created`` / ``failed`` /
    ``cancelled`` states — regenerating an in-flight run would desync
    outputs from inputs.

    If the run has a non-empty ``work/`` directory a warning is printed
    since the existing outputs may no longer correspond to the new inputs.
    """
    run_dir = resolve_run_or_cwd(run, search_dir=Path.cwd())

    try:
        project_root = find_project_root(run_dir)
        project = load_project(project_root)
    except SimctlError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from None

    try:
        result = regenerate_run(project, run_dir, dry_run=dry_run)
    except ProjectConfigError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from None

    _print_result(result, dry_run=dry_run)

    if result.work_exists:
        typer.echo(
            "\nWarning: work/ is non-empty — existing outputs may no longer "
            "correspond to the regenerated input/.",
            err=True,
        )


def _print_result(result: RegenerateResult, *, dry_run: bool) -> None:
    prefix = "[dry-run] " if dry_run else ""
    verb = "Would regenerate" if dry_run else "Regenerated"
    typer.echo(f"{prefix}{verb} input for {result.run_id} from case {result.case_name}")

    if not result.has_changes:
        typer.echo(f"{prefix}(no changes; input/ already matches the case template)")
        return

    for path in result.added:
        typer.echo(f"  + {path}")
    for path in result.modified:
        typer.echo(f"  ~ {path}")
    for path in result.removed:
        typer.echo(f"  - {path}")

    summary = []
    if result.added:
        summary.append(f"{len(result.added)} added")
    if result.modified:
        summary.append(f"{len(result.modified)} modified")
    if result.removed:
        summary.append(f"{len(result.removed)} removed")
    if result.unchanged:
        summary.append(f"{len(result.unchanged)} unchanged")
    typer.echo(f"  ({', '.join(summary)})")
