"""Action registry: normalized execution interface for AI agents.

Provides a fixed set of named actions with explicit input schemas,
preconditions, and structured results.  Unlike the CLI (designed for humans),
the action registry is designed for programmatic consumption where inputs
and outputs are typed dictionaries.

Each action wraps existing core functions -- no new domain logic lives here.
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from runops.core.exceptions import SimctlError
from runops.core.state import RunState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


class ActionStatus(str, Enum):
    """Outcome of an action execution."""

    SUCCESS = "success"
    FAILED = "failed"
    PRECONDITION_FAILED = "precondition_failed"
    ERROR = "error"


@dataclass
class ActionResult:
    """Structured result returned by every action.

    Attributes:
        action: Name of the executed action.
        status: Outcome status.
        message: Human-readable summary.
        data: Arbitrary result payload (action-specific).
        state_before: Run state before execution (if applicable).
        state_after: Run state after execution (if applicable).
    """

    action: str
    status: ActionStatus
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    state_before: str = ""
    state_after: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-friendly dictionary."""
        d: dict[str, Any] = {
            "action": self.action,
            "status": self.status.value,
            "message": self.message,
        }
        if self.data:
            d["data"] = self.data
        if self.state_before:
            d["state_before"] = self.state_before
        if self.state_after:
            d["state_after"] = self.state_after
        return d


