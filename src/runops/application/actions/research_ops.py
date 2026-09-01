"""Agent Gateway actions for Experiments, TestAttempts, and Results."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from runops.application.actions.helpers import _precondition_fail
from runops.application.actions.result import ActionResult, ActionStatus
from runops.application.experiments import (
    close_experiment as close_experiment_workflow,
)
from runops.application.experiments import (
    create_experiment as create_experiment_workflow,
)
from runops.application.experiments import (
    review_experiment as review_experiment_workflow,
)
from runops.application.research.results import (
    EvidenceRequest,
)
from runops.application.research.results import (
    check_result as check_result_workspace,
)
from runops.application.research.results import (
    seal_result as seal_result_workspace,
)
from runops.application.research.workspace import (
    ResearchWorkspaceError,
)
from runops.application.research.workspace import (
    archive_result as archive_result_workspace,
)
from runops.application.research.workspace import (
    create_result as create_result_workspace,
)
from runops.application.research.workspace import (
    restore_result as restore_result_workspace,
)
from runops.application.test_attempts import (
    clean_test_attempts as clean_test_attempts_workflow,
)
from runops.application.test_attempts import (
    prepare_test_attempt as prepare_test_attempt_workflow,
)
from runops.application.test_attempts import (
    record_test_result as record_test_result_workflow,
)
from runops.core.event_log import logged_action
from runops.core.exceptions import SimctlError
from runops.core.experiment import ExperimentData
from runops.core.project import load_project
from runops.core.research.workspace import ResearchBudget
from runops.core.test_attempt import TestAttemptData


@logged_action("create_experiment")
def create_experiment(
    project_root: Path,
    title: str,
    question: str,
    intent: str,
    *,
    baseline_run_ids: tuple[str, ...] = (),
    baseline_reason: str = "",
    max_planned_points: int,
    max_materialized_runs: int,
    max_active_runs: int,
    max_core_hours: float,
    max_unreviewed_runs: int,
    expires_at: str,
    exit_criteria: tuple[str, ...],
    review_due: str = "",
    created_by: str = "human",
) -> ActionResult:
    """Admit one bounded Experiment and return its stable identity."""
    try:
        mutation = create_experiment_workflow(
            project_root,
            title=title,
            question=question,
            intent=intent,
            baseline_run_ids=baseline_run_ids,
            baseline_reason=baseline_reason,
            max_planned_points=max_planned_points,
            max_materialized_runs=max_materialized_runs,
            max_active_runs=max_active_runs,
            max_core_hours=max_core_hours,
            max_unreviewed_runs=max_unreviewed_runs,
            expires_at=expires_at,
            exit_criteria=exit_criteria,
            review_due=review_due,
            created_by=created_by,
        )
    except SimctlError as exc:
        return _precondition_fail("create_experiment", str(exc))
    return ActionResult(
        action="create_experiment",
        status=ActionStatus.SUCCESS,
        message=f"Created Experiment {mutation.experiment.id}",
        data=_experiment_payload(mutation.experiment, mutation.path),
        state_after=mutation.experiment.lifecycle,
    )


@logged_action("review_experiment")
def review_experiment(
    project_root: Path,
    experiment: str,
    *,
    decision: str,
    reason: str,
    outcome: str = "unknown",
    successor: str = "",
) -> ActionResult:
    """Record a structured decision on an active Experiment."""
    try:
        mutation = review_experiment_workflow(
            project_root,
            experiment,
            decision=decision,
            reason=reason,
            outcome=outcome,
            successor=successor,
        )
    except SimctlError as exc:
        return _precondition_fail("review_experiment", str(exc))
    return ActionResult(
        action="review_experiment",
        status=ActionStatus.SUCCESS,
        message=(
            f"Reviewed {mutation.experiment.id}: "
            f"decision={mutation.experiment.decision}"
        ),
        data=_experiment_payload(mutation.experiment, mutation.path),
        state_before="active",
        state_after=mutation.experiment.lifecycle,
    )


@logged_action("close_experiment")
def close_experiment(
    project_root: Path,
    experiment: str,
    *,
    decision: str,
    outcome: str,
    reason: str,
    successor: str = "",
) -> ActionResult:
    """Close an Experiment after a terminal research decision."""
    try:
        mutation = close_experiment_workflow(
            project_root,
            experiment,
            decision=decision,
            outcome=outcome,
            reason=reason,
            successor=successor,
        )
    except SimctlError as exc:
        return _precondition_fail("close_experiment", str(exc))
    return ActionResult(
        action="close_experiment",
        status=ActionStatus.SUCCESS,
        message=(
            f"Closed {mutation.experiment.id}: outcome={mutation.experiment.outcome}"
        ),
        data=_experiment_payload(mutation.experiment, mutation.path),
        state_before="active",
        state_after=mutation.experiment.lifecycle,
    )


@logged_action("prepare_test_attempt")
def prepare_test_attempt(
    project_root: Path,
    case: str,
    *,
    kind: str,
    profile: str = "",
    source_commit: str = "",
    executable_hash: str = "",
    adapter: str = "",
    adapter_version: str = "",
    cache_ttl_hours: float = 24.0,
    rerun: bool = False,
) -> ActionResult:
    """Prepare or cache-reuse an isolated smoke/debug TestAttempt."""
    try:
        prepared = prepare_test_attempt_workflow(
            project_root,
            case,
            kind=kind,
            profile=profile,
            source_commit=source_commit,
            executable_hash=executable_hash,
            adapter=adapter,
            adapter_version=adapter_version,
            cache_ttl=timedelta(hours=cache_ttl_hours),
            rerun=rerun,
        )
    except (SimctlError, OverflowError, ValueError) as exc:
        return _precondition_fail("prepare_test_attempt", str(exc))
    action = "Reused" if prepared.cached else "Prepared"
    payload = _test_attempt_payload(prepared.attempt)
    payload.update(
        {
            "cached": prepared.cached,
            "cache_age_seconds": prepared.cache_age_seconds,
            "receipt_path": str(prepared.path / "test-receipt.toml"),
        }
    )
    return ActionResult(
        action="prepare_test_attempt",
        status=ActionStatus.SUCCESS,
        message=f"{action} {prepared.attempt.kind} TestAttempt {prepared.attempt.id}",
        data=payload,
        state_after=prepared.attempt.state,
    )


@logged_action("record_test_result")
def record_test_result(
    project_root: Path,
    attempt_id: str,
    *,
    result: str,
    observation: str = "",
) -> ActionResult:
    """Record one terminal TestAttempt observation."""
    try:
        attempt = record_test_result_workflow(
            project_root,
            attempt_id,
            result=result,
            observation=observation,
        )
    except SimctlError as exc:
        return _precondition_fail("record_test_result", str(exc))
    return ActionResult(
        action="record_test_result",
        status=ActionStatus.SUCCESS,
        message=f"Recorded {attempt.id}: {attempt.state}",
        data=_test_attempt_payload(attempt),
        state_after=attempt.state,
    )


@logged_action("clean_test_attempts")
def clean_test_attempts(
    project_root: Path,
    *,
    older_than_days: int,
) -> ActionResult:
    """Remove terminal TestAttempts older than an explicit threshold."""
    try:
        cleaned = clean_test_attempts_workflow(
            project_root,
            older_than_days=older_than_days,
        )
    except SimctlError as exc:
        return _precondition_fail("clean_test_attempts", str(exc))
    removed_ids = list(cleaned.removed_ids)
    return ActionResult(
        action="clean_test_attempts",
        status=ActionStatus.SUCCESS,
        message=f"Removed {len(removed_ids)} TestAttempt(s)",
        data={"removed_ids": removed_ids, "removed_count": len(removed_ids)},
    )


@logged_action("create_result")
def create_result(
    project_root: Path,
    name: str,
    *,
    budget: ResearchBudget | None = None,
) -> ActionResult:
    """Create one canonical draft Result within the active Result budget."""
    try:
        selected_budget = _load_research_budget(project_root, budget)
        result = create_result_workspace(
            project_root,
            name,
            budget=selected_budget,
        )
    except (ResearchWorkspaceError, SimctlError) as exc:
        return _precondition_fail("create_result", str(exc))
    return ActionResult(
        action="create_result",
        status=ActionStatus.SUCCESS,
        message=f"Created {result.result_id}",
        data={"result_id": result.result_id, "path": str(result.path)},
        state_after="draft",
    )


@logged_action("check_result")
def check_result(project_root: Path, result: str | Path) -> ActionResult:
    """Check one Result's evidence and seal integrity without mutation."""
    try:
        project = load_project(project_root)
        checked = check_result_workspace(
            project_root,
            result,
            budget=project.research_budget,
        )
    except (ResearchWorkspaceError, SimctlError) as exc:
        return _precondition_fail("check_result", str(exc))
    status = ActionStatus.SUCCESS if checked.ok else ActionStatus.PRECONDITION_FAILED
    return ActionResult(
        action="check_result",
        status=status,
        message=(
            f"Result {checked.result_id} is valid"
            if checked.ok
            else f"Result {checked.result_id} has blocking issues"
        ),
        data=checked.to_dict(),
        state_after=checked.status,
    )


