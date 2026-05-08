"""CLI command for project health linting."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from runops.core.exceptions import SimctlError
from runops.core.lint import LintError, available_scopes, run_project_lint
from runops.core.lint.models import LintReport
from runops.core.project import find_project_root


def lint(
    path: Annotated[
        Path | None,
        typer.Argument(
            help="Project path (defaults to cwd or nearest parent project).",
        ),
    ] = None,
    scope: Annotated[
        str,
        typer.Option(
            "--scope",
            "-s",
            help=(
                "Comma-separated lint scopes. "
                f"Available: {', '.join(available_scopes())}."
            ),
        ),
    ] = "",
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Print a machine-readable JSON report.",
        ),
    ] = False,
    strict: Annotated[
        bool,
        typer.Option(
            "--strict",
            help="Exit non-zero when warnings are present.",
        ),
    ] = False,
) -> None:
    """Check project structure, runs, analysis, and knowledge hygiene."""
    try:
        project_root = find_project_root(path or Path.cwd())
        report = run_project_lint(project_root, scopes=_parse_scopes(scope))
    except (OSError, LintError, SimctlError) as exc:
        typer.echo(f"Error running project lint: {exc}", err=True)
        raise typer.Exit(code=1) from None

    if json_output:
        typer.echo(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        _echo_report(report)

    if report.error_count or (strict and report.warning_count):
        raise typer.Exit(code=1)


def _parse_scopes(raw: str) -> tuple[str, ...] | None:
    scopes = tuple(part.strip() for part in raw.split(",") if part.strip())
    return scopes or None


def _echo_report(report: LintReport) -> None:
    if report.status == "ok":
        typer.echo(f"Project lint: ok ({report.project_root})")
        return

    typer.echo(
        "Project lint: "
        f"{report.status} "
        f"({report.error_count} error, {report.warning_count} warning, "
        f"{report.info_count} info)"
    )
    for issue in report.sorted_issues():
        path = ""
        if issue.path is not None:
            try:
                path = issue.path.resolve().relative_to(report.project_root).as_posix()
            except ValueError:
                path = issue.path.as_posix()
        suffix = f" {path}" if path else ""
        typer.echo(f"[{issue.severity}] {issue.issue_id}{suffix}")
        typer.echo(f"  {issue.message}")
        if issue.recommendation:
            typer.echo(f"  Fix: {issue.recommendation}")
        if issue.migration:
            typer.echo(f"  Migration: {issue.migration}")
