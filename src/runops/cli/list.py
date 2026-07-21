"""CLI command for listing runs."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer

from runops.application.execution.readiness import readiness_for_bulk_view
from runops.core.discovery import discover_runs, find_archived_bundle
from runops.core.exceptions import SimctlError
from runops.core.manifest import read_manifest


def list_runs(
    paths: Optional[list[Path]] = typer.Argument(
        None,
        help=(
            "One or more directories to search for runs. "
            "Defaults to the current directory."
        ),
    ),
    status_filter: Optional[str] = typer.Option(
        None, "--status", help="Filter by run status (e.g. 'failed', 'completed')."
    ),
    tag: Optional[str] = typer.Option(
        None, "--tag", help="Filter by classification tag."
    ),
    include_archived: Annotated[
        bool,
        typer.Option(
            "--include-archived",
            help="Include archived and purged runs in the unfiltered listing.",
        ),
    ] = False,
) -> None:
    """List runs under one or more paths."""
    search_dirs = list(paths) if paths else [Path.cwd()]

    run_dirs: list[Path] = []
    seen: set[Path] = set()
    for search_dir in search_dirs:
        if not search_dir.is_dir():
            typer.echo(f"Error: directory not found: {search_dir}", err=True)
            raise typer.Exit(code=1)

        try:
            for rd in discover_runs(search_dir):
                resolved = rd.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    run_dirs.append(rd)
        except SimctlError as e:
            typer.echo(f"Error discovering runs in {search_dir}: {e}", err=True)
            raise typer.Exit(code=1) from None

    if not run_dirs:
        typer.echo("No runs found.")
        raise typer.Exit(code=0)

    # Collect manifest data for each run
    rows: list[tuple[str, str, str, str, str, str]] = []
    for run_dir in run_dirs:
        try:
            manifest = read_manifest(run_dir)
        except SimctlError:
            continue

        run_id = manifest.run.get("id", "???")
        display_name = manifest.run.get("display_name", "")
        run_status = manifest.run.get("status", "unknown")
        tags: list[str] = manifest.classification.get("tags", [])

        # Apply filters
        if status_filter and run_status != status_filter:
            continue
        if (
            not status_filter
            and not include_archived
            and (
                run_status in {"archived", "purged"}
                or find_archived_bundle(run_dir) is not None
            )
        ):
            continue
        if tag and tag not in tags:
            continue

        readiness = readiness_for_bulk_view(run_dir, manifest=manifest)
        analysis_status = readiness.analysis_status if readiness is not None else "-"
        next_action = readiness.recommended_action if readiness is not None else "-"
        rows.append(
            (
                str(run_id),
                str(display_name),
                str(run_status),
                analysis_status,
                next_action,
                str(run_dir),
            )
        )

    # Sort by run_id
    rows.sort(key=lambda r: r[0])

    if not rows:
        typer.echo("No runs match the given filters.")
        raise typer.Exit(code=0)

    _print_table(rows)


def _print_table(rows: list[tuple[str, str, str, str, str, str]]) -> None:
    """Print a formatted table of run entries.

    Args:
        rows: List of run identity, execution/readiness state, action, and path.
    """
    headers = ("RUN_ID", "NAME", "STATUS", "ANALYSIS", "NEXT", "PATH")
    # Calculate column widths
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    typer.echo(fmt.format(*headers))
    typer.echo(fmt.format(*("-" * w for w in widths)))
    for row in rows:
        typer.echo(fmt.format(*row))