@logged_action("seal_result")
def seal_result(
    project_root: Path,
    result: str | Path,
    *,
    claim: str,
    outcome: str,
    evidence: tuple[EvidenceRequest, ...],
) -> ActionResult:
    """Seal one canonical Result with immutable evidence receipts."""
    try:
        project = load_project(project_root)
        sealed = seal_result_workspace(
            project_root,
            result,
            claim=claim,
            outcome=outcome,
            evidence=evidence,
            budget=project.research_budget,
        )
    except (ResearchWorkspaceError, SimctlError) as exc:
        return _precondition_fail("seal_result", str(exc))
    verb = "Sealed" if sealed.changed else "Already sealed"
    return ActionResult(
        action="seal_result",
        status=ActionStatus.SUCCESS,
        message=f"{verb}: {sealed.result_id}",
        data={
            "result_id": sealed.result_id,
            "path": str(sealed.path),
            "sealed_at": sealed.sealed_at,
            "content_sha256": sealed.content_sha256,
            "changed": sealed.changed,
        },
        state_after="sealed",
    )


@logged_action("archive_result")
def archive_result(project_root: Path, result_id: str) -> ActionResult:
    """Archive one Result intact outside the active set."""
    try:
        load_project(project_root)
        destination = archive_result_workspace(project_root, result_id)
    except (ResearchWorkspaceError, SimctlError) as exc:
        return _precondition_fail("archive_result", str(exc))
    return ActionResult(
        action="archive_result",
        status=ActionStatus.SUCCESS,
        message=f"Archived Result {result_id}",
        data={"result_id": result_id, "path": str(destination)},
        state_before="active",
        state_after="archived",
    )


