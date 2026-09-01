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
        description="Admit one bounded research question as an Experiment.",
        required_params=(
            "project_root",
            "title",
            "question",
            "intent",
            "max_planned_points",
            "max_materialized_runs",
            "max_active_runs",
            "max_core_hours",
            "max_unreviewed_runs",
            "expires_at",
            "exit_criteria",
        ),
        optional_params=(
            "baseline_run_ids",
            "baseline_reason",
            "review_due",
            "created_by",
        ),
        preconditions=(
            "project loaded",
            "active Experiment WIP limit permits admission",
            "exactly one baseline source or no-baseline reason supplied",
            "expires_at is timezone-aware and later than admission",
            "at least one exit criterion supplied",
        ),
        state_change="-> active",
        risk_level="medium",
        cost_class="low",
        cli_commands=(("experiments", "create"),),
        mcp_tools=(),
    ),
    "review_experiment": ActionSpec(
        name="review_experiment",
        description="Record a structured decision on an active Experiment.",
        required_params=("project_root", "experiment", "decision", "reason"),
        optional_params=("outcome", "successor"),
        preconditions=(
            "Experiment exists",
            "Experiment lifecycle is active",
            "review reason is non-empty",
        ),
        risk_level="low",
        cost_class="low",
        cli_commands=(("experiments", "review"),),
        mcp_tools=(),
    ),
    "close_experiment": ActionSpec(
        name="close_experiment",
        description="Close an Experiment with a terminal research decision.",
        required_params=(
            "project_root",
            "experiment",
            "decision",
            "outcome",
            "reason",
        ),
        optional_params=("successor",),
        preconditions=(
            "Experiment exists",
            "Experiment lifecycle is active",
            "decision is revise, stop, or accept",
            "outcome is terminal and reason is non-empty",
        ),
        state_change="active -> closed",
        risk_level="medium",
        cost_class="low",
        cli_commands=(("experiments", "close"),),
        mcp_tools=(),
    ),
    "prepare_test_attempt": ActionSpec(
        name="prepare_test_attempt",
        description=(
            "Prepare or cache-reuse an isolated smoke/debug TestAttempt without "
            "creating a formal Run."
        ),
        required_params=("project_root", "case", "kind"),
        optional_params=(
            "profile",
            "source_commit",
            "executable_hash",
            "adapter",
            "adapter_version",
            "cache_ttl_hours",
            "rerun",
        ),
        preconditions=(
            "project and case exist",
            "kind is smoke or debug",
            "cache TTL is non-negative",
        ),
        state_change="-> prepared or existing passed evidence reused",
        risk_level="low",
        cost_class="low",
        cli_commands=(("test", "smoke"), ("test", "debug")),
        mcp_tools=(),
    ),
    "record_test_result": ActionSpec(
        name="record_test_result",
        description="Record a terminal observation for one TestAttempt.",
        required_params=("project_root", "attempt_id", "result"),
        optional_params=("observation",),
        preconditions=(
            "TestAttempt exists",
            "TestAttempt is prepared or submitted",
            "result is passed, failed, or skipped",
        ),
        state_change="prepared/submitted -> passed/failed/skipped",
        risk_level="low",
        cost_class="low",
        cli_commands=(("test", "record"),),
        mcp_tools=(),
    ),
    "clean_test_attempts": ActionSpec(
        name="clean_test_attempts",
        description="Delete terminal TestAttempts older than an explicit threshold.",
        required_params=("project_root", "older_than_days"),
        preconditions=(
            "age threshold is non-negative",
            "no matching prepared or submitted TestAttempt exists",
        ),
        destructive=True,
        risk_level="medium",
        cost_class="low",
        confirmation_conditions=(
            "age threshold selects terminal TestAttempt directories for deletion",
        ),
        cli_commands=(("test", "clean"),),
        mcp_tools=(),
    ),
    "create_result": ActionSpec(
        name="create_result",
        description="Create one canonical draft Result within its active budget.",
        required_params=("project_root", "name"),
        optional_params=("budget",),
        preconditions=(
            "project loaded",
            "active Result budget permits creation",
        ),
        state_change="-> draft",
        risk_level="low",
        cost_class="low",
        cli_commands=(("research", "new-result"),),
        mcp_tools=(),
    ),
    "check_result": ActionSpec(
        name="check_result",
        description="Validate Result evidence and seal integrity without mutation.",
        required_params=("project_root", "result"),
        preconditions=("Result exists and has a readable manifest",),
        risk_level="low",
        cost_class="low",
        cli_commands=(("research", "check-result"),),
        mcp_tools=(),
    ),
    "seal_result": ActionSpec(
        name="seal_result",
        description="Seal a canonical Result with immutable evidence receipts.",
        required_params=("project_root", "result", "claim", "outcome", "evidence"),
        preconditions=(
            "Result is canonical and active",
            "claim and terminal outcome are supplied",
            "included evidence is reviewed and ready",
            "every included or excluded evidence item has a reason",
        ),
        state_change="draft -> sealed",
        risk_level="medium",
        cost_class="low",
        cli_commands=(("research", "seal"),),
        mcp_tools=(),
    ),
    "archive_result": ActionSpec(
        name="archive_result",
        description="Move one Result intact out of the active workspace.",
        required_params=("project_root", "result_id"),
        preconditions=("active Result exists", "archive destination is absent"),
        state_change="active -> archived",
        risk_level="medium",
        cost_class="low",
        cli_commands=(("research", "archive"),),
        mcp_tools=(),
    ),
    "restore_result": ActionSpec(
        name="restore_result",
        description="Restore one archived Result within the active Result budget.",
        required_params=("project_root", "result_id"),
        optional_params=("budget",),
        preconditions=(
            "archived Result exists",
            "active Result budget permits restoration",
            "active destination is absent",
        ),
        state_change="archived -> active",
        risk_level="medium",
        cost_class="low",
        cli_commands=(("research", "restore"),),
        mcp_tools=(),
    ),
    "create_run": ActionSpec(
        name="create_run",
        description="Create a new run directory from a case.",
        required_params=("project_root", "case_name"),
        optional_params=(
            "dest_dir",
            "display_name",
            "params",
            "experiment_id",
            "purpose",
            "created_by",
        ),
        preconditions=(
            "project loaded",
            "case exists",
            "active Experiment supplied when project policy requires it",
        ),
        state_change="-> created",
        risk_level="medium",
        cost_class="medium",
        cli_commands=(("runs", "create"),),
    ),
    "clone_run": ActionSpec(
        name="clone_run",
        description=(
            "Derive a Run from a completed-equivalent source snapshot, with "
            "optional parameter overrides."
        ),
        required_params=("source_dir",),
        optional_params=(
            "dest_dir",
            "overrides",
            "experiment_id",
            "purpose",
        ),
        preconditions=(
            "source Run is completed-equivalent and remains stable under lock",
            "formal destination is inside the active project runs namespace",
            "Experiment admission and budget permit a new Run",
        ),
        state_change="completed-equivalent source -> created derivative",
        risk_level="medium",
        cost_class="medium",
        cli_commands=(("runs", "clone"),),
    ),
    "extend_run": ActionSpec(
        name="extend_run",
        description=(
            "Create a continuation from a completed-equivalent source snapshot."
        ),
        required_params=("source_dir",),
        optional_params=(
            "dest_dir",
            "nstep",
            "experiment_id",
            "purpose",
            "submit",
        ),
        preconditions=(
            "source Run is completed-equivalent and remains stable under lock",
            "adapter can prepare continuation input",
            "Experiment admission and budget permit a new Run",
        ),
        state_change="completed-equivalent source -> created/submitted continuation",
        risk_level="high",
        cost_class="high",
        confirmation_conditions=("--run submits the continuation to Slurm",),
        cli_commands=(("runs", "extend"),),
    ),
    "inspect_regeneration": ActionSpec(
        name="inspect_regeneration",
        description=(
            "Inspect case-template drift without mutating a Run's frozen inputs."
        ),
        required_params=("run_dir",),
        optional_params=("dry_run",),
        preconditions=(
            "Run state permits drift inspection",
            "--dry-run is supplied because in-place regeneration is disabled",
        ),
        risk_level="low",
        cost_class="low",
        cli_commands=(("runs", "regenerate"),),
    ),
    "review_run": ActionSpec(
        name="review_run",
        description="Acknowledge a terminal Run without selecting Result evidence.",
        required_params=("run_dir", "reason"),
        optional_params=("reviewed_by",),
        preconditions=("run state is terminal", "review reason is non-empty"),
        risk_level="low",
        cost_class="low",
        cli_commands=(("runs", "review"),),
    ),
    "create_survey": ActionSpec(
        name="create_survey",
        description="Materialize selected points from an unchanged Survey plan.",
        required_params=("project_root", "survey_dir", "expected_plan_hash"),
        optional_params=("point_refs", "all_points"),
        preconditions=(
            "plan hash matches current inputs",
            "explicit points or --all selected",
            "Experiment and Survey budgets permit new Runs",
        ),
        state_change="selected points -> created",
        risk_level="high",
        cost_class="medium",
        cli_commands=(("runs", "sweep"),),
    ),
    "plan_survey": ActionSpec(
        name="plan_survey",
        description="Preview lazy Survey candidates without creating directories.",
        required_params=("project_root", "survey_dir"),
        optional_params=("offset", "limit"),
        preconditions=("project loaded", "survey.toml exists", "base case exists"),
        risk_level="low",
        cost_class="low",
        cli_commands=(("runs", "sweep"),),
        mcp_tools=("runops.survey.plan",),
    ),
    "relabel_run": ActionSpec(
        name="relabel_run",
        description="Add a semantic directory label without changing the run ID.",
        required_params=("run_dir",),
        preconditions=(
            "run state not in {submitted, running}",
            "run display_name is non-empty",
            "destination path does not exist",
        ),
        risk_level="medium",
        cost_class="low",
        requires_confirmation=True,
        confirmation_reason=(
            "Relabeling moves the run directory and updates path metadata."
        ),
        cli_commands=(("runs", "relabel"),),
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
            "accept_incomplete_reason",
            "force",
        ),
        preconditions=(
            "target exists",
            "target is a run or contains runs",
            "accepted incomplete evidence requires an inline provenance reason",
        ),
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
    "archive_bundle": ActionSpec(
        name="archive_bundle",
        description=(
            "Move a directory containing terminal/inactive runs as one bundle "
            "without changing individual run states."
        ),
        required_params=("bundle_dir",),
        optional_params=("archive_root", "adopt_archived"),
        preconditions=(
            "bundle contains at least one run",
            "bundle contains no submitted or running runs",
            (
                "archive destination does not exist, or --adopt-archived "
                "validates only matching archived/purged runs"
            ),
        ),
        destructive=True,
        risk_level="high",
        cost_class="low",
        requires_confirmation=True,
        confirmation_reason=(
            "Bundle archival moves a parent directory and all contents."
        ),
        cli_commands=(("runs", "archive"),),
    ),
    "restore_run": ActionSpec(
        name="restore_run",
        description="Restore an archived run without deleting its contents.",
        required_params=("run_dir",),
        preconditions=("run state == archived", "restore path does not exist"),
        state_change="archived -> completed",
        risk_level="medium",
        cost_class="low",
        cli_commands=(("runs", "restore"),),
    ),
    "restore_bundle": ActionSpec(
        name="restore_bundle",
        description=(
            "Restore an archived bundle without changing individual run states."
        ),
        required_params=("bundle_dir",),
        preconditions=(
            "bundle archive metadata exists",
            "restore destination does not exist",
        ),
        risk_level="medium",
        cost_class="low",
        cli_commands=(("runs", "restore"),),
    ),
    "purge_work": ActionSpec(
        name="purge_work",
        description="Delete purgeable work/ artifacts from an archived run.",
        required_params=("run_dir",),
        optional_params=("discard_incomplete", "review_reason"),
        preconditions=(
            "run state == archived",
            "known incomplete readiness requires an inline review reason",
        ),
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
