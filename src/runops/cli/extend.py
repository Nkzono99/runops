"""CLI command for continuing a simulation from a stable snapshot."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer

from runops.application.actions import ActionResult, ActionStatus, execute_action
from runops.cli.run_lookup import resolve_run_or_cwd


def extend(
    run: Annotated[
        Optional[str],
        typer.Argument(help="Source run to continue from (defaults to cwd)."),
    ] = None,
    dest: Annotated[
        Optional[Path],
        typer.Option(
            "--dest", "-d", help="Destination parent (defaults to source's parent)."
        ),
    ] = None,
    nstep: Annotated[
        Optional[int],
        typer.Option("--nstep", help="Override total step count for continuation."),
    ] = None,
    submit: Annotated[
        bool,
        typer.Option("--run", help="Automatically submit the new continuation Run."),
    ] = False,
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
    """Create a continuation from a completed-equivalent source snapshot."""
    source_dir = resolve_run_or_cwd(run, search_dir=Path.cwd())
    result = execute_action(
        "extend_run",
        source_dir=source_dir,
        dest_dir=dest.resolve() if dest is not None else None,
        nstep=nstep,
        experiment_id=experiment,
        purpose=purpose,
        submit=submit,
    )
    if result.status is not ActionStatus.SUCCESS:
        if result.data.get("run_id"):
            _print_created(result)
        prefix = (
            "Warning: auto-submit failed" if result.data.get("submission") else "Error"
        )
        typer.echo(f"{prefix}: {result.message}", err=True)
        raise typer.Exit(code=1)

    _print_created(result)
    submission = result.data.get("submission")
    if isinstance(submission, dict):
        typer.echo(
            f"  Submission: {submission.get('message', submission.get('status', ''))}"
        )


def _print_created(result: ActionResult) -> None:
    reused = bool(result.data.get("reused"))
    verb = "Reused continuation run" if reused else "Created continuation run"
    typer.echo(f"{verb}: {result.data.get('run_id', '???')}")
    typer.echo(f"  Source: {result.data.get('source_run_id', '?')}")
    typer.echo(f"  Path:   {result.data.get('run_dir', '')}")
    continuation = result.data.get("continuation", {})
    if isinstance(continuation, dict):
        for key, value in continuation.items():
            typer.echo(f"  {key}: {value}")
    warnings = result.data.get("warnings", [])
    if isinstance(warnings, list):
        for warning in warnings:
            typer.echo(f"  Warning: {warning}", err=True)


__all__ = ["extend"]
