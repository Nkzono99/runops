"""CLI command for cloning and deriving Runs."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer

from runops.application.actions import ActionStatus, execute_action
from runops.cli.run_lookup import resolve_run_or_cwd
from runops.core.exceptions import SimctlError


def clone(
    run: Annotated[
        Optional[str],
        typer.Argument(help="Run directory or run_id (defaults to cwd)."),
    ] = None,
    dest: Annotated[
        Optional[Path],
        typer.Option(
            "--dest",
            "-d",
            help="Destination parent (defaults to the source Run's parent).",
        ),
    ] = None,
    set_params: Annotated[
        Optional[list[str]],
        typer.Option("--set", help="Override parameters as key=value."),
    ] = None,
    experiment: Annotated[
        Optional[str],
        typer.Option(
            "--experiment",
            help="Active Experiment ID (defaults to the source Run's Experiment).",
        ),
    ] = None,
    purpose: Annotated[
        Optional[str],
        typer.Option(
            "--purpose",
            help="Run purpose (defaults to the source Run's purpose).",
        ),
    ] = None,
) -> None:
    """Clone a completed-equivalent Run, optionally changing parameters."""
    source_dir = resolve_run_or_cwd(run, search_dir=Path.cwd())
    try:
        overrides = _parse_set_params(set_params or [])
    except SimctlError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from None

    result = execute_action(
        "clone_run",
        source_dir=source_dir,
        dest_dir=dest.resolve() if dest is not None else None,
        overrides=overrides,
        experiment_id=experiment,
        purpose=purpose,
    )
    if result.status is not ActionStatus.SUCCESS:
        typer.echo(f"Error creating clone: {result.message}", err=True)
        raise typer.Exit(code=1)

    if bool(result.data.get("reused")):
        typer.echo(
            "Equivalent completed Run reused by scientific_hash: "
            f"{result.data.get('run_id', '???')}"
        )
    else:
        typer.echo(
            f"Cloned {result.data.get('source_run_id', '?')} -> "
            f"{result.data.get('run_id', '???')}"
        )
    typer.echo(f"  Path: {result.data.get('run_dir', '')}")
    for warning in result.data.get("warnings", []):
        typer.echo(f"  Warning: {warning}", err=True)


def _parse_set_params(set_params: list[str]) -> dict[str, str]:
    """Parse repeatable ``--set key=value`` interface values."""
    overrides: dict[str, str] = {}
    for param in set_params:
        if "=" not in param:
            raise SimctlError(f"invalid --set format {param!r}, expected key=value")
        key, value = param.split("=", 1)
        key = key.strip()
        if not key:
            raise SimctlError(f"invalid --set format {param!r}, key must not be empty")
        overrides[key] = value.strip()
    return overrides


__all__ = ["clone"]
