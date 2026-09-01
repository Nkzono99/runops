"""CLI commands for run and survey creation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any, Optional

import typer

from runops.application.actions import ActionStatus, execute_action
from runops.core.case import JobData, parse_walltime_hours
from runops.core.exceptions import SimctlError
from runops.core.project import find_project_root


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
    label: Annotated[
        str,
        typer.Option(
            "--label",
            help="Human-readable run label used in the directory name.",
        ),
    ] = "",
    experiment: Annotated[
        str,
        typer.Option(
            "--experiment",
            help="Active Experiment ID required by bounded project policy.",
        ),
    ] = "",
    purpose: Annotated[
        str,
        typer.Option(
            "--purpose",
            help=(
                "explore, confirm, validate, or reproduce; defaults to "
                "Experiment intent."
            ),
        ),
    ] = "",
    created_by: Annotated[
        str,
        typer.Option("--created-by", help="Actor frozen in Run intent metadata."),
    ] = "human",
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

    _create_single(
        case_name,
        target_dir,
        label=label,
        experiment=experiment,
        purpose=purpose,
        created_by=created_by,
    )


def _create_single(
    case_name: str,
    target_dir: Path,
    *,
    label: str = "",
    experiment: str = "",
    purpose: str = "",
    created_by: str = "human",
) -> None:
    """Create a single run from a case template."""
    try:
        project_root = find_project_root(target_dir)
        result = execute_action(
            "create_run",
            project_root=project_root,
            case_name=case_name,
            dest_dir=target_dir,
            display_name=label,
            experiment_id=experiment,
            purpose=purpose,
            created_by=created_by,
        )
    except SimctlError as exc:
        typer.echo(f"Error creating run: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if result.status is not ActionStatus.SUCCESS:
        typer.echo(f"Error creating run: {result.message}", err=True)
        raise typer.Exit(code=1)

    _echo_warnings(list(result.data.get("warnings", [])))
    verb = "Reused equivalent Run" if result.data.get("reused") else "Created run"
    typer.echo(f"{verb}: {result.data.get('run_id', '???')}")
    display_name = str(result.data.get("display_name", ""))
    if display_name:
        typer.echo(f"  Label: {display_name}")
    typer.echo(f"  Path: {result.data.get('run_dir', target_dir)}")


def _create_survey(
    survey_dir: Path,
    *,
    expected_plan_hash: str,
    point_refs: tuple[str, ...],
    all_points: bool,
    json_output: bool,
) -> None:
    """Materialize explicitly selected points from a reviewed plan."""
    try:
        project_root = find_project_root(survey_dir)
        result = execute_action(
            "create_survey",
            project_root=project_root,
            survey_dir=survey_dir,
            expected_plan_hash=expected_plan_hash,
            point_refs=point_refs,
            all_points=all_points,
        )
    except SimctlError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if result.status is not ActionStatus.SUCCESS:
        typer.echo(f"Error: {result.message}", err=True)
        raise typer.Exit(code=1)

    if json_output:
        typer.echo(json.dumps(result.data, ensure_ascii=False, indent=2, default=str))
        return

    created_runs = list(result.data.get("runs", []))
    for created_run in created_runs:
        _echo_warnings(
            list(created_run.get("warnings", [])),
            context=str(created_run.get("ref", "")),
        )

    typer.echo(
        f"Applied plan {result.data.get('plan_hash', expected_plan_hash)}: "
        f"created={result.data.get('created_count', 0)}, "
        f"reused={result.data.get('reused_count', 0)}"
    )
    for created_run in created_runs:
        marker = "reused" if created_run.get("reused") else "created"
        typer.echo(
            f"  {created_run.get('ref', '?')} -> "
            f"{created_run.get('run_id', '???')} ({marker})"
        )


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
    apply_changes: Annotated[
        bool,
        typer.Option(
            "--apply",
            help=(
                "Materialize selected points; without this flag the command "
                "is read-only."
            ),
        ),
    ] = False,
    points: Annotated[
        Optional[list[str]],
        typer.Option(
            "--point",
            help="Point ref (p0001) or point_id hash; repeat to select multiple.",
        ),
    ] = None,
    all_points: Annotated[
        bool,
        typer.Option(
            "--all",
            help="Explicitly select all candidates (still subject to hard budgets).",
        ),
    ] = False,
    expected_plan_hash: Annotated[
        str,
        typer.Option(
            "--expect-plan",
            help="Exact plan hash printed by the read-only preview.",
        ),
    ] = "",
    offset: Annotated[
        int,
        typer.Option("--offset", min=0, help="First candidate offset for preview."),
    ] = 0,
    limit: Annotated[
        int,
        typer.Option("--limit", min=1, max=1000, help="Preview page size."),
    ] = 50,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit machine-readable plan/result JSON."),
    ] = False,
) -> None:
    """Plan a Survey, or explicitly materialize a bounded selection.

    Planning is always the default and never allocates Run IDs.  Applying a
    plan requires both an unchanged hash and ``--point`` or ``--all``.
    ``--dry-run`` remains as a compatibility alias for the default behavior.
    """
    target = (survey_dir or Path.cwd()).resolve()
    if dry_run and apply_changes:
        typer.echo("Error: --dry-run and --apply are mutually exclusive", err=True)
        raise typer.Exit(code=2)
    if not apply_changes:
        if points or all_points or expected_plan_hash:
            typer.echo(
                "Error: --point, --all, and --expect-plan require --apply",
                err=True,
            )
            raise typer.Exit(code=2)
        _sweep_plan(target, offset=offset, limit=limit, json_output=json_output)
        return
    if offset or limit != 50:
        typer.echo("Error: --offset/--limit only apply to plan preview", err=True)
        raise typer.Exit(code=2)
    _create_survey(
        target,
        expected_plan_hash=expected_plan_hash,
        point_refs=tuple(points or ()),
        all_points=all_points,
        json_output=json_output,
    )


def _sweep_plan(
    survey_dir: Path,
    *,
    offset: int,
    limit: int,
    json_output: bool,
) -> None:
    """Print a bounded candidate page without writing any files."""
    try:
        project_root = find_project_root(survey_dir)
    except SimctlError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    try:
        result = execute_action(
            "plan_survey",
            project_root=project_root,
            survey_dir=survey_dir,
            offset=offset,
            limit=limit,
        )
    except SimctlError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if result.status is not ActionStatus.SUCCESS:
        typer.echo(f"Error: {result.message}", err=True)
        raise typer.Exit(code=1)

    data = result.data
    if json_output:
        typer.echo(json.dumps(data, ensure_ascii=False, indent=2, default=str))
        return
    count = int(data.get("candidate_count", 0))
    typer.echo(f"[plan only] {count} candidate points; 0 directories created")
    typer.echo(f"  survey     : {data.get('survey_id', '')}")
    typer.echo(f"  experiment : {data.get('experiment_id', '') or '(unset)'}")
    typer.echo(f"  phase      : {data.get('phase', '') or '(unset)'}")
    typer.echo(f"  purpose    : {data.get('purpose', '') or '(unset)'}")
    typer.echo(f"  plan hash  : {data.get('plan_hash', '')}")
    estimate = data.get("estimated_core_hours")
    if estimate is not None:
        typer.echo(
            f"  estimate   : {float(estimate):,.1f} core-hours for all candidates"
        )
    issues = list(data.get("admission_issues", []))
    for issue in issues:
        typer.echo(f"  BLOCKED    : {issue}", err=True)
    typer.echo("")
    typer.echo("Candidate page:")
    for point in list(data.get("points", [])):
        typer.echo(
            f"  {point.get('ref', '?')}  {point.get('display_name', ''):<24} "
            f"{_format_combo(dict(point.get('params', {})))}"
        )
    shown = len(list(data.get("points", [])))
    if offset + shown < count:
        typer.echo(
            f"  ... {count - offset - shown} more; use --offset {offset + shown}"
        )
    typer.echo("")
    typer.echo(
        "Materialize explicitly: runo runs sweep --apply --point p0001 "
        f"--expect-plan {data.get('plan_hash', '')} {survey_dir}"
    )


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
    return parse_walltime_hours(walltime) or 0.0