@logged_action("restore_result")
def restore_result(
    project_root: Path,
    result_id: str,
    *,
    budget: ResearchBudget | None = None,
) -> ActionResult:
    """Restore one archived Result within the active Result budget."""
    try:
        selected_budget = _load_research_budget(project_root, budget)
        destination = restore_result_workspace(
            project_root,
            result_id,
            budget=selected_budget,
        )
    except (ResearchWorkspaceError, SimctlError) as exc:
        return _precondition_fail("restore_result", str(exc))
    return ActionResult(
        action="restore_result",
        status=ActionStatus.SUCCESS,
        message=f"Restored Result {result_id}",
        data={"result_id": result_id, "path": str(destination)},
        state_before="archived",
        state_after="active",
    )


def _experiment_payload(
    experiment: ExperimentData,
    path: Path,
) -> dict[str, object]:
    """Serialize the stable Experiment fields needed by interfaces."""
    return {
        "experiment_id": experiment.id,
        "title": experiment.title,
        "lifecycle": experiment.lifecycle,
        "decision": experiment.decision,
        "outcome": experiment.outcome,
        "path": str(path),
    }


def _test_attempt_payload(attempt: TestAttemptData) -> dict[str, object]:
    """Serialize a TestAttempt without exposing its mutable raw TOML mapping."""
    return {
        "attempt_id": attempt.id,
        "kind": attempt.kind,
        "state": attempt.state,
        "case": attempt.case,
        "profile": attempt.profile,
        "adapter": attempt.adapter,
        "adapter_version": attempt.adapter_version,
        "source_commit": attempt.source_commit,
        "executable_hash": attempt.executable_hash,
        "input_hash": attempt.input_hash,
        "cache_key": attempt.cache_key,
        "created_at": attempt.created_at,
        "updated_at": attempt.updated_at,
        "started_at": attempt.started_at,
        "finished_at": attempt.finished_at,
        "observation": attempt.observation,
        "cached_from": attempt.cached_from,
        "path": str(attempt.attempt_dir),
    }


def _load_research_budget(
    project_root: Path,
    budget: ResearchBudget | None,
) -> ResearchBudget:
    """Validate the project and select its loaded research budget."""
    project = load_project(project_root)
    return budget or project.research_budget


__all__ = [
    "archive_result",
    "check_result",
    "clean_test_attempts",
    "close_experiment",
    "create_experiment",
    "create_result",
    "prepare_test_attempt",
    "record_test_result",
    "restore_result",
    "review_experiment",
    "seal_result",
]
