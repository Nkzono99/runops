"""CLI commands for status checking and scheduler state synchronization."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer

from runops.cli.run_lookup import resolve_run_targets
from runops.core.actions import ActionStatus
from runops.core.actions import sync_run as sync_run_action
from runops.core.exceptions import (
    ManifestNotFoundError,
)
from runops.core.manifest import ManifestData, read_manifest
from runops.core.readiness import RunReadiness, evaluate_run_readiness
from runops.core.state import RunState
from runops.slurm.query import SlurmQueryError, query_job_status
from runops.slurm.submit import SlurmNotFoundError


def status(
    runs: Annotated[
        Optional[list[str]],
        typer.Argument(
            help=(
                "Run identifiers or directories.  Each item may be a run_id, "
                "a run directory, or a directory containing runs (recursive). "
                "Defaults to cwd."
            )
        ),
    ] = None,
    short: Annotated[
        bool,
        typer.Option(
            "--short",
            "-s",
            help=(
                "Compact one-line-per-run output: "
                "run_id  state  origin_case  display_name."
            ),
        ),
    ] = False,
    summary: Annotated[
        bool,
        typer.Option(
            "--summary",
            help="Aggregate by origin.case x state; no per-run lines.",
        ),
    ] = False,
) -> None:
    """Show the current status of one or more runs.

    Displays the run state from manifest.toml. If a scheduler job_id is
    recorded, also queries the scheduler for the live job state. Does NOT
    update the manifest (use ``runo runs sync`` for that).

    Multi-target form: pass a survey directory (e.g. ``runs/series_A``)
    or several run_ids; status is printed for each.

    Use ``--short`` for a compact 1-line-per-run view, or ``--summary``
    for a per-case aggregate. These modes skip the (slower) live scheduler
    query and rely on manifest state only.
    """
    if short and summary:
        typer.echo("Error: --short and --summary are mutually exclusive.", err=True)
        raise typer.Exit(code=2)

    targets = resolve_run_targets(runs, search_dir=Path.cwd())

    if summary:
        _print_status_summary(targets)
        return

    if short:
        _print_status_short(targets)
        return

    multi = len(targets) > 1
    for index, run_dir in enumerate(targets):
        if multi and index > 0:
            typer.echo("")
        _print_status_one(run_dir)


def _print_status_short(targets: list[Path]) -> None:
    """One line per run: run_id  state  case  display_name."""
    rows: list[tuple[str, str, str, str]] = []
    for run_dir in targets:
        try:
            manifest = read_manifest(run_dir)
        except ManifestNotFoundError:
            rows.append((run_dir.name, "unknown", "", "(no manifest)"))
            continue
        run_id = str(manifest.run.get("id", run_dir.name))
        state = str(manifest.run.get("status", "unknown"))
        case = str(manifest.origin.get("case", ""))
        display_name = str(manifest.run.get("display_name", ""))
        rows.append((run_id, state, case, display_name))

    widths = [0, 0, 0]
    for row in rows:
        for i in range(3):
            widths[i] = max(widths[i], len(row[i]))
    for run_id, state, case, name in rows:
        typer.echo(
            f"{run_id:<{widths[0]}}  {state:<{widths[1]}}  "
            f"{case:<{widths[2]}}  {name}".rstrip()
        )


def _print_status_summary(targets: list[Path]) -> None:
    """Aggregate by origin.case x state."""
    from collections import Counter, defaultdict

    by_case: dict[str, Counter[str]] = defaultdict(Counter)
    total = 0
    for run_dir in targets:
        try:
            manifest = read_manifest(run_dir)
        except ManifestNotFoundError:
            by_case["(no manifest)"]["unknown"] += 1
            total += 1
            continue
        case = str(manifest.origin.get("case", "")) or "(none)"
        state = str(manifest.run.get("status", "unknown"))
        by_case[case][state] += 1
        total += 1

    if not by_case:
        typer.echo("No runs found.")
        return

    state_order = [
        "completed",
        "running",
        "submitted",
        "created",
        "failed",
        "cancelled",
        "archived",
        "purged",
    ]

    case_width = max(len(case) for case in by_case)
    for case in sorted(by_case):
        counts = by_case[case]
        ordered = [(s, counts[s]) for s in state_order if counts.get(s)]
        # Append any unknown states we didn't list
        for s, c in sorted(counts.items()):
            if s not in state_order and c:
                ordered.append((s, c))
        parts = "  ".join(f"{s}={c}" for s, c in ordered)
        typer.echo(f"{case:<{case_width}}  {parts}")
    typer.echo(f"\n{total} run(s) across {len(by_case)} case(s)")


def _print_status_one(run_dir: Path) -> None:
    try:
        manifest = read_manifest(run_dir)
    except ManifestNotFoundError as e:
        typer.echo(f"Error: {e}")
        raise typer.Exit(code=1) from None

    run_id = manifest.run.get("id", run_dir.name)
    current_status = manifest.run.get("status", "unknown")
    job_id = manifest.job.get("job_id", "")
    scheduler = str(manifest.job.get("scheduler", "slurm")).lower()

    typer.echo(f"Run:    {run_id}")
    typer.echo(f"Path:   {run_dir}")
    typer.echo(f"State:  {current_status}")
    readiness = _readiness_for_display(run_dir, manifest)
    if readiness is not None:
        typer.echo(f"Analysis: {readiness.analysis_status}")
        if readiness.missing_required_artifacts:
            typer.echo(
                "Missing artifacts: " + ", ".join(readiness.missing_required_artifacts)
            )
        for warning in readiness.warnings:
            typer.echo(f"Readiness warning: {warning}")
    retry_status = str(manifest.run.get("retry_status", "")).strip()
    if retry_status:
        typer.echo(f"Retry:  {retry_status}")
        partial_outputs = manifest.run.get("partial_outputs", {})
        if isinstance(partial_outputs, dict) and partial_outputs:
            parts = [f"{key}={value}" for key, value in sorted(partial_outputs.items())]
            typer.echo(f"Partial outputs: {', '.join(parts)}")

    # Show failure reason if recorded
    failure_reason = manifest.run.get("failure_reason", "")
    if failure_reason:
        typer.echo(f"Reason: {failure_reason}")

    if job_id:
        typer.echo(f"Job ID: {job_id}")
        _print_live_job_status(str(job_id), scheduler)
    else:
        typer.echo("Job ID: (not submitted)")


def _print_live_job_status(job_id: str, scheduler: str) -> None:
    """Print best-effort live scheduler status for a recorded job."""
    if scheduler == "slurm":
        try:
            slurm_status = query_job_status(job_id)
            typer.echo(f"Slurm:  {slurm_status.slurm_state}")
            if slurm_status.failure_reason:
                typer.echo(f"Slurm reason: {slurm_status.failure_reason}")
        except SlurmNotFoundError:
            typer.echo("Slurm:  (Slurm commands not available)")
        except SlurmQueryError as e:
            typer.echo(f"Slurm:  (query failed: {e})")
        return

    if scheduler == "pbs":
        from runops.pbs import query as pbs_query
        from runops.pbs.submit import PbsNotFoundError

        try:
            pbs_status = pbs_query.query_job_status(job_id)
            typer.echo(f"PBS:    {pbs_status.pbs_state}")
            if pbs_status.failure_reason:
                typer.echo(f"PBS reason: {pbs_status.failure_reason}")
        except PbsNotFoundError:
            typer.echo("PBS:    (PBS commands not available)")
        except pbs_query.PbsQueryError as e:
            typer.echo(f"PBS:    (query failed: {e})")
        return

    typer.echo(f"Scheduler: (unsupported scheduler: {scheduler})")


def _readiness_for_display(
    run_dir: Path,
    manifest: ManifestData,
) -> RunReadiness | None:
    """Return readiness details for completed runs."""
    if manifest.run.get("status") != RunState.COMPLETED.value:
        return None
    return evaluate_run_readiness(run_dir, manifest=manifest)


def sync(
    runs: Annotated[
        Optional[list[str]],
        typer.Argument(
            help=(
                "Run identifiers or directories.  Each item may be a run_id, "
                "a run directory, or a directory containing runs (recursive). "
                "Defaults to cwd."
            )
        ),
    ] = None,
) -> None:
    """Synchronize scheduler job state into one or more run manifests.

    Queries the configured scheduler for each target and updates
    both manifest.toml and status/state.json if the state has changed.

    When passed a survey directory (e.g. ``runo runs sync runs/series_A``)
    every run found underneath is sync'd.  In bulk / multi-target mode the
    following runs are skipped silently so the command remains useful on
    mixed-state surveys:

    - runs without a recorded ``job_id`` (typical for ``created`` runs that
      haven't been submitted yet);
    - runs already in a terminal state (``completed``, ``failed``,
      ``cancelled``, ``archived``, ``purged``) — those have nothing left to
      sync.

    In single-target mode the user is explicitly asking about a specific
    run, so the precondition errors are surfaced instead of swallowed.
    """
    targets = resolve_run_targets(runs, search_dir=Path.cwd())
    multi = len(targets) > 1

    # Terminal states that no longer need (or accept) scheduler reconciliation.
    terminal_states = {
        RunState.COMPLETED.value,
        RunState.FAILED.value,
        RunState.CANCELLED.value,
        RunState.ARCHIVED.value,
        RunState.PURGED.value,
    }

    from collections import Counter

    failures = 0
    state_counts: Counter[str] = Counter()
    changed = 0
    total = 0

    for run_dir in targets:
        try:
            manifest = read_manifest(run_dir)
        except ManifestNotFoundError as e:
            typer.echo(f"Error: {e}", err=True)
            failures += 1
            continue

        total += 1

        # In multi-target / bulk mode, runs without a job_id are skipped
        # silently — they typically belong to ``created`` runs that haven't
        # been submitted yet.
        if not manifest.job.get("job_id", ""):
            if multi:
                state = str(manifest.run.get("status", "created"))
                state_counts[state] += 1
                continue
            run_id_str = manifest.run.get("id", run_dir.name)
            typer.echo(
                f"Error: {run_id_str}: no job_id recorded in manifest "
                "(was the run submitted?)",
                err=True,
            )
            raise typer.Exit(code=1)

        # Same idea for runs already in a terminal state — there is nothing
        # for sync_run() to do, and the underlying action raises a
        # precondition_failed for completed/failed/cancelled.  Skip silently
        # in bulk mode so the rest of the survey still gets processed.
        current_state = str(manifest.run.get("status", ""))
        if current_state in terminal_states:
            state_counts[current_state] += 1
            if multi:
                continue
            run_id_str = manifest.run.get("id", run_dir.name)
            typer.echo(
                f"{run_id_str}: state already terminal ({current_state}) — "
                "nothing to sync"
            )
            continue

        result = sync_run_action(run_dir)
        run_id = str(result.data.get("run_id", run_dir.name))
        if result.status is not ActionStatus.SUCCESS:
            typer.echo(f"{run_id}: error — {result.message}", err=True)
            failures += 1
            continue

        after = str(result.state_after or current_state)
        state_counts[after] += 1

        if result.state_before == result.state_after:
            typer.echo(f"{run_id}: state unchanged ({result.state_after})")
        else:
            changed += 1
            msg = f"{run_id}: {result.state_before} -> {result.state_after}"
            failure_reason = str(result.data.get("failure_reason", ""))
            if failure_reason:
                msg += f" (reason: {failure_reason})"
            typer.echo(msg)

    # Print summary when multiple targets are involved
    if multi and total > 0:
        parts = []
        for state in (
            "completed",
            "running",
            "submitted",
            "created",
            "failed",
            "cancelled",
            "archived",
            "purged",
        ):
            count = state_counts.get(state, 0)
            if count:
                parts.append(f"{count} {state}")
        summary_line = ", ".join(parts)
        typer.echo(f"\nSummary: {summary_line}  ({total} total)")
        typer.echo(f"         {changed} state(s) changed in this sync")

    if failures:
        raise typer.Exit(code=1)
