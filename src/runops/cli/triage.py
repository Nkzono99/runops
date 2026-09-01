"""CLI rendering for the read-only project triage report."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from runops.application.triage import TriageReport, build_triage_report
from runops.core.exceptions import SimctlError
from runops.core.project import find_project_root


def triage(
    path: Annotated[
        Path,
        typer.Argument(help="Project root or a path inside it."),
    ] = Path("."),
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit the complete machine-readable report."),
    ] = False,
) -> None:
    """Show cleanup and review work to do before creating new experiments."""
    try:
        root = find_project_root(path.resolve())
        report = build_triage_report(root)
    except (SimctlError, OSError, TypeError, ValueError) as exc:
        _fail(exc)

    if json_output:
        typer.echo(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
        return
    _render_text(report)


def _render_text(report: TriageReport) -> None:
    typer.echo(
        f"ACTIVE EXPERIMENTS ({report.active_experiment_count}; "
        f"pending decision: {report.pending_decision_count})"
    )
    if not report.active_experiments:
        typer.echo("- none")
    for experiment in report.active_experiments:
        statuses = _format_counts(experiment.run_status_counts)
        expiry = (
            f"EXPIRED at {experiment.expires_at}"
            if experiment.expired
            else f"expires={experiment.expires_at}"
        )
        typer.echo(
            f"- {experiment.experiment_id}: decision={experiment.decision}; "
            f"runs={experiment.run_count} ({statuses}); {expiry}"
        )

    run_total = (
        str(report.active_formal_run_count)
        if report.run_namespace_available
        else "unavailable"
    )
    typer.echo(f"\nACTIVE FORMAL RUNS ({run_total})")
    typer.echo(f"- Status: {_format_counts(report.run_status_counts)}")
    typer.echo(f"- By Experiment: {_format_counts(report.run_experiment_counts)}")
    typer.echo(f"- Unreviewed completed Runs: {report.unreviewed_completed_count}")

    typer.echo(f"\nTEST ATTEMPTS ({report.test_attempt_count})")
    typer.echo(f"- State: {_format_counts(report.test_attempt_state_counts)}")
    typer.echo(
        f"- Old TestAttempts (>={report.test_attempt_age_days} days): "
        f"{report.old_test_attempt_count} "
        f"(terminal={report.old_terminal_test_attempt_count}, "
        f"active={report.old_active_test_attempt_count})"
    )

    typer.echo(
        f"\nRESULTS (active: {report.active_result_count}; "
        f"archived: {report.archived_result_count})"
    )
    typer.echo(f"- Active status: {_format_counts(report.result_status_counts)}")

    if report.diagnostics:
        typer.echo(f"\nDIAGNOSTICS ({len(report.diagnostics)})")
        for item in report.diagnostics:
            typer.echo(f"- [{item.section}/{item.code}] {item.path}: {item.message}")

    typer.echo("\nSUGGESTED ACTIONS")
    for number, action in enumerate(report.suggested_actions, start=1):
        typer.echo(f"{number}. {action}")


def _format_counts(counts: dict[str, int] | None) -> str:
    if counts is None:
        return "unavailable"
    if not counts:
        return "none"
    return ", ".join(f"{key}={value}" for key, value in counts.items())


def _fail(exc: Exception) -> NoReturn:
    typer.echo(f"Error: {exc}", err=True)
    raise typer.Exit(code=2) from exc


__all__ = ["triage"]
