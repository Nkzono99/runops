"""Machine-readable action specifications for agent workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


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
        cli_commands: Public CLI command paths that expose this action.
        mcp_tools: MCP tool names that expose or plan this action.
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
    cli_commands: tuple[tuple[str, ...], ...] = ()
    mcp_tools: tuple[str, ...] = ()

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
            "cli_commands": [list(command) for command in self.cli_commands],
            "mcp_tools": list(self.mcp_tools),
        }
        if self.state_change:
            data["state_change"] = self.state_change
        if self.confirmation_reason:
            data["confirmation_reason"] = self.confirmation_reason
        if self.confirmation_conditions:
            data["confirmation_conditions"] = list(self.confirmation_conditions)
        return data


ACTION_SPECS: dict[str, ActionSpec] = {
    "create_experiment": ActionSpec(
        name="create_experiment",
        description="Create a typed experiment record and proposal attachment.",
        required_params=("project_root", "experiment_id", "spec_path"),
        optional_params=("dry_run",),
        preconditions=(
            "project loaded",
            "experiment ledger schema == 2",
            "experiment id unused",
        ),
        state_change="-> experiment proposed",
        risk_level="low",
        cost_class="low",
        cli_commands=(("experiment", "new"),),
        mcp_tools=("runops.experiment.create",),
    ),
    "create_run": ActionSpec(
        name="create_run",
        description="Create a new run directory from a case.",
        required_params=("project_root", "case_name"),
        optional_params=("dest_dir", "display_name", "params"),
        preconditions=("project loaded", "case exists"),
        state_change="-> created",
        risk_level="medium",
        cost_class="medium",
        cli_commands=(("runs", "create"),),
    ),
    "create_survey": ActionSpec(
        name="create_survey",
        description="Expand a survey.toml into created run directories.",
        required_params=("project_root", "survey_dir"),
        preconditions=("project loaded", "survey.toml exists", "base case exists"),
        state_change="N x -> created",
        risk_level="medium",
        cost_class="medium",
        cli_commands=(("runs", "sweep"),),
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
        cli_commands=(("runs", "submit"),),
        mcp_tools=("runops.job.plan_submit", "runops.job.submit"),
    ),
    "sync_run": ActionSpec(
        name="sync_run",
        description="Synchronize run state with Slurm.",
        required_params=("run_dir",),
        preconditions=("run state in {submitted, running}", "job_id recorded"),
        state_change="submitted/running -> completed/failed/cancelled",
        risk_level="low",
        cost_class="low",
        cli_commands=(("runs", "sync"),),
    ),
    "show_log": ActionSpec(
        name="show_log",
        description="Read latest job stdout and return tail lines.",
        required_params=("run_dir",),
        optional_params=("lines",),
        preconditions=("run has been submitted at least once",),
        risk_level="low",
        cost_class="low",
        cli_commands=(("runs", "log"),),
        mcp_tools=("runops.run.logs",),
    ),
    "summarize_run": ActionSpec(
        name="summarize_run",
        description="Generate analysis summary for a completed run.",
        required_params=("run_dir",),
        preconditions=("run state == completed",),
        risk_level="low",
        cost_class="medium",
        cli_commands=(("analyze", "summarize"),),
    ),
    "collect_survey": ActionSpec(
        name="collect_survey",
        description="Aggregate results across all runs in a survey.",
        required_params=("survey_dir",),
        preconditions=("survey directory contains at least one completed run",),
        risk_level="low",
        cost_class="medium",
        cli_commands=(("analyze", "collect"),),
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
            "paper_status",
            "force",
        ),
        preconditions=("target exists", "target is a run or contains runs"),
        risk_level="low",
        cost_class="medium",
        cli_commands=(("analyze", "export"),),
    ),
    "retry_run": ActionSpec(
        name="retry_run",
        description="Prepare a failed or cancelled run for resubmission.",
        required_params=("run_dir",),
        optional_params=("adjustments", "reviewed_log"),
        preconditions=("run state == failed or cancelled",),
        state_change="failed/cancelled -> created",
        risk_level="medium",
        cost_class="medium",
        confirmation_conditions=(
            "required when retry adjustments increase walltime, memory, or nodes",
        ),
        cli_commands=(("runs", "retry"),),
    ),
    "plan_retry": ActionSpec(
        name="plan_retry",
        description=(
            "Record retry intent and partial-output diagnostics without "
            "resetting the run."
        ),
        required_params=("run_dir",),
        optional_params=("adjustments", "reviewed_log", "note"),
        preconditions=("run state == failed or cancelled",),
        risk_level="low",
        cost_class="low",
        cli_commands=(("runs", "retry"),),
    ),
    "archive_run": ActionSpec(
        name="archive_run",
        description="Mark a completed run as archived, optionally relocating it.",
        required_params=("run_dir",),
        optional_params=("move_to",),
        preconditions=("run state == completed",),
        state_change="completed -> archived",
        destructive=True,
        risk_level="high",
        cost_class="low",
        requires_confirmation=True,
        confirmation_reason=(
            "Archiving changes lifecycle state and may move run directories."
        ),
        cli_commands=(("runs", "archive"),),
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
        cli_commands=(("runs", "purge-work"),),
    ),
    "cancel_run": ActionSpec(
        name="cancel_run",
        description="Cancel an active Slurm job (scancel) and sync the run state.",
        required_params=("run_dir",),
        preconditions=("run state in {submitted, running}", "job_id recorded"),
        state_change="submitted/running -> cancelled",
        risk_level="high",
        cost_class="low",
        requires_confirmation=True,
        confirmation_reason="Cancelling stops an active Slurm job.",
        cli_commands=(("runs", "cancel"),),
        mcp_tools=("runops.job.cancel",),
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
        cli_commands=(("runs", "delete"),),
        mcp_tools=("runops.run.delete",),
    ),
    "save_insight": ActionSpec(
        name="save_insight",
        description="Record a markdown knowledge insight.",
        required_params=("project_root", "name", "content"),
        optional_params=("insight_type", "simulator", "tags", "source_project"),
        preconditions=("project loaded",),
        risk_level="low",
        cost_class="low",
        cli_commands=(("knowledge", "save"),),
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
        cli_commands=(("knowledge", "add-fact"),),
    ),
    "promote_fact": ActionSpec(
        name="promote_fact",
        description="Promote an imported candidate fact into local curated facts.",
        required_params=("project_root", "fact_id"),
        preconditions=("candidate fact exists",),
        risk_level="low",
        cost_class="low",
        cli_commands=(("knowledge", "promote-fact"),),
    ),
}


def list_actions() -> list[ActionSpec]:
    """Return all registered action specifications."""
    return list(ACTION_SPECS.values())


def get_action_spec(name: str) -> ActionSpec | None:
    """Look up an action spec by name."""
    return ACTION_SPECS.get(name)
