"""CLI commands for job submission."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated, Optional

import typer

from runops.application.actions import ActionStatus
from runops.application.actions import submit_run as submit_run_action
from runops.application.execution.submission import (
    SubmitPlan,
    SubmitRequest,
    plan_submit,
)
from runops.cli.run_lookup import resolve_project_run_dir
from runops.core.discovery import discover_runs
from runops.core.exceptions import SimctlError

logger = logging.getLogger(__name__)


def _build_submit_plan(
    run_dir: Path,
    *,
    queue_name: str = "",
    qos: str = "",
    afterok: str | None = None,
) -> SubmitPlan:
    """Build the shared submission plan for one CLI target."""
    return plan_submit(
        SubmitRequest(
            run_dir=run_dir,
            queue_name=queue_name,
            qos=qos,
            afterok=afterok or "",
        )
    )


def _render_submit_plan(plan: SubmitPlan, *, bulk: bool = False) -> None:
    """Render one typed submission plan without applying it."""
    if bulk:
        marker = "[would submit]" if plan.ready else "[skip]"
        typer.echo(f"  {plan.run_id} ({plan.state_before}) {marker}")
        indent = "    "
    else:
        verb = "Would submit" if plan.ready else "Would skip"
        typer.echo(f"{verb}: {plan.run_dir}")
        indent = "  "

    typer.echo(f"{indent}Command: {' '.join(plan.command)}")
    typer.echo(f"{indent}Preconditions:")
    for check in plan.preconditions:
        status = "pass" if check.passed else "fail"
        typer.echo(f"{indent}  {check.name} [{status}]: {check.message}")
    for warning in plan.warnings:
        typer.echo(f"{indent}Warning: {warning}")


def _resolve_run_dir(identifier: str) -> Path:
    """Resolve a run identifier (path or run_id) to a run directory.

    Args:
        identifier: A run directory path or run_id string.

    Returns:
        Absolute path to the run directory.

    Raises:
        typer.Exit: If the run cannot be found.
    """
    return resolve_project_run_dir(identifier, start=Path.cwd())


def _submit_single_run(
    run_dir: Path,
    *,
    quiet: bool = False,
    queue_name: str = "",
    qos: str = "",
    afterok: str | None = None,
) -> str | None:
    """Submit a single run and return the job_id, or None on skip/error.

    Args:
        run_dir: Path to the run directory.
        quiet: If True, suppress per-run output (used in --all mode).

    Returns:
        The Slurm job ID string on success, or None if skipped or failed.

    Raises:
        typer.Exit: On fatal errors (only in single-run mode, not --all).
    """
    result = submit_run_action(
        run_dir,
        queue_name=queue_name,
        qos=qos,
        afterok=afterok or "",
    )

    if result.status is not ActionStatus.SUCCESS:
        prefix = "Error"
        if result.status is ActionStatus.PRECONDITION_FAILED:
            prefix = "Error"
        typer.echo(f"{prefix}: {result.message}")
        return None

    warnings = result.data.get("warnings", [])
    for warning in warnings:
        typer.echo(f"Warning: {warning}")

    job_id = str(result.data.get("job_id", ""))
    run_id = str(result.data.get("run_id", run_dir.name))
    if not quiet:
        typer.echo(f"Submitted {run_id}: job_id={job_id}")

    return job_id or None


def run_cmd(
    run: Annotated[
        Optional[str],
        typer.Argument(help="Run directory or run_id (defaults to cwd)."),
    ] = None,
    all_runs: Annotated[
        bool,
        typer.Option("--all", help="Submit all created runs in current directory."),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Show what would be submitted."),
    ] = False,
    queue_name: Annotated[
        Optional[str],
        typer.Option("-qn", "--queue-name", help="Override partition/queue name."),
    ] = None,
    qos: Annotated[
        Optional[str],
        typer.Option("--qos", help="Override Slurm QOS name."),
    ] = None,
    afterok_id: Annotated[
        Optional[str],
        typer.Option(
            "--afterok",
            help="Start job only after the given job ID completes successfully.",
        ),
    ] = None,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Submit all created runs without prompting."),
    ] = False,
) -> None:
    """Submit a run or all runs via sbatch.

    Examples:
      cd runs/experiment/R0001 && runo runs submit
      cd runs/mag_scan && runo runs submit --all
      runo runs submit -qn gr10451a
      runo runs submit -qn gr10451a --qos gr10451a
      runo runs submit --afterok 12345
    """
    if all_runs:
        target = Path(run) if run else None
        _submit_all_cwd(
            target,
            dry_run=dry_run,
            queue_name=queue_name or "",
            qos=qos or "",
            afterok=afterok_id,
            yes=yes,
        )
    elif run is None:
        _submit_single_cwd(
            dry_run=dry_run,
            queue_name=queue_name or "",
            qos=qos or "",
            afterok=afterok_id,
        )
    else:
        _submit_single(
            run,
            dry_run=dry_run,
            queue_name=queue_name or "",
            qos=qos or "",
            afterok=afterok_id,
        )


def _submit_single_cwd(
    *,
    dry_run: bool = False,
    queue_name: str = "",
    qos: str = "",
    afterok: str | None = None,
) -> None:
    """Submit the run in the current directory."""
    cwd = Path.cwd().resolve()
    # Check if cwd itself is a run (has manifest.toml)
    if (cwd / "manifest.toml").exists():
        run_dir = cwd
    else:
        # Try to find a single run in cwd
        run_dirs = discover_runs(cwd)
        if len(run_dirs) == 1:
            run_dir = run_dirs[0]
        elif len(run_dirs) > 1:
            typer.echo(
                f"Multiple runs found in {cwd}. "
                "Use 'runo runs submit --all' or specify a run."
            )
            raise typer.Exit(code=1)
        else:
            typer.echo(f"No run found in {cwd}")
            raise typer.Exit(code=1)

    if dry_run:
        try:
            plan = _build_submit_plan(
                run_dir,
                queue_name=queue_name,
                qos=qos,
                afterok=afterok,
            )
        except SimctlError as exc:
            typer.echo(f"Error: {exc}")
            raise typer.Exit(code=1) from exc
        _render_submit_plan(plan)
        return

    result = _submit_single_run(
        run_dir, queue_name=queue_name, qos=qos, afterok=afterok
    )
    if result is None:
        raise typer.Exit(code=1)


def _submit_all_cwd(
    target: Path | None,
    *,
    dry_run: bool = False,
    queue_name: str = "",
    qos: str = "",
    afterok: str | None = None,
    yes: bool = False,
) -> None:
    """Submit all runs in the given directory or cwd."""
    target_dir = (target or Path.cwd()).resolve()
    _submit_all(
        None,
        target_dir,
        dry_run=dry_run,
        queue_name=queue_name,
        qos=qos,
        afterok=afterok,
        yes=yes,
    )


def _submit_single(
    run_arg: str | None,
    *,
    dry_run: bool = False,
    queue_name: str = "",
    qos: str = "",
    afterok: str | None = None,
) -> None:
    """Handle single-run submission."""
    if run_arg is None:
        typer.echo("Error: RUN argument is required (unless using --all).")
        raise typer.Exit(code=1)

    run_dir = _resolve_run_dir(run_arg)

    if dry_run:
        try:
            plan = _build_submit_plan(
                run_dir,
                queue_name=queue_name,
                qos=qos,
                afterok=afterok,
            )
        except SimctlError as exc:
            typer.echo(f"Error: {exc}")
            raise typer.Exit(code=1) from exc
        _render_submit_plan(plan)
        return

    result = _submit_single_run(
        run_dir, queue_name=queue_name, qos=qos, afterok=afterok
    )
    if result is None:
        raise typer.Exit(code=1)


def _submit_all(
    run_arg: str | None,
    survey_dir_opt: Path | None,
    *,
    dry_run: bool = False,
    queue_name: str = "",
    qos: str = "",
    afterok: str | None = None,
    yes: bool = False,
) -> None:
    """Handle batch submission of all runs in a directory.

    Args:
        run_arg: Positional argument that may serve as the survey directory.
        survey_dir_opt: Explicit --survey-dir option.
        dry_run: If True, only show what would happen.
    """
    # Determine the target directory from arguments (fallback to cwd)
    target_dir: Path | None = None
    if survey_dir_opt is not None:
        target_dir = survey_dir_opt
    elif run_arg is not None:
        target_dir = Path(run_arg)
    else:
        target_dir = Path.cwd()

    if not target_dir.is_dir():
        typer.echo(f"Error: Directory not found: {target_dir}")
        raise typer.Exit(code=1)

    run_dirs = discover_runs(target_dir)
    if not run_dirs:
        typer.echo(f"No runs found under {target_dir}")
        return

    plans: dict[Path, SubmitPlan] = {}
    plan_errors: dict[Path, str] = {}
    for run_dir in run_dirs:
        try:
            plans[run_dir] = _build_submit_plan(
                run_dir,
                queue_name=queue_name,
                qos=qos,
                afterok=afterok,
            )
        except SimctlError as exc:
            plan_errors[run_dir] = str(exc)

    if dry_run:
        typer.echo(f"Found {len(run_dirs)} run(s) under {target_dir}")
        for run_dir in run_dirs:
            plan = plans.get(run_dir)
            if plan is None:
                typer.echo(f"  {run_dir.name} (error) [skip]")
                typer.echo(f"    Error: {plan_errors[run_dir]}")
                continue
            _render_submit_plan(plan, bulk=True)
        return

    for run_dir in run_dirs:
        plan = plans.get(run_dir)
        if plan is None:
            typer.echo(f"  {run_dir.name} (error) [skip]")
            typer.echo(f"    Error: {plan_errors[run_dir]}")
        elif not plan.ready:
            _render_submit_plan(plan, bulk=True)

    ready_plans = [
        plans[run_dir]
        for run_dir in run_dirs
        if run_dir in plans and plans[run_dir].ready
    ]
    skipped = len(run_dirs) - len(ready_plans)

    if not ready_plans:
        typer.echo(
            f"Summary: 0 submitted, {skipped} skipped, 0 failed "
            f"(total: {len(run_dirs)} runs)"
        )
        return

    if not yes:
        typer.echo(
            f"About to submit {len(ready_plans)} created run(s) under {target_dir}."
        )
        if not typer.confirm("Continue?"):
            typer.echo("Cancelled.")
            return

    submitted = 0
    failed = 0

    for plan in ready_plans:
        job_id = _submit_single_run(
            plan.run_dir,
            quiet=True,
            queue_name=queue_name,
            qos=qos,
            afterok=afterok,
        )
        if job_id is not None:
            typer.echo(f"  Submitted {plan.run_id}: job_id={job_id}")
            submitted += 1
        else:
            failed += 1

    typer.echo(
        f"\nSummary: {submitted} submitted, {skipped} skipped, {failed} failed "
        f"(total: {len(run_dirs)} runs)"
    )
    if failed > 0:
        raise typer.Exit(code=1)
