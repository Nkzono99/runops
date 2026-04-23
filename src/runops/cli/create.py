"""CLI commands for run and survey creation."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Optional

import typer

from runops.core.actions import ActionStatus, execute_action
from runops.core.case import JobData, load_case, resolve_case
from runops.core.exceptions import SimctlError
from runops.core.project import find_project_root, load_project
from runops.core.survey import expand_survey, generate_display_name, load_survey


def _echo_warnings(warnings: list[str], *, context: str = "") -> None:
    """Print non-fatal validation warnings emitted during run creation."""
    prefix = f"{context}: " if context else ""
    for warning in warnings:
        typer.echo(f"  Warning: {prefix}{warning}", err=True)


def create(
    case_name: Annotated[
        str,
        typer.Argument(
            help="Case name to create a run from.",
        ),
    ],
    dest: Annotated[
        Optional[Path],
        typer.Option("--dest", "-d", help="Destination directory (defaults to cwd)."),
    ] = None,
) -> None:
    """Create a run in the current directory.

    Examples:
      cd runs/experiment && runo runs create flat_surface
    """
    target_dir = (dest or Path.cwd()).resolve()

    if case_name == "survey" and (target_dir / "survey.toml").is_file():
        typer.echo(
            "Error: 'runo runs create survey' has been removed. "
            "Use 'runo runs sweep [DIR]' instead.",
            err=True,
        )
        raise typer.Exit(code=1)

    _create_single(case_name, target_dir)


def _create_single(case_name: str, target_dir: Path) -> None:
    """Create a single run from a case template."""
    try:
        project_root = find_project_root(target_dir)
        result = execute_action(
            "create_run",
            project_root=project_root,
            case_name=case_name,
            dest_dir=target_dir,
        )
    except SimctlError as exc:
        typer.echo(f"Error creating run: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if result.status is not ActionStatus.SUCCESS:
        typer.echo(f"Error creating run: {result.message}", err=True)
        raise typer.Exit(code=1)

    _echo_warnings(list(result.data.get("warnings", [])))
    typer.echo(f"Created run: {result.data.get('run_id', '???')}")
    typer.echo(f"  Path: {result.data.get('run_dir', target_dir)}")


def _create_survey(survey_dir: Path) -> None:
    """Expand survey.toml into multiple runs."""
    try:
        project_root = find_project_root(survey_dir)
        result = execute_action(
            "create_survey",
            project_root=project_root,
            survey_dir=survey_dir,
        )
    except SimctlError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if result.status is not ActionStatus.SUCCESS:
        typer.echo(f"Error: {result.message}", err=True)
        raise typer.Exit(code=1)

    created_runs = list(result.data.get("runs", []))
    if not created_runs:
        typer.echo("No parameter combinations to expand.")
        raise typer.Exit(code=0)

    for created_run in created_runs:
        _echo_warnings(
            list(created_run.get("warnings", [])),
            context=str(created_run.get("display_name", "")),
        )

    typer.echo(f"Created {len(created_runs)} runs in {survey_dir}")
    for created_run in created_runs:
        display_name = str(created_run.get("display_name", ""))
        name_part = f" ({display_name})" if display_name else ""
        typer.echo(f"  {created_run.get('run_id', '???')}{name_part}")


def sweep(
    survey_dir: Annotated[
        Optional[Path],
        typer.Argument(help="Directory containing survey.toml (defaults to cwd)."),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            "-n",
            help=(
                "Print the runs that would be generated (count, parameter "
                "combinations, estimated total resource cost) without "
                "writing any files."
            ),
        ),
    ] = False,
) -> None:
    """Generate all runs from a survey.toml parameter sweep.

    With ``--dry-run`` the survey is parsed and expanded but no run
    directories are created — useful to verify the parameter combinations
    and total resource cost before committing files / queue time.
    """
    target = (survey_dir or Path.cwd()).resolve()
    if dry_run:
        _sweep_dry_run(target)
    else:
        _create_survey(target)


def _sweep_dry_run(survey_dir: Path) -> None:
    """Print the planned runs without writing files."""
    try:
        survey_data = load_survey(survey_dir)
    except SimctlError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    try:
        project_root = find_project_root(survey_dir)
    except SimctlError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    # Look up the base case so we can show the resolved job (the survey's
    # own [job] block, when present, overrides the case's).
    try:
        project = load_project(project_root)
        case_dir = resolve_case(survey_data.base_case, project.root_dir)
        case_data = load_case(case_dir)
    except SimctlError as exc:
        typer.echo(f"Error resolving base case: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    effective_job = survey_data.job if survey_data.job.partition else case_data.job

    combinations = expand_survey(survey_data.axes, survey_data.linked)
    if not combinations:
        typer.echo("No parameter combinations to expand.")
        raise typer.Exit(code=0)

    n = len(combinations)
    typer.echo(f"[dry-run] {n} runs would be created in {survey_dir}")
    typer.echo(f"  base case  : {survey_data.base_case}")
    typer.echo(f"  simulator  : {survey_data.simulator}")
    typer.echo(f"  launcher   : {survey_data.launcher}")
    if survey_data.naming_template:
        typer.echo(f"  display    : {survey_data.naming_template}")
    typer.echo(_format_job_summary(effective_job))
    typer.echo(_format_resource_estimate(effective_job, n))

    # Print one line per combination so the user can scan parameters.
    typer.echo("")
    typer.echo("Planned runs:")
    for combo in combinations:
        display_name = generate_display_name(survey_data.naming_template, combo)
        params_str = _format_combo(combo)
        if display_name:
            typer.echo(f"  {display_name:<24} {params_str}")
        else:
            typer.echo(f"  {params_str}")


def _format_combo(combo: dict[str, Any]) -> str:
    """Format a combo dict as ``key1=value1, key2=value2``."""
    parts = []
    for key in sorted(combo.keys()):
        value = combo[key]
        # Truncate long lists for readability.
        if isinstance(value, list) and len(value) > 4:
            shown = f"[{value[0]}, ..., {value[-1]} ({len(value)} items)]"
        else:
            shown = repr(value)
        parts.append(f"{key}={shown}")
    return ", ".join(parts)


def _format_job_summary(job: JobData) -> str:
    """Format a JobData line for the dry-run output."""
    if job.processes > 1 or job.threads > 1 or job.cores > 1:
        # rsc-style site
        return (
            f"  job        : partition={job.partition or '(default)'} "
            f"p={job.processes} t={job.threads} c={job.cores} "
            f"walltime={job.walltime}"
        )
    return (
        f"  job        : partition={job.partition or '(default)'} "
        f"nodes={job.nodes} ntasks={job.ntasks} walltime={job.walltime}"
    )


def _format_resource_estimate(job: JobData, n_runs: int) -> str:
    """Best-effort estimate of total core-hours for the planned sweep."""
    # Pick the larger of (rsc processes) or (standard ntasks) so the
    # estimate works regardless of which site mode the job uses.
    cores_per_run = max(job.processes, job.ntasks)
    walltime_hours = _walltime_to_hours(job.walltime)
    if cores_per_run <= 1 or walltime_hours <= 0:
        return "  estimate   : (cannot estimate — incomplete job spec)"
    total_core_hours = cores_per_run * walltime_hours * n_runs
    return (
        f"  estimate   : {n_runs} runs x {cores_per_run} cores x "
        f"{walltime_hours:.1f} h walltime ~= {total_core_hours:,.0f} core-hours"
    )


def _walltime_to_hours(walltime: str) -> float:
    """Parse a walltime string to hours.  Returns 0.0 on failure."""
    if not walltime:
        return 0.0
    # Strip optional ``D-`` day prefix.
    days = 0
    rest = walltime
    if "-" in walltime:
        head, _, rest = walltime.partition("-")
        try:
            days = int(head)
        except ValueError:
            return 0.0
    parts = rest.split(":")
    try:
        if len(parts) == 3:
            h, m, s = (int(p) for p in parts)
        elif len(parts) == 2:
            h, m, s = 0, int(parts[0]), int(parts[1])
        else:
            return 0.0
    except ValueError:
        return 0.0
    return days * 24 + h + m / 60 + s / 3600
