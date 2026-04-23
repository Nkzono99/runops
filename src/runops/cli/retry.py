"""CLI command for retrying failed or cancelled runs."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer

from runops.cli.run_lookup import resolve_run_or_cwd
from runops.core.actions import ActionStatus
from runops.core.actions import retry_run as retry_run_action


def _parse_adjustments(values: list[str]) -> dict[str, str]:
    """Parse ``KEY=VAL`` pairs into a dict."""
    parsed: dict[str, str] = {}
    for item in values:
        if "=" not in item:
            raise typer.BadParameter(
                f"adjustment '{item}' is missing '=' separator (expected KEY=VAL)"
            )
        key, _, val = item.partition("=")
        key = key.strip()
        if not key:
            raise typer.BadParameter(f"adjustment '{item}' has empty key")
        parsed[key] = val.strip()
    return parsed


def retry(
    run: Annotated[
        Optional[str],
        typer.Argument(help="Run directory or run_id (defaults to cwd)."),
    ] = None,
    reviewed_log: Annotated[
        bool,
        typer.Option(
            "--reviewed-log",
            help=(
                "Confirm that the failure log has been reviewed. Required when "
                "failure_reason is 'exit_error'."
            ),
        ),
    ] = False,
    adjustments: Annotated[
        Optional[list[str]],
        typer.Option(
            "--adjustments",
            "-a",
            help=(
                "KEY=VAL overrides recorded on the next attempt (repeat the flag "
                "or pass multiple KEY=VAL arguments, e.g. -a walltime=24:00:00)."
            ),
        ),
    ] = None,
    and_submit: Annotated[
        bool,
        typer.Option(
            "--and-submit",
            help="Automatically call `runs submit` after the retry reset.",
        ),
    ] = False,
) -> None:
    """Reset a failed or cancelled run so it can be resubmitted.

    ``retry_run`` clears the recorded job_id / submitted_at, bumps the attempt
    counter, and returns the run to ``created`` state.  Pass ``--and-submit``
    to immediately invoke ``runo runs submit`` after the reset.
    """
    run_dir = resolve_run_or_cwd(run, search_dir=Path.cwd())

    adjustments_dict = _parse_adjustments(adjustments or [])

    result = retry_run_action(
        run_dir,
        adjustments=adjustments_dict or None,
        reviewed_log=reviewed_log,
    )
    if result.status is not ActionStatus.SUCCESS:
        typer.echo(f"Error: {result.message}", err=True)
        raise typer.Exit(code=1)

    typer.echo(result.message)
    if result.state_after and result.state_before != result.state_after:
        typer.echo(f"  State: {result.state_before} -> {result.state_after}")

    if and_submit:
        from runops.cli.submit import run_cmd

        typer.echo("Submitting after retry reset...")
        run_cmd(run=str(run_dir))
