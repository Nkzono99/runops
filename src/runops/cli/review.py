"""CLI callback for acknowledging terminal Run outcomes."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer

from runops.application.actions import ActionStatus, execute_action
from runops.cli.run_lookup import resolve_run_or_cwd
from runops.core.exceptions import SimctlError


def review(
    run: Annotated[
        Optional[str],
        typer.Argument(help="Run ID or directory; defaults to the current Run."),
    ] = None,
    reason: Annotated[
        str,
        typer.Option("--reason", help="Why this outcome has been reviewed."),
    ] = "",
    reviewed_by: Annotated[
        str,
        typer.Option("--reviewed-by", help="Actor recorded in curation metadata."),
    ] = "human",
) -> None:
    """Mark a terminal Run reviewed; Result evidence selection remains separate."""
    try:
        run_dir = resolve_run_or_cwd(run, search_dir=Path.cwd())
        result = execute_action(
            "review_run",
            run_dir=run_dir,
            reason=reason,
            reviewed_by=reviewed_by,
        )
    except SimctlError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if result.status is not ActionStatus.SUCCESS:
        typer.echo(f"Error: {result.message}", err=True)
        raise typer.Exit(code=1)
    typer.echo(
        f"Reviewed {result.data.get('run_id', '?')} at "
        f"{result.data.get('reviewed_at', '')}"
    )


__all__ = ["review"]
