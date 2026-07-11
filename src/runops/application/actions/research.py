"""Research-workspace actions."""

from __future__ import annotations

from pathlib import Path

from runops.application.actions.result import ActionResult, ActionStatus
from runops.application.research.experiments import (
    ExperimentCreateRequest,
    apply_create_experiment,
    plan_create_experiment,
    read_experiment_spec,
)


def create_experiment(
    project_root: Path,
    experiment_id: str,
    spec_path: Path,
    dry_run: bool = False,
) -> ActionResult:
    """Create or plan a typed experiment record and proposal."""
    spec = read_experiment_spec(spec_path)
    plan = plan_create_experiment(
        ExperimentCreateRequest(project_root, experiment_id, spec)
    )
    if dry_run:
        return ActionResult(
            action="create_experiment",
            status=ActionStatus.SUCCESS,
            message=f"Planned experiment {experiment_id}",
            data={
                "dry_run": True,
                "experiment_id": experiment_id,
                "ledger": str(plan.ledger_path),
                "proposal": str(plan.proposal_path),
            },
        )
    result = apply_create_experiment(plan)
    return ActionResult(
        action="create_experiment",
        status=ActionStatus.SUCCESS,
        message=f"Created experiment {experiment_id}",
        data={
            "dry_run": False,
            "experiment_id": experiment_id,
            "ledger": str(result.ledger_path),
            "proposal": str(result.proposal_path),
        },
    )
