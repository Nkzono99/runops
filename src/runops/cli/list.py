"""CLI command for listing runs."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer

from runops.application.execution.readiness import readiness_for_bulk_view
from runops.application.run_query import (
    filter_run_query,
    query_runs,
    resolve_run_query_view,
)
from runops.core.exceptions import SimctlError


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
    experiment: Optional[str] = typer.Option(
        None, "--experiment", help="Filter by immutable Experiment ID."
    ),
    purpose: Optional[str] = typer.Option(
        None,
        "--purpose",
        help="Filter by research purpose (explore/confirm/validate/reproduce).",
    ),
    review_status: Optional[str] = typer.Option(
        None,
        "--review-status",
        help="Filter by curation review status (unreviewed/reviewed).",
    ),
    storage_tier: Optional[str] = typer.Option(
        None, "--storage-tier", help="Filter by storage tier (hot/cold)."
    ),
    storage_form: Optional[str] = typer.Option(
        None,
        "--storage-form",
        help="Filter by storage form (full/compacted/metadata_only).",
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

    for search_dir in search_dirs:
        if not search_dir.is_dir():
            typer.echo(f"Error: directory not found: {search_dir}", err=True)
            raise typer.Exit(code=1)

    try:
        queried = query_runs(
            search_dirs,
            view=resolve_run_query_view(
                include_archived=include_archived,
                status_filter=status_filter,
                storage_tier=storage_tier,
                storage_form=storage_form,
            ),
        )
    except SimctlError as e:
        typer.echo(f"Error discovering runs: {e}", err=True)
        raise typer.Exit(code=1) from None

    if not queried:
        typer.echo("No runs found.")
        raise typer.Exit(code=0)

    # Collect manifest data for each run
    rows: list[tuple[str, str, str, str, str, str]] = []
    for entry in filter_run_query(
        queried,
        status_filter=status_filter,
        tag=tag,
        experiment_id=experiment,
        purpose=purpose,
        review_status=review_status,
        storage_tier=storage_tier,
        storage_form=storage_form,
    ):
        manifest = entry.manifest
        run_dir = entry.run_dir
        if manifest is None:
            rows.append(("???", "", "unknown", "-", "inspect_manifest", str(run_dir)))
            continue

        run_id = manifest.run.get("id", "???")
        display_name = manifest.run.get("display_name", "")
        run_status = manifest.run.get("status", "unknown")

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
