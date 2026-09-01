"""CLI callbacks for bounded Experiment admission and review."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, NoReturn, Optional

import typer

from runops.application.actions import ActionResult, ActionStatus, execute_action
from runops.application.experiments import (
    resolve_experiment,
)
from runops.core.exceptions import SimctlError
from runops.core.experiment import ExperimentData, discover_experiments, load_experiment
from runops.core.project import find_project_root


def create(
    title: Annotated[str, typer.Argument(help="Human-readable Experiment title.")],
    question: Annotated[
        str,
        typer.Option("--question", help="The single research question to decide."),
    ],
    intent: Annotated[
        str,
        typer.Option(
            "--intent",
            help="Research intent: explore, confirm, validate, or reproduce.",
        ),
    ],
    exit_criteria: Annotated[
        list[str],
        typer.Option(
            "--exit",
            help="Observable stop/decision criterion; repeat for multiple criteria.",
        ),
    ],
    expires_at: Annotated[
        str,
        typer.Option(
            "--expires-at",
            help="Required timezone-aware ISO-8601 admission deadline.",
        ),
    ],
    baseline_runs: Annotated[
        Optional[list[str]],
        typer.Option("--baseline-run", help="Baseline Run ID; repeat as needed."),
    ] = None,
    baseline_reason: Annotated[
        str,
        typer.Option(
            "--baseline-reason",
            help="Why no baseline Run is needed (required when none is supplied).",
        ),
    ] = "",
    max_planned_points: Annotated[
        int,
        typer.Option("--max-planned-points", min=1),
    ] = 30,
    max_materialized_runs: Annotated[
        int,
        typer.Option("--max-materialized-runs", min=1),
    ] = 6,
    max_active_runs: Annotated[
        int,
        typer.Option("--max-active-runs", min=1),
    ] = 3,
    max_core_hours: Annotated[
        float,
        typer.Option("--max-core-hours", min=0.001),
    ] = 100.0,
    max_unreviewed_runs: Annotated[
        int,
        typer.Option("--max-unreviewed-runs", min=0),
    ] = 6,
    review_due: Annotated[
        str,
        typer.Option("--review-due", help="Optional ISO-8601 review deadline."),
    ] = "",
    created_by: Annotated[
        str,
        typer.Option("--created-by", help="Actor recorded in experiment.toml."),
    ] = "human",
    path: Annotated[
        Path,
        typer.Option("--path", help="Project root or a path inside it."),
    ] = Path("."),
) -> None:
    """Admit one bounded research question as an active Experiment."""
    root = _project_root(path)
    result = execute_action(
        "create_experiment",
        project_root=root,
        title=title,
        question=question,
        intent=intent,
        baseline_run_ids=tuple(baseline_runs or ()),
        baseline_reason=baseline_reason,
        max_planned_points=max_planned_points,
        max_materialized_runs=max_materialized_runs,
        max_active_runs=max_active_runs,
        max_core_hours=max_core_hours,
        max_unreviewed_runs=max_unreviewed_runs,
        expires_at=expires_at,
        exit_criteria=tuple(exit_criteria),
        review_due=review_due,
        created_by=created_by,
    )
    _require_success(result)
    typer.echo(f"Created Experiment {result.data['experiment_id']}")
    typer.echo(f"  Path: {Path(str(result.data['path'])).relative_to(root)}")


def list_experiments(
    path: Annotated[
        Path,
        typer.Argument(help="Project root or a path inside it."),
    ] = Path("."),
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit machine-readable JSON."),
    ] = False,
) -> None:
    """List Experiment admission units without inspecting every Run artifact."""
    root = _project_root(path)
    try:
        experiments = discover_experiments(root)
    except SimctlError as exc:
        _fail(exc)
    payload = [_experiment_payload(item, root) for item in experiments]
    if json_output:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if not payload:
        typer.echo("No Experiments found.")
        return
    for item in payload:
        typer.echo(
            f"{item['id']}  {item['lifecycle']:<6}  "
            f"{item['decision']:<7}  {item['title']}"
        )


def inspect(
    experiment: Annotated[str, typer.Argument(help="Experiment ID or TOML path.")],
    path: Annotated[
        Path,
        typer.Option("--path", help="Project root or a path inside it."),
    ] = Path("."),
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit machine-readable JSON."),
    ] = False,
) -> None:
    """Inspect one Experiment contract."""
    root = _project_root(path)
    try:
        item = load_experiment(resolve_experiment(root, experiment))
    except SimctlError as exc:
        _fail(exc)
    payload = _experiment_payload(item, root, include_details=True)
    if json_output:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    typer.echo(f"Experiment: {item.id} — {item.title}")
    typer.echo(f"Question: {item.question}")
    typer.echo(
        f"State: {item.lifecycle}; decision={item.decision}; outcome={item.outcome}"
    )
    typer.echo(
        "Budget: "
        f"planned={item.budget.max_planned_points}, "
        f"materialized={item.budget.max_materialized_runs}, "
        f"active={item.budget.max_active_runs}, "
        f"core_hours={item.budget.max_core_hours:g}, "
        f"expires_at={item.budget.expires_at}"
    )


def review(
    experiment: Annotated[str, typer.Argument(help="Experiment ID or TOML path.")],
    decision: Annotated[
        str,
        typer.Option("--decision", help="expand, revise, stop, or accept."),
    ],
    reason: Annotated[str, typer.Option("--reason", help="Review rationale.")],
    outcome: Annotated[
        str,
        typer.Option(
            "--outcome",
            help="unknown, supported, refuted, inconclusive, or invalid.",
        ),
    ] = "unknown",
    successor: Annotated[
        str,
        typer.Option("--successor", help="Optional successor Experiment ID."),
    ] = "",
    path: Annotated[
        Path,
        typer.Option("--path", help="Project root or a path inside it."),
    ] = Path("."),
) -> None:
    """Record an Experiment decision; EXPAND unlocks main materialization."""
    root = _project_root(path)
    result = execute_action(
        "review_experiment",
        project_root=root,
        experiment=experiment,
        decision=decision,
        outcome=outcome,
        reason=reason,
        successor=successor,
    )
    _require_success(result)
    typer.echo(
        f"Reviewed {result.data['experiment_id']}: "
        f"decision={result.data['decision']}, outcome={result.data['outcome']}"
    )


def close(
    experiment: Annotated[str, typer.Argument(help="Experiment ID or TOML path.")],
    decision: Annotated[
        str,
        typer.Option("--decision", help="revise, stop, or accept."),
    ],
    outcome: Annotated[
        str,
        typer.Option("--outcome", help="Scientific outcome; unknown is not allowed."),
    ],
    reason: Annotated[str, typer.Option("--reason", help="Closure rationale.")],
    successor: Annotated[
        str,
        typer.Option("--successor", help="Optional successor Experiment ID."),
    ] = "",
    path: Annotated[
        Path,
        typer.Option("--path", help="Project root or a path inside it."),
    ] = Path("."),
) -> None:
    """Close an Experiment without moving or deleting its Runs."""
    root = _project_root(path)
    result = execute_action(
        "close_experiment",
        project_root=root,
        experiment=experiment,
        decision=decision,
        outcome=outcome,
        reason=reason,
        successor=successor,
    )
    _require_success(result)
    typer.echo(
        f"Closed {result.data['experiment_id']}: "
        f"decision={result.data['decision']}, outcome={result.data['outcome']}"
    )


def _project_root(path: Path) -> Path:
    try:
        return find_project_root(path.resolve())
    except SimctlError as exc:
        _fail(exc)


def _fail(exc: Exception) -> NoReturn:
    typer.echo(f"Error: {exc}", err=True)
    raise typer.Exit(code=2) from exc


def _require_success(result: ActionResult) -> None:
    if result.status is not ActionStatus.SUCCESS:
        _fail(RuntimeError(result.message))


def _experiment_payload(
    item: ExperimentData,
    root: Path,
    *,
    include_details: bool = False,
) -> dict[str, object]:
    # Kept local to the presentation layer so the core model stays UI-agnostic.
    payload: dict[str, object] = {
        "id": item.id,
        "title": item.title,
        "lifecycle": item.lifecycle,
        "intent": item.intent,
        "decision": item.decision,
        "outcome": item.outcome,
        "path": item.experiment_file.relative_to(root).as_posix(),
    }
    if include_details:
        payload.update(
            {
                "question": item.question,
                "baseline_run_ids": list(item.baseline.run_ids),
                "baseline_reason": item.baseline.reason,
                "budget": {
                    "max_planned_points": item.budget.max_planned_points,
                    "max_materialized_runs": (item.budget.max_materialized_runs),
                    "max_active_runs": item.budget.max_active_runs,
                    "max_core_hours": item.budget.max_core_hours,
                    "max_unreviewed_runs": item.budget.max_unreviewed_runs,
                    "expires_at": item.budget.expires_at,
                },
                "exit_criteria": list(item.exit_criteria),
                "review_due": item.review_due,
            }
        )
    return payload
