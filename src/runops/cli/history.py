"""CLI command for viewing job submission history."""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Annotated, Optional

import typer

from runops.core.discovery import discover_runs
from runops.core.exceptions import SimctlError
from runops.core.manifest import read_manifest
from runops.core.project import find_project_root


def history(
    path: Annotated[
        Optional[Path],
        typer.Argument(help="Directory to search (defaults to project root)."),
    ] = None,
    count: Annotated[
        int,
        typer.Option("-n", "--count", help="Number of entries to show (0 = all)."),
    ] = 20,
) -> None:
    """Show job submission history across the project.

    Lists runs sorted by submission time (most recent first).

    Examples:
      runo runs history           # last 20 submissions
      runo runs history -n 0      # all submissions
    """
    search_dir = (path or Path.cwd()).resolve()

    try:
        root = find_project_root(search_dir)
        runs_dir = root / "runs"
        if runs_dir.is_dir():
            search_dir = runs_dir
    except SimctlError:
        pass

    try:
        run_dirs = discover_runs(search_dir)
    except SimctlError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from None

    if not run_dirs:
        typer.echo("No runs found.")
        return

    # Collect entries with submission info
    entries: list[tuple[str, str, str, str, str]] = []
    for run_dir in run_dirs:
        try:
            manifest = read_manifest(run_dir)
        except SimctlError:
            continue

        job_id = manifest.job.get("job_id", "")
        if not job_id:
            continue  # Never submitted

        run_id = manifest.run.get("id", "???")
        status = manifest.run.get("status", "unknown")
        submitted_at = manifest.job.get("submitted_at", "")
        rel_path = str(run_dir)
        with contextlib.suppress(ValueError):
            rel_path = run_dir.relative_to(search_dir.parent).as_posix()

        entries.append((submitted_at, job_id, run_id, status, rel_path))

    if not entries:
        typer.echo("No submitted runs found.")
        return

    # Sort by submission time (newest first)
    entries.sort(key=lambda e: e[0], reverse=True)

    if count > 0:
        entries = entries[:count]

    headers = ("SUBMITTED", "JOB_ID", "RUN_ID", "STATUS", "PATH")
    widths = [len(h) for h in headers]
    for row in entries:
        for i, cell in enumerate(row):
            # Shorten timestamp for display
            display = cell
            if i == 0 and "T" in cell:
                display = cell.replace("T", " ")[:19]
            widths[i] = max(widths[i], len(display))

    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    typer.echo(fmt.format(*headers))
    typer.echo(fmt.format(*("-" * w for w in widths)))
    for row in entries:
        display_row = list(row)
        if "T" in display_row[0]:
            display_row[0] = display_row[0].replace("T", " ")[:19]
        typer.echo(fmt.format(*display_row))

    typer.echo(f"\n{len(entries)} entries")
