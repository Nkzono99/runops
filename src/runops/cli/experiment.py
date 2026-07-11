"""CLI callbacks for typed experiment workflows."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Any

import typer

from runops.application.actions.research import create_experiment
from runops.application.research.experiments import (
    ExperimentCandidate,
    ExperimentCreatePlan,
    ExperimentCreateRequest,
    ExperimentCreateSpec,
    apply_create_experiment,
    check_experiments,
    list_experiment_projections,
    plan_create_experiment,
    project_experiment,
)
from runops.core.exceptions import SimctlError
from runops.core.project import find_project_root


def new_experiment(
    experiment_id: Annotated[
        str,
        typer.Argument(help="Stable experiment identifier."),
    ],
    spec_path: Annotated[
        Path | None,
        typer.Option("--from", help="TOML or JSON experiment creation spec."),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Validate and show the plan without writing."),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Apply an effectful JSON request."),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit a versioned JSON envelope."),
    ] = False,
) -> None:
    """Create a typed experiment record and proposal attachment."""
    try:
        project_root = find_project_root(Path.cwd())
        if spec_path is None:
            spec = _prompt_spec()
            plan = plan_create_experiment(
                ExperimentCreateRequest(project_root, experiment_id, spec)
            )
            planned = dry_run or (json_output and not yes)
            if planned:
                data = _plan_data(plan)
            else:
                result = apply_create_experiment(plan)
                data = {
                    "dry_run": False,
                    "experiment_id": result.experiment.id,
                    "ledger": _display(project_root, result.ledger_path),
                    "proposal": _display(project_root, result.proposal_path),
                }
        else:
            planned = dry_run or (json_output and not yes)
            action_result = create_experiment(
                project_root,
                experiment_id,
                spec_path,
                dry_run=planned,
            )
            data = dict(action_result.data)
            for field in ("ledger", "proposal"):
                if field in data:
                    data[field] = _display(project_root, Path(str(data[field])))
    except (OSError, SimctlError) as exc:
        _render_error(str(exc), json_output=json_output)
        return

    status = "planned" if planned else "success"
    if json_output:
        _echo_json(_envelope(status, data=data))
        return
    typer.echo(f"{'Planned' if planned else 'Created'} experiment {experiment_id}.")
    typer.echo(f"Ledger: {data['ledger']}")
    typer.echo(f"Proposal: {data['proposal']}")


def show_experiment(
    experiment_id: Annotated[
        str | None,
        typer.Argument(help="Experiment ID; optional when the ledger has one record."),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit a versioned JSON envelope."),
    ] = False,
) -> None:
    """Show a derived experiment readiness projection."""
    try:
        project_root = find_project_root(Path.cwd())
        if experiment_id is None:
            projections = list_experiment_projections(project_root)
            if not projections:
                raise SimctlError("experiment ledger is empty")
            if len(projections) != 1:
                raise SimctlError(
                    "specify an experiment ID when the ledger has multiple records"
                )
            projection = projections[0]
        else:
            projection = project_experiment(project_root, experiment_id)
    except (OSError, SimctlError) as exc:
        _render_error(str(exc), json_output=json_output)
        return

    data = projection.to_dict(project_root)
    status = "blocked" if projection.blockers else "success"
    if json_output:
        _echo_json(
            _envelope(
                status,
                data=data,
                warnings=[item.message for item in projection.warnings],
                blockers=[item.message for item in projection.blockers],
                next_actions=projection.next_actions,
            )
        )
        return
    typer.echo(f"Experiment: {projection.experiment.id}")
    typer.echo(f"Phase: {projection.phase}")
    for issue in (*projection.blockers, *projection.warnings):
        typer.echo(f"{issue.severity.upper()} {issue.code}: {issue.message}")
    for command in projection.next_commands:
        typer.echo(f"Next: {command}")


def check_experiment(
    experiment_id: Annotated[
        str | None,
        typer.Argument(help="Optional experiment ID."),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit a versioned JSON envelope."),
    ] = False,
) -> None:
    """Check experiment ledger and referenced project state."""
    try:
        project_root = find_project_root(Path.cwd())
        issues = check_experiments(project_root, experiment_id)
    except (OSError, SimctlError) as exc:
        _render_error(str(exc), json_output=json_output)
        return
    blockers = [item for item in issues if item.severity == "error"]
    warnings = [item for item in issues if item.severity == "warning"]
    status = "blocked" if blockers else "success"
    data = {"issues": [item.to_dict(project_root) for item in issues]}
    if json_output:
        _echo_json(
            _envelope(
                status,
                data=data,
                warnings=[item.message for item in warnings],
                blockers=[item.message for item in blockers],
            )
        )
    elif issues:
        for item in issues:
            typer.echo(f"{item.severity.upper()} {item.code}: {item.message}")
    else:
        typer.echo("Experiment checks passed.")
    if blockers:
        raise typer.Exit(code=1)


def _prompt_spec() -> ExperimentCreateSpec:
    title = typer.prompt("Title")
    question = typer.prompt("Scientific question")
    count = typer.prompt("Number of candidates", type=int, default=2)
    if count < 2:
        raise SimctlError("experiment requires at least two candidates")
    candidates: list[ExperimentCandidate] = []
    for index in range(1, count + 1):
        typer.echo(f"Candidate {index}")
        candidates.append(
            ExperimentCandidate(
                id=typer.prompt("  ID"),
                information_gain=typer.prompt("  Information gain"),
                falsification=typer.prompt("  Falsification criterion"),
                estimated_core_hours=typer.prompt("  Estimated core-hours", type=float),
                operational_risk=typer.prompt("  Operational risk"),
            )
        )
    selected = typer.prompt("Selected candidate")
    ceiling = typer.prompt("Cost ceiling (core-hours)", type=float)
    if selected not in {item.id for item in candidates}:
        raise SimctlError("selected candidate must name a candidate")
    if ceiling < 0 or any(item.estimated_core_hours < 0 for item in candidates):
        raise SimctlError("experiment costs must be non-negative")
    return ExperimentCreateSpec(
        title=title,
        question=question,
        selected_candidate=selected,
        cost_ceiling_core_hours=ceiling,
        candidates=tuple(candidates),
    )


def _plan_data(plan: ExperimentCreatePlan) -> dict[str, Any]:
    return {
        "dry_run": True,
        "experiment_id": plan.experiment_id,
        "ledger": _display(plan.project_root, plan.ledger_path),
        "proposal": _display(plan.project_root, plan.proposal_path),
    }


def _envelope(
    status: str,
    *,
    data: dict[str, Any],
    warnings: Sequence[str] = (),
    blockers: Sequence[str] = (),
    next_actions: Sequence[str] = (),
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": status,
        "data": data,
        "warnings": list(warnings),
        "blockers": list(blockers),
        "next_actions": list(next_actions),
    }


def _display(project_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return str(path)


def _render_error(message: str, *, json_output: bool) -> None:
    if json_output:
        _echo_json(_envelope("error", data={}, blockers=[message]))
    else:
        typer.echo(f"Error: {message}", err=True)
    raise typer.Exit(code=1)


def _echo_json(payload: dict[str, Any]) -> None:
    typer.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True))