# ---------------------------------------------------------------------------
# Action specifications (metadata for agents)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ActionSpec:
    """Machine-readable specification for a single action.

    Attributes:
        name: Action identifier (e.g. ``"create_run"``).
        description: One-line summary.
        required_params: Required input parameter names.
        optional_params: Optional input parameter names.
        preconditions: Human-readable preconditions list.
        state_change: Expected state transition (e.g. ``"created -> submitted"``).
        destructive: Whether the action is hard to reverse.
        risk_level: Relative operational risk (``"low"``, ``"medium"``,
            or ``"high"``).
        cost_class: Relative execution/storage cost (``"low"``,
            ``"medium"``, or ``"high"``).
        requires_confirmation: Whether this action always requires
            human confirmation before execution.
        confirmation_reason: Human-readable reason for the confirmation.
        confirmation_conditions: Dynamic cases that should trigger
            confirmation even if the action is not always gated.
    """

    name: str
    description: str
    required_params: tuple[str, ...] = ()
    optional_params: tuple[str, ...] = ()
    preconditions: tuple[str, ...] = ()
    state_change: str = ""
    destructive: bool = False
    risk_level: str = "low"
    cost_class: str = "low"
    requires_confirmation: bool = False
    confirmation_reason: str = ""
    confirmation_conditions: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Serialize metadata for machine-readable agent consumption."""
        data: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "required_params": list(self.required_params),
            "optional_params": list(self.optional_params),
            "preconditions": list(self.preconditions),
            "destructive": self.destructive,
            "risk_level": self.risk_level,
            "cost_class": self.cost_class,
            "requires_confirmation": self.requires_confirmation,
        }
        if self.state_change:
            data["state_change"] = self.state_change
        if self.confirmation_reason:
            data["confirmation_reason"] = self.confirmation_reason
        if self.confirmation_conditions:
            data["confirmation_conditions"] = list(self.confirmation_conditions)
        return data


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

ACTION_SPECS: dict[str, ActionSpec] = {
    "create_run": ActionSpec(
        name="create_run",
        description="Create a new run directory from a case.",
        required_params=("project_root", "case_name"),
        optional_params=("dest_dir", "display_name", "params"),
        preconditions=("project loaded", "case exists"),
        state_change="-> created",
        risk_level="medium",
        cost_class="medium",
    ),
    "create_survey": ActionSpec(
        name="create_survey",
        description="Expand a survey.toml into created run directories.",
        required_params=("project_root", "survey_dir"),
        preconditions=("project loaded", "survey.toml exists", "base case exists"),
        state_change="N x -> created",
        risk_level="medium",
        cost_class="medium",
    ),
    "submit_run": ActionSpec(
        name="submit_run",
        description="Submit a run to Slurm via sbatch.",
        required_params=("run_dir",),
        optional_params=("queue_name", "qos", "afterok"),
        preconditions=("run state == created", "job.sh exists"),
        state_change="created -> submitted",
        risk_level="high",
        cost_class="high",
        confirmation_conditions=(
            "required for first bulk submit of a new survey",
            "required after a retry that increases walltime, memory, or nodes",
        ),
    ),
    "sync_run": ActionSpec(
        name="sync_run",
        description="Synchronize run state with Slurm.",
        required_params=("run_dir",),
        preconditions=("run state in {submitted, running}", "job_id recorded"),
        state_change="submitted/running -> completed/failed/cancelled",
        risk_level="low",
        cost_class="low",
    ),
    "show_log": ActionSpec(
        name="show_log",
        description="Read latest job stdout and return tail lines.",
        required_params=("run_dir",),
        optional_params=("lines",),
        preconditions=("run has been submitted at least once",),
        risk_level="low",
        cost_class="low",
    ),
    "summarize_run": ActionSpec(
        name="summarize_run",
        description="Generate analysis summary for a completed run.",
        required_params=("run_dir",),
        preconditions=("run state == completed",),
        risk_level="low",
        cost_class="medium",
    ),
    "collect_survey": ActionSpec(
        name="collect_survey",
        description="Aggregate results across all runs in a survey.",
        required_params=("survey_dir",),
        preconditions=("survey directory contains at least one completed run",),
        risk_level="low",
        cost_class="medium",
    ),
    "export_publication": ActionSpec(
        name="export_publication",
        description="Create a paper-facing export bundle from a run or survey.",
        required_params=("target_path", "paper_id"),
        optional_params=(
            "export_name",
            "mode",
            "include_figures",
            "include_plots",
            "force",
        ),
        preconditions=("target exists", "target is a run or contains runs"),
        risk_level="low",
        cost_class="medium",
    ),
    "retry_run": ActionSpec(
        name="retry_run",
        description="Prepare a failed run for resubmission.",
        required_params=("run_dir",),
        optional_params=("adjustments", "reviewed_log"),
        preconditions=("run state == failed",),
        state_change="failed -> created",
        risk_level="medium",
        cost_class="medium",
        confirmation_conditions=(
            "required when retry adjustments increase walltime, memory, or nodes",
        ),
    ),
    "archive_run": ActionSpec(
        name="archive_run",
        description="Mark a completed run as archived.",
        required_params=("run_dir",),
        preconditions=("run state == completed",),
        state_change="completed -> archived",
        destructive=True,
        risk_level="high",
        cost_class="low",
        requires_confirmation=True,
        confirmation_reason=(
            "Archiving changes lifecycle state and is treated as a review gate."
        ),
    ),
    "purge_work": ActionSpec(
        name="purge_work",
        description="Delete purgeable work/ artifacts from an archived run.",
        required_params=("run_dir",),
        preconditions=("run state == archived",),
        state_change="archived -> purged",
        destructive=True,
        risk_level="high",
        cost_class="high",
        requires_confirmation=True,
        confirmation_reason=(
            "Purging deletes generated work files and is intentionally gated."
        ),
    ),
    "cancel_run": ActionSpec(
        name="cancel_run",
        description="Cancel an active Slurm job (scancel) and sync the run state.",
        required_params=("run_dir",),
        preconditions=("run state in {submitted, running}", "job_id recorded"),
        state_change="submitted/running -> cancelled",
        risk_level="medium",
        cost_class="low",
    ),
    "delete_run": ActionSpec(
        name="delete_run",
        description="Hard-delete a run directory.  Only allowed for terminal "
        "non-completed states (created, cancelled, failed) so existing "
        "results are never lost.",
        required_params=("run_dir",),
        preconditions=("run state in {created, cancelled, failed}",),
        destructive=True,
        risk_level="high",
        cost_class="low",
        requires_confirmation=True,
        confirmation_reason="Deletion removes the run directory irreversibly.",
    ),
    "save_insight": ActionSpec(
        name="save_insight",
        description="Record a markdown knowledge insight.",
        required_params=("project_root", "name", "content"),
        optional_params=("insight_type", "simulator", "tags", "source_project"),
        preconditions=("project loaded",),
        risk_level="low",
        cost_class="low",
    ),
    "add_fact": ActionSpec(
        name="add_fact",
        description="Record a structured knowledge fact.",
        required_params=("project_root", "claim"),
        optional_params=(
            "fact_type",
            "simulator",
            "scope_case",
            "scope_text",
            "param_name",
            "confidence",
            "source_run",
            "evidence_kind",
            "evidence_ref",
            "tags",
            "supersedes",
        ),
        preconditions=("project loaded",),
        risk_level="medium",
        cost_class="low",
        confirmation_conditions=(
            "recommended before recording a new high-confidence fact from fresh "
            "survey results",
        ),
    ),
    "promote_fact": ActionSpec(
        name="promote_fact",
        description="Promote an imported candidate fact into local curated facts.",
        required_params=("project_root", "fact_id"),
        preconditions=("candidate fact exists",),
        risk_level="low",
        cost_class="low",
    ),
}


def list_actions() -> list[ActionSpec]:
    """Return all registered action specifications."""
    return list(ACTION_SPECS.values())


def get_action_spec(name: str) -> ActionSpec | None:
    """Look up an action spec by name."""
    return ACTION_SPECS.get(name)


# ---------------------------------------------------------------------------
# Precondition helpers
# ---------------------------------------------------------------------------


def _require_state(run_dir: Path, *allowed: RunState) -> tuple[str, str | None]:
    """Read manifest and check run state.

    Returns:
        (current_state_value, error_message_or_None)
    """
    from runops.core.manifest import read_manifest

    manifest = read_manifest(run_dir)
    state_str = manifest.run.get("status", "")
    try:
        state = RunState(state_str)
    except ValueError:
        return state_str, f"Unknown run state: {state_str!r}"

    if state not in allowed:
        allowed_str = ", ".join(s.value for s in allowed)
        return state_str, f"Run state is {state_str!r}, requires one of: {allowed_str}"

    return state_str, None


def _precondition_fail(action: str, message: str) -> ActionResult:
    return ActionResult(
        action=action,
        status=ActionStatus.PRECONDITION_FAILED,
        message=message,
    )


def _error(action: str, message: str) -> ActionResult:
    return ActionResult(
        action=action,
        status=ActionStatus.ERROR,
        message=message,
    )


def _dir_size(dir_path: Path) -> int:
    """Calculate total size of files under a directory tree."""
    if not dir_path.is_dir():
        return 0
    total = 0
    for f in dir_path.rglob("*"):
        if f.is_file():
            total += f.stat().st_size
    return total


# ---------------------------------------------------------------------------
# Action implementations
# ---------------------------------------------------------------------------


def create_run(
    project_root: Path,
    case_name: str,
    *,
    dest_dir: Path | None = None,
    display_name: str = "",
    params: dict[str, Any] | None = None,
) -> ActionResult:
    """Create a new run directory from a case definition."""
    from runops.core.project import load_project
    from runops.core.run_creation import create_case_run

    try:
        project = load_project(project_root)
        result = create_case_run(
            project,
            case_name,
            dest_dir=dest_dir,
            display_name=display_name,
            params=params,
        )

        return ActionResult(
            action="create_run",
            status=ActionStatus.SUCCESS,
            message=f"Created run {result.run_info.run_id}",
            data={
                "run_id": result.run_info.run_id,
                "run_dir": str(result.run_info.run_dir),
                "display_name": result.run_info.display_name,
                "warnings": list(result.warnings),
            },
            state_after=RunState.CREATED.value,
        )
    except SimctlError as e:
        return _error("create_run", str(e))


def create_survey(project_root: Path, survey_dir: Path) -> ActionResult:
    """Expand a survey.toml into created run directories."""
    from runops.core.project import load_project
    from runops.core.run_creation import create_survey_runs

    try:
        project = load_project(project_root)
        created_runs = create_survey_runs(project, survey_dir)
    except SimctlError as e:
        return _error("create_survey", str(e))

    run_payload: list[dict[str, Any]] = []
    aggregated_warnings: list[dict[str, str]] = []
    for result in created_runs:
        run_payload.append(
            {
                "run_id": result.run_info.run_id,
                "run_dir": str(result.run_info.run_dir),
                "display_name": result.run_info.display_name,
                "warnings": list(result.warnings),
            }
        )
        for warning in result.warnings:
            aggregated_warnings.append(
                {
                    "display_name": result.run_info.display_name,
                    "message": warning,
                }
            )

    if not run_payload:
        return ActionResult(
            action="create_survey",
            status=ActionStatus.SUCCESS,
            message=f"No parameter combinations to expand in {survey_dir}",
            data={
                "survey_dir": str(survey_dir),
                "created_count": 0,
                "runs": [],
                "warnings": [],
            },
        )

    return ActionResult(
        action="create_survey",
        status=ActionStatus.SUCCESS,
        message=f"Created {len(run_payload)} runs",
        data={
            "survey_dir": str(survey_dir),
            "created_count": len(run_payload),
            "runs": run_payload,
            "warnings": aggregated_warnings,
        },
        state_after=RunState.CREATED.value,
    )


def submit_run(
    run_dir: Path,
    *,
    queue_name: str = "",
    qos: str = "",
    afterok: str = "",
) -> ActionResult:
    """Submit a run to Slurm via sbatch."""
    from runops.core.manifest import read_manifest, update_manifest
    from runops.core.retry import get_attempt_count
    from runops.core.state import update_state
    from runops.slurm.submit import (
        SlurmNotFoundError,
        SlurmSubmitError,
        sbatch_submit,
    )

    state_str, err = _require_state(run_dir, RunState.CREATED)
    if err:
        return _precondition_fail("submit_run", err)

    job_script = run_dir / "submit" / "job.sh"
    if not job_script.exists():
        return _precondition_fail("submit_run", f"Job script not found: {job_script}")

    input_dir = run_dir / "input"
    if not input_dir.is_dir() or not any(input_dir.iterdir()):
        return _precondition_fail(
            "submit_run",
            f"input/ directory is empty or missing in {run_dir}",
        )

    try:
        job_content = job_script.read_text(encoding="utf-8")
    except OSError as e:
        return _error("submit_run", f"Failed to read job script: {e}")

    if "#SBATCH" not in job_content:
        return _precondition_fail(
            "submit_run",
            "job.sh does not contain expected #SBATCH directives",
        )

    manifest = read_manifest(run_dir)
    run_id = manifest.run.get("id", run_dir.name)
    warnings: list[str] = []
    tags = manifest.classification.get("tags", [])
    if "production" in tags and manifest.simulator_source.get("git_dirty", False):
        warnings.append("production run submitted with dirty git working tree")

    work_dir = run_dir / "work"
    if not work_dir.is_dir():
        work_dir = run_dir

    extra_args: list[str] = []
    if queue_name:
        extra_args.append(f"--partition={queue_name}")
    if qos:
        extra_args.append(f"--qos={qos}")

    try:
        job_id = sbatch_submit(
            job_script,
            work_dir,
            extra_args=extra_args or None,
            afterok=afterok or None,
        )
    except (SlurmNotFoundError, SlurmSubmitError, FileNotFoundError, RuntimeError) as e:
        return _error("submit_run", f"sbatch failed: {e}")

    # Update manifest
    now = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
    attempt = get_attempt_count(manifest.job) + 1
    existing_attempts: list[dict[str, str]] = list(manifest.job.get("attempts", []))
    existing_attempts.append(
        {
            "job_id": job_id,
            "submitted_at": now,
            "attempt": str(attempt),
        }
    )
    update_manifest(
        run_dir,
        {
            "run": {
                "last_slurm_state": "",
            },
            "job": {
                "job_id": job_id,
                "submitted_at": now,
                "attempt": attempt,
                "attempts": existing_attempts,
                "queue": queue_name or manifest.job.get("queue", ""),
            },
        },
    )
    try:
        update_state(run_dir, RunState.SUBMITTED)
    except SimctlError as e:
        return _error("submit_run", f"State transition failed: {e}")

    return ActionResult(
        action="submit_run",
        status=ActionStatus.SUCCESS,
        message=f"Submitted job {job_id} (attempt {attempt})",
        data={
            "job_id": job_id,
            "attempt": attempt,
            "run_id": run_id,
            "warnings": warnings,
        },
        state_before=state_str,
        state_after=RunState.SUBMITTED.value,
    )


def sync_run(run_dir: Path) -> ActionResult:
    """Synchronize run state with Slurm."""
    from runops.core.manifest import read_manifest, update_manifest
    from runops.core.state import update_state
    from runops.slurm.query import SlurmQueryError, query_job_status

    manifest = read_manifest(run_dir)
    run_id = manifest.run.get("id", run_dir.name)
    job_id = manifest.job.get("job_id", "")
    if not job_id:
        return _precondition_fail("sync_run", "No job_id recorded in manifest")

    state_str, err = _require_state(run_dir, RunState.SUBMITTED, RunState.RUNNING)
    if err:
        return _precondition_fail("sync_run", err)

    try:
        job_status = query_job_status(job_id)
    except (SlurmQueryError, RuntimeError) as e:
        return _error("sync_run", f"Slurm query failed: {e}")

    new_state = job_status.run_state
    if new_state.value == state_str:
        try:
            update_manifest(
                run_dir,
                {"run": {"last_slurm_state": job_status.slurm_state}},
            )
        except SimctlError as e:
            return _error("sync_run", f"State update failed: {e}")

        return ActionResult(
            action="sync_run",
            status=ActionStatus.SUCCESS,
            message=f"State unchanged: {state_str}",
            data={"run_id": run_id, "slurm_state": job_status.slurm_state},
            state_before=state_str,
            state_after=state_str,
        )

    try:
        update_state(
            run_dir,
            new_state,
            reconcile=True,
            reason=job_status.failure_reason,
            slurm_state=job_status.slurm_state,
        )
    except SimctlError as e:
        return _error("sync_run", f"State update failed: {e}")

    return ActionResult(
        action="sync_run",
        status=ActionStatus.SUCCESS,
        message=f"State: {state_str} -> {new_state.value}",
        data={
            "run_id": run_id,
            "slurm_state": job_status.slurm_state,
            "failure_reason": job_status.failure_reason,
            "exit_code": job_status.exit_code,
        },
        state_before=state_str,
        state_after=new_state.value,
    )


def show_log(run_dir: Path, *, lines: int = 50) -> ActionResult:
    """Read the latest job stdout log."""
    # Look for common log file patterns
    work_dir = run_dir / "work"
    log_candidates = [
        *sorted(work_dir.glob("slurm-*.out"), reverse=True),
        *sorted(work_dir.glob("*.log"), reverse=True),
        *sorted(work_dir.glob("*.out"), reverse=True),
    ]

    if not log_candidates:
        return _precondition_fail("show_log", "No log files found in work/")

    log_file = log_candidates[0]
    try:
        all_lines = log_file.read_text(encoding="utf-8").splitlines()
        tail = all_lines[-lines:] if len(all_lines) > lines else all_lines
    except OSError as e:
        return _error("show_log", f"Failed to read log: {e}")

    return ActionResult(
        action="show_log",
        status=ActionStatus.SUCCESS,
        message=f"Last {len(tail)} lines from {log_file.name}",
        data={
            "log_file": str(log_file),
            "total_lines": len(all_lines),
            "lines": tail,
        },
    )


def summarize_run(run_dir: Path) -> ActionResult:
    """Generate an analysis summary for a completed run."""
    _state_str, err = _require_state(run_dir, RunState.COMPLETED)
    if err:
        return _precondition_fail("summarize_run", err)

    try:
        from runops.core.analysis import generate_run_summary

        result = generate_run_summary(run_dir)
    except (KeyError, OSError, TypeError, json.JSONDecodeError, SimctlError) as e:
        return _error("summarize_run", str(e))

    return ActionResult(
        action="summarize_run",
        status=ActionStatus.SUCCESS,
        message=f"Summary written to {result.summary_path}",
        data={
            "run_id": result.run_id,
            "summary": result.summary,
            "summary_path": str(result.summary_path),
            "script_path": str(result.script_path) if result.script_path else "",
            "warnings": list(result.warnings),
        },
    )


def collect_survey(survey_dir: Path) -> ActionResult:
    """Aggregate results across all runs in a survey directory."""
    from runops.core.discovery import discover_runs
    from runops.core.manifest import read_manifest

    run_dirs = discover_runs(survey_dir)
    if not run_dirs:
        return _precondition_fail("collect_survey", f"No runs found under {survey_dir}")

    summary: dict[str, int] = {s.value: 0 for s in RunState}
    run_data: list[dict[str, Any]] = []
    for rd in run_dirs:
        try:
            m = read_manifest(rd)
            state = m.run.get("status", "unknown")
            summary[state] = summary.get(state, 0) + 1
            run_data.append(
                {
                    "run_id": m.run.get("id", ""),
                    "status": state,
                    "display_name": m.run.get("display_name", ""),
                }
            )
        except SimctlError:
            continue

    if summary.get(RunState.COMPLETED.value, 0) == 0:
        return _precondition_fail(
            "collect_survey",
            f"No completed runs found under {survey_dir}",
        )

    try:
        from runops.core.analysis import collect_survey_summaries

        result = collect_survey_summaries(survey_dir)
    except (OSError, TypeError, json.JSONDecodeError, SimctlError) as e:
        return _error("collect_survey", str(e))

    return ActionResult(
        action="collect_survey",
        status=ActionStatus.SUCCESS,
        message=f"Collected {result.summaries_collected} summaries",
        data={
            "total_runs": len(run_data),
            "state_counts": {k: v for k, v in summary.items() if v > 0},
            "csv_path": str(result.csv_path),
            "json_path": str(result.json_path),
            "figures_path": str(result.figures_path),
            "report_path": str(result.report_path),
            "generated_summaries": result.generated_summaries,
            "missing_summaries": result.missing_summaries,
            "figure_count": len(result.figures),
            "warnings": list(result.warnings),
        },
    )


def export_publication(
    target_path: Path,
    paper_id: str,
    *,
    export_name: str = "",
    mode: str = "copy",
    include_figures: bool = True,
    include_plots: bool = True,
    force: bool = False,
) -> ActionResult:
    """Create a project-side publication export bundle."""
    from runops.core.publication import export_publication_bundle

    try:
        result = export_publication_bundle(
            target_path,
            paper_id=paper_id,
            name=export_name,
            mode=mode,
            include_figures=include_figures,
            include_plots=include_plots,
            force=force,
        )
    except SimctlError as e:
        return _error("export_publication", str(e))

    return ActionResult(
        action="export_publication",
        status=ActionStatus.SUCCESS,
        message=(
            f"Exported {result.target_kind} bundle for paper {paper_id!r} "
            f"to {result.export_dir}"
        ),
        data={
            "paper_id": result.paper_id,
            "export_name": result.export_name,
            "target_kind": result.target_kind,
            "target_path": str(result.target_path),
            "export_dir": str(result.export_dir),
            "manifest_path": str(result.manifest_path),
            "readme_path": str(result.readme_path),
            "mode": result.mode,
            "source_run_ids": list(result.source_run_ids),
            "file_count": len(result.files),
            "warnings": list(result.warnings),
        },
    )


def retry_run(
    run_dir: Path,
    *,
    adjustments: dict[str, Any] | None = None,
    reviewed_log: bool = False,
) -> ActionResult:
    """Resubmit a failed or cancelled run as a new attempt."""
    from runops.core.manifest import read_manifest, update_manifest
    from runops.core.retry import get_attempt_count

    state_str, err = _require_state(run_dir, RunState.FAILED, RunState.CANCELLED)
    if err:
        return _precondition_fail("retry_run", err)

    manifest = read_manifest(run_dir)
    attempt = get_attempt_count(manifest.job)
    failure_reason = manifest.run.get("failure_reason", "")

    if attempt >= 3:
        return _precondition_fail(
            "retry_run",
            "Max attempts (3) reached. Manual inspection required.",
        )
    if failure_reason == "exit_error" and not reviewed_log:
        return _precondition_fail(
            "retry_run",
            "failure_reason 'exit_error' requires log review before retrying",
        )

    # Reset state to created for resubmission
    update_manifest(
        run_dir,
        {
            "run": {
                "status": RunState.CREATED.value,
                "failure_reason": "",
                "last_slurm_state": "",
            },
            "job": {
                "job_id": "",
                "submitted_at": "",
                "attempt": attempt,
                "retry_adjustments": adjustments or {},
            },
        },
    )

    return ActionResult(
        action="retry_run",
        status=ActionStatus.SUCCESS,
        message=f"Reset to created for retry (attempt {attempt + 1})",
        data={
            "previous_attempt": attempt,
            "next_attempt": attempt + 1,
            "adjustments": adjustments or {},
        },
        state_before=state_str,
        state_after=RunState.CREATED.value,
    )


def archive_run(run_dir: Path) -> ActionResult:
    """Archive a completed run."""
    from runops.core.manifest import read_manifest
    from runops.core.state import update_state

    state_str, err = _require_state(run_dir, RunState.COMPLETED)
    if err:
        return _precondition_fail("archive_run", err)

    run_id = read_manifest(run_dir).run.get("id", run_dir.name)

    try:
        update_state(run_dir, RunState.ARCHIVED)
    except SimctlError as e:
        return _error("archive_run", str(e))

    return ActionResult(
        action="archive_run",
        status=ActionStatus.SUCCESS,
        message="Run archived",
        data={"run_id": run_id},
        state_before=state_str,
        state_after=RunState.ARCHIVED.value,
    )


def purge_work(run_dir: Path) -> ActionResult:
    """Delete purgeable work outputs from an archived run."""
    from runops.core.state import update_state

    state_str, err = _require_state(run_dir, RunState.ARCHIVED)
    if err:
        return _precondition_fail("purge_work", err)

    work_dir = run_dir / "work"
    targets = ["outputs", "restart", "tmp"]
    removed_dirs: list[str] = []
    total_removed = 0

    for dirname in targets:
        target_dir = work_dir / dirname
        if not target_dir.is_dir():
            continue
        try:
            total_removed += _dir_size(target_dir)
            shutil.rmtree(target_dir)
        except OSError as e:
            return _error("purge_work", f"Failed to remove {target_dir}: {e}")
        removed_dirs.append(dirname)

    try:
        update_state(run_dir, RunState.PURGED)
    except SimctlError as e:
        return _error("purge_work", str(e))

    return ActionResult(
        action="purge_work",
        status=ActionStatus.SUCCESS,
        message="Purged work files",
        data={
            "removed_dirs": removed_dirs,
            "bytes_removed": total_removed,
        },
        state_before=state_str,
        state_after=RunState.PURGED.value,
    )


def cancel_run(run_dir: Path) -> ActionResult:
    """Cancel an active Slurm job (scancel) and sync the run state.

    Wraps ``scancel <job_id>`` followed by ``sync_run`` so the manifest is
    updated atomically once Slurm reports the cancellation.  Use this instead
    of bare ``scancel`` so the run state ends up consistent.
    """
    from runops.core.manifest import read_manifest
    from runops.slurm.submit import (
        SlurmCancelError,
        SlurmNotFoundError,
        scancel_job,
    )

    manifest = read_manifest(run_dir)
    run_id = manifest.run.get("id", run_dir.name)
    job_id = manifest.job.get("job_id", "")
    if not job_id:
        return _precondition_fail("cancel_run", "No job_id recorded in manifest")

    state_str, err = _require_state(run_dir, RunState.SUBMITTED, RunState.RUNNING)
    if err:
        return _precondition_fail("cancel_run", err)

    try:
        scancel_job(job_id)
    except SlurmNotFoundError as e:
        return _error("cancel_run", str(e))
    except SlurmCancelError as e:
        return _error("cancel_run", str(e))

    # Slurm typically takes a moment to mark the job as cancelled.  Run
    # sync_run so the manifest reflects whatever Slurm reports right now;
    # the caller can re-sync later if needed.
    sync_result = sync_run(run_dir)

    if sync_result.status is not ActionStatus.SUCCESS:
        return ActionResult(
            action="cancel_run",
            status=ActionStatus.SUCCESS,
            message=(
                f"scancel sent for job {job_id}; sync did not complete "
                f"({sync_result.message}).  Re-run `runops runs sync` shortly."
            ),
            data={"run_id": run_id, "job_id": job_id},
            state_before=state_str,
            state_after=state_str,
        )

    return ActionResult(
        action="cancel_run",
        status=ActionStatus.SUCCESS,
        message=f"Cancelled job {job_id}; {sync_result.message}",
        data={
            "run_id": run_id,
            "job_id": job_id,
            "slurm_state": sync_result.data.get("slurm_state", ""),
        },
        state_before=state_str,
        state_after=sync_result.state_after or state_str,
    )


def delete_run(run_dir: Path) -> ActionResult:
    """Hard-delete a run directory.

    Only runs in a terminal non-completed state (``created``, ``cancelled``,
    or ``failed``) may be deleted.  Completed and archived runs hold valuable
    results and must go through the archive/purge flow instead.
    """
    state_str, err = _require_state(
        run_dir,
        RunState.CREATED,
        RunState.CANCELLED,
        RunState.FAILED,
    )
    if err:
        return _precondition_fail("delete_run", err)

    from runops.core.manifest import read_manifest

    run_id = read_manifest(run_dir).run.get("id", run_dir.name)
    bytes_removed = _dir_size(run_dir)

    try:
        shutil.rmtree(run_dir)
    except OSError as e:
        return _error("delete_run", f"Failed to remove {run_dir}: {e}")

    return ActionResult(
        action="delete_run",
        status=ActionStatus.SUCCESS,
        message=f"Deleted run {run_id}",
        data={"run_id": run_id, "bytes_removed": bytes_removed},
        state_before=state_str,
        state_after="",
    )


def save_insight(
    project_root: Path,
    *,
    name: str,
    content: str,
    insight_type: str = "result",
    simulator: str = "",
    tags: list[str] | None = None,
    source_project: str = "",
) -> ActionResult:
    """Record a markdown knowledge insight."""
    from runops.core.knowledge import (
        INSIGHT_TYPES,
        Insight,
        get_insights_dir,
        write_insight,
    )

    if insight_type not in INSIGHT_TYPES:
        return _error(
            "save_insight",
            "Invalid insight type "
            f"{insight_type!r}. Must be one of: {', '.join(sorted(INSIGHT_TYPES))}",
        )

    insight = Insight(
        name=name,
        type=insight_type,
        simulator=simulator,
        tags=tags or [],
        source_project=source_project or project_root.name,
        content=content.strip(),
    )

    try:
        path = write_insight(get_insights_dir(project_root), insight)
    except OSError as e:
        return _error("save_insight", str(e))

    return ActionResult(
        action="save_insight",
        status=ActionStatus.SUCCESS,
        message=f"Saved insight {name}",
        data={
            "name": name,
            "path": str(path),
            "insight_type": insight_type,
            "simulator": simulator,
            "tags": list(tags or []),
        },
    )


def add_fact(
    project_root: Path,
    *,
    claim: str,
    fact_type: str = "observation",
    simulator: str = "",
    scope_case: str = "",
    scope_text: str = "",
    param_name: str = "",
    confidence: str = "medium",
    source_run: str = "",
    evidence_kind: str = "",
    evidence_ref: str = "",
    tags: list[str] | None = None,
    supersedes: str = "",
) -> ActionResult:
    """Record a structured knowledge fact.

    This delegates to the knowledge module's save_fact function.
    """
    from runops.core.knowledge import Fact, next_fact_id, save_fact

    fact_id = next_fact_id(project_root)

    fact = Fact(
        id=fact_id,
        claim=claim,
        fact_type=fact_type,
        simulator=simulator,
        scope_case=scope_case,
        scope_text=scope_text,
        param_name=param_name,
        confidence=confidence,
        source_run=source_run,
        source_project=project_root.name,
        evidence_kind=evidence_kind,
        evidence_ref=evidence_ref,
        tags=tags or [],
        supersedes=supersedes,
    )
    try:
        save_fact(project_root, fact)
    except (RuntimeError, OSError) as e:
        return _error("add_fact", str(e))

    return ActionResult(
        action="add_fact",
        status=ActionStatus.SUCCESS,
        message=f"Saved fact {fact_id}: {claim}",
        data={"fact_id": fact_id},
    )


def promote_fact(project_root: Path, fact_id: str) -> ActionResult:
    """Promote an imported candidate fact into local curated facts."""
    from runops.core.knowledge import promote_candidate_fact

    try:
        promoted = promote_candidate_fact(project_root, fact_id)
    except LookupError as exc:
        return _precondition_fail("promote_fact", str(exc))
    except RuntimeError as exc:
        return _error("promote_fact", str(exc))

    return ActionResult(
        action="promote_fact",
        status=ActionStatus.SUCCESS,
        message=f"Promoted fact {fact_id} -> {promoted.id}",
        data={
            "fact_id": promoted.id,
            "source_fact_id": fact_id,
            "confidence": promoted.confidence,
            "fact_type": promoted.fact_type,
        },
    )


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

#: Map action name -> callable.
_DISPATCH: dict[str, Any] = {
    "create_run": create_run,
    "create_survey": create_survey,
    "submit_run": submit_run,
    "sync_run": sync_run,
    "show_log": show_log,
    "summarize_run": summarize_run,
    "collect_survey": collect_survey,
    "export_publication": export_publication,
    "retry_run": retry_run,
    "archive_run": archive_run,
    "purge_work": purge_work,
    "cancel_run": cancel_run,
    "delete_run": delete_run,
    "save_insight": save_insight,
    "add_fact": add_fact,
    "promote_fact": promote_fact,
}


def execute_action(name: str, **kwargs: Any) -> ActionResult:
    """Execute a named action with keyword arguments.

    This is the primary entry point for agents.

    Args:
        name: Action name (must be in ACTION_SPECS).
        **kwargs: Arguments matching the action's parameter spec.

    Returns:
        ActionResult with status, message, and data.
    """
    if name not in _DISPATCH:
        return ActionResult(
            action=name,
            status=ActionStatus.ERROR,
            message=f"Unknown action: {name!r}. Available: {sorted(_DISPATCH)}",
        )

    fn = _DISPATCH[name]
    try:
        result: ActionResult = fn(**kwargs)
        return result
    except TypeError as e:
        return ActionResult(
            action=name,
            status=ActionStatus.ERROR,
            message=f"Invalid arguments for {name}: {e}",
        )
    except Exception as e:
        logger.exception("Unexpected error in action %s", name)
        return ActionResult(
            action=name,
            status=ActionStatus.ERROR,
            message=f"Unexpected error: {e}",
        )
