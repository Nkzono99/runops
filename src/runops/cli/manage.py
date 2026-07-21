"""CLI commands for run lifecycle management: archive, purge, cancel, delete."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer

from runops.application.actions import (
    ActionStatus,
    default_archive_destination,
)
from runops.application.actions import archive_bundle as archive_bundle_action
from runops.application.actions import archive_run as archive_run_action
from runops.application.actions import cancel_run as cancel_run_action
from runops.application.actions import delete_run as delete_run_action
from runops.application.actions import plan_bundle_archive as plan_bundle_archive_action
from runops.application.actions import purge_work as purge_work_action
from runops.application.actions import restore_bundle as restore_bundle_action
from runops.application.actions import restore_run as restore_run_action
from runops.cli.run_lookup import resolve_run_or_cwd, resolve_run_targets
from runops.core.exceptions import SimctlError
from runops.core.manifest import read_manifest
from runops.core.state import RunState


def _get_dir_size(dir_path: Path) -> int:
    """Calculate total size of files in a directory tree."""
    if not dir_path.is_dir():
        return 0
    total = 0
    for f in dir_path.rglob("*"):
        if f.is_file():
            total += f.stat().st_size
    return total


def _format_size(size_bytes: int) -> str:
    """Format a byte count as a human-readable string."""
    value = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} PB"


def archive(
    runs: Annotated[
        Optional[list[str]],
        typer.Argument(
            help=(
                "Run identifiers or directories. Each item may be a run_id, "
                "a run directory, or a directory containing runs. Defaults to cwd."
            )
        ),
    ] = None,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip confirmation prompt."),
    ] = False,
    all_runs: Annotated[
        bool,
        typer.Option(
            "--all",
            help="Archive completed runs discovered under the target directory.",
        ),
    ] = False,
    keep_in_place: Annotated[
        bool,
        typer.Option(
            "--keep-in-place",
            "--no-move",
            help="Only change lifecycle state; do not move the run directory.",
        ),
    ] = False,
    move_to: Annotated[
        Optional[Path],
        typer.Option(
            "--move-to",
            help="Archive root to use instead of the default runs/_archive.",
        ),
    ] = None,
    bundle: Annotated[
        bool,
        typer.Option(
            "--bundle",
            help=(
                "Move one parent directory and all contained runs as a bundle "
                "without changing individual run states."
            ),
        ),
    ] = False,
    adopt_archived: Annotated[
        bool,
        typer.Option(
            "--adopt-archived",
            help=(
                "With --bundle, adopt matching archived/purged runs already "
                "at the bundle destination."
            ),
        ),
    ] = False,
) -> None:
    """Archive completed runs and move them under ``runs/_archive`` by default."""
    if bundle:
        _archive_bundle(
            runs,
            yes=yes,
            all_runs=all_runs,
            keep_in_place=keep_in_place,
            move_to=move_to,
            adopt_archived=adopt_archived,
        )
        return

    if adopt_archived:
        typer.echo("Error: --adopt-archived requires --bundle.", err=True)
        raise typer.Exit(code=1)

    if keep_in_place and move_to is not None:
        typer.echo("Error: --move-to cannot be used with --keep-in-place.", err=True)
        raise typer.Exit(code=1)

    targets = _resolve_archive_targets(runs, all_runs=all_runs)
    archive_root = move_to.expanduser().resolve() if move_to is not None else None

    plans: list[tuple[Path, str, Path | None]] = []
    skipped: list[tuple[str, str]] = []
    for run_dir in targets:
        try:
            manifest = read_manifest(run_dir)
        except SimctlError as e:
            skipped.append((run_dir.name, f"error reading manifest: {e}"))
            continue

        run_id = str(manifest.run.get("id", run_dir.name))
        current_status = str(manifest.run.get("status", ""))
        if current_status != RunState.COMPLETED.value:
            skipped.append((run_id, f"state is '{current_status}'"))
            continue

        destination = (
            None
            if keep_in_place
            else default_archive_destination(run_dir, archive_root=archive_root)
        )
        plans.append((run_dir, run_id, destination))

    if len(targets) == 1 and not plans and skipped:
        _, reason = skipped[0]
        if reason.startswith("state is"):
            state = reason.split("'")[1] if "'" in reason else "?"
            typer.echo(
                f"Error: can only archive 'completed' runs, but run is '{state}'.",
                err=True,
            )
        else:
            typer.echo(f"Error: cannot archive {targets[0]}: {reason}", err=True)
        raise typer.Exit(code=1)

    if not plans:
        typer.echo("No completed runs found.")
        for run_id, reason in skipped:
            typer.echo(f"  {run_id}: {reason}")
        return

    if not yes and not _confirm_archive(plans, keep_in_place=keep_in_place):
        typer.echo("Cancelled.")
        raise typer.Exit()

    failures = 0
    moved_any = False
    for run_dir, run_id, destination in plans:
        result = archive_run_action(run_dir, move_to=destination)
        if result.status is not ActionStatus.SUCCESS:
            typer.echo(f"{run_id}: error — {result.message}", err=True)
            failures += 1
            continue

        moved = bool(result.data.get("moved"))
        moved_any = moved_any or moved
        source_path = str(result.data.get("source_path", run_dir))
        archive_path = str(result.data.get("archive_path", run_dir))
        typer.echo(f"Archived run {run_id}.")
        if moved:
            typer.echo(f"  Moved: {source_path} -> {archive_path}")
        else:
            typer.echo(f"  Path: {archive_path}")

    if skipped:
        typer.echo(f"\nSkipped {len(skipped)} run(s):")
        for run_id, reason in skipped:
            typer.echo(f"  {run_id}: {reason}")

    if moved_any:
        typer.echo(
            "\nNote: existing notes, reports, and scripts may still reference "
            "the old run path."
        )

    if failures:
        raise typer.Exit(code=1)


def _resolve_archive_targets(
    args: list[str] | None,
    *,
    all_runs: bool,
) -> list[Path]:
    """Resolve archive arguments while keeping no-arg archive conservative."""
    cwd = Path.cwd()
    if args or all_runs:
        return resolve_run_targets(args, search_dir=cwd)
    return [resolve_run_or_cwd(None, search_dir=cwd)]


def _confirm_archive(
    plans: list[tuple[Path, str, Path | None]],
    *,
    keep_in_place: bool,
) -> bool:
    if len(plans) == 1:
        _, run_id, destination = plans[0]
        if keep_in_place or destination is None:
            prompt = f"Archive run {run_id}? This changes the lifecycle state."
        else:
            prompt = f"Archive run {run_id} and move it to {destination}?"
        return typer.confirm(prompt, default=False)

    preview = ", ".join(run_id for _, run_id, _ in plans[:5])
    if len(plans) > 5:
        preview += f", ... (+{len(plans) - 5} more)"
    if keep_in_place:
        prompt = f"Archive {len(plans)} completed runs in place? [{preview}]"
    else:
        prompt = f"Archive and move {len(plans)} completed runs? [{preview}]"
    return typer.confirm(prompt, default=False)


def _archive_bundle(
    args: list[str] | None,
    *,
    yes: bool,
    all_runs: bool,
    keep_in_place: bool,
    move_to: Path | None,
    adopt_archived: bool,
) -> None:
    if keep_in_place:
        typer.echo("Error: --bundle cannot be used with --keep-in-place.", err=True)
        raise typer.Exit(code=1)
    if all_runs:
        typer.echo("Error: --bundle cannot be used with --all.", err=True)
        raise typer.Exit(code=1)
    source = _resolve_bundle_path(args)
    archive_root = move_to.expanduser().resolve() if move_to is not None else None
    plan = plan_bundle_archive_action(
        source,
        archive_root=archive_root,
        adopt_archived=adopt_archived,
    )
    if plan.status is not ActionStatus.SUCCESS:
        typer.echo(f"Error: {plan.message}", err=True)
        raise typer.Exit(code=1) from None
    destination = Path(str(plan.data["archive_path"]))
    adopted_runs = plan.data.get("adopted_runs", [])
    if isinstance(adopted_runs, list) and adopted_runs:
        typer.echo("Previously archived runs to adopt:")
        for adopted in adopted_runs:
            if isinstance(adopted, dict):
                typer.echo(
                    f"  {adopted.get('run_id', '?')} ({adopted.get('status', '?')})"
                )

    if not yes and not typer.confirm(
        f"Archive bundle {source.name} and move it to {destination}?",
        default=False,
    ):
        typer.echo("Cancelled.")
        raise typer.Exit()

    result = archive_bundle_action(
        source,
        archive_root=archive_root,
        adopt_archived=adopt_archived,
    )
    if result.status is not ActionStatus.SUCCESS:
        typer.echo(f"Error: {result.message}", err=True)
        raise typer.Exit(code=1)

    run_count = int(result.data.get("run_count", 0))
    noun = "run" if run_count == 1 else "runs"
    bundle_name = str(result.data.get("bundle_name", source.name))
    source_path = str(result.data.get("source_path", source))
    archive_path = str(result.data.get("archive_path", destination))
    typer.echo(f"Archived bundle {bundle_name} ({run_count} {noun}).")
    typer.echo(f"  Moved: {source_path} -> {archive_path}")
    adopted_count = int(result.data.get("adopted_run_count", 0))
    if adopted_count:
        adopted_noun = "run" if adopted_count == 1 else "runs"
        typer.echo(f"Adopted {adopted_count} previously archived {adopted_noun}.")
    typer.echo("  Run states were preserved; work/status/cache remain ignored by Git.")


def _resolve_bundle_path(args: list[str] | None) -> Path:
    if args and len(args) > 1:
        typer.echo("Error: --bundle accepts exactly one directory.", err=True)
        raise typer.Exit(code=1)
    raw = args[0] if args else "."
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    resolved = candidate.resolve()
    if not resolved.is_dir():
        typer.echo(f"Error: bundle directory not found: {resolved}", err=True)
        raise typer.Exit(code=1)
    return resolved


def restore(
    run: str = typer.Argument(..., help="Archived run directory or run_id."),
    bundle: Annotated[
        bool,
        typer.Option(
            "--bundle",
            help="Restore a parent directory archived with runs archive --bundle.",
        ),
    ] = False,
) -> None:
    """Restore an archived run to its pre-archive location."""
    if bundle:
        bundle_dir = _resolve_bundle_path([run])
        result = restore_bundle_action(bundle_dir)
        if result.status is not ActionStatus.SUCCESS:
            typer.echo(f"Error: {result.message}", err=True)
            raise typer.Exit(code=1)

        run_count = int(result.data.get("run_count", 0))
        noun = "run" if run_count == 1 else "runs"
        bundle_name = str(result.data.get("bundle_name", bundle_dir.name))
        source_path = str(result.data.get("source_path", bundle_dir))
        restore_path = str(result.data.get("restore_path", bundle_dir))
        typer.echo(f"Restored bundle {bundle_name} ({run_count} {noun}).")
        typer.echo(f"  Moved: {source_path} -> {restore_path}")
        return

    run_dir = resolve_run_or_cwd(run, search_dir=Path.cwd())
    result = restore_run_action(run_dir)
    if result.status is not ActionStatus.SUCCESS:
        typer.echo(f"Error: {result.message}", err=True)
        raise typer.Exit(code=1)

    run_id = str(result.data.get("run_id", run_dir.name))
    restored_path = str(result.data.get("restore_path", run_dir))
    typer.echo(f"Restored run {run_id}.")
    if bool(result.data.get("moved")):
        source_path = str(result.data.get("source_path", run_dir))
        typer.echo(f"  Moved: {source_path} -> {restored_path}")
    else:
        typer.echo(f"  Path: {restored_path}")


def purge_work(
    run: str = typer.Argument(None, help="Run directory or run_id (defaults to cwd)."),
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation prompt."),
    discard_incomplete: bool = typer.Option(
        False,
        "--discard-incomplete",
        help="Allow deletion when cached readiness is incomplete or unknown.",
    ),
    reason: str = typer.Option(
        "",
        "--reason",
        help="Required review reason when --discard-incomplete is used.",
    ),
) -> None:
    """Remove unnecessary files from a run's work/ directory."""
    run_dir = resolve_run_or_cwd(run, search_dir=Path.cwd())

    try:
        manifest = read_manifest(run_dir)
    except SimctlError as e:
        typer.echo(f"Error reading manifest: {e}", err=True)
        raise typer.Exit(code=1) from None

    current_status = manifest.run.get("status", "")
    if current_status != RunState.ARCHIVED.value:
        typer.echo(
            f"Error: can only purge 'archived' runs, but run is '{current_status}'.",
            err=True,
        )
        raise typer.Exit(code=1)

    # Calculate size of directories to remove
    work_dir = run_dir / "work"
    targets = ["outputs", "restart", "tmp"]
    total_freed = 0

    for dirname in targets:
        target_dir = work_dir / dirname
        if target_dir.is_dir():
            total_freed += _get_dir_size(target_dir)

    run_id = manifest.run.get("id", "???")
    if not yes and not typer.confirm(
        "Purge work files for "
        f"{run_id}? This will remove outputs/restart/tmp "
        f"(about {_format_size(total_freed)}).",
        default=False,
    ):
        typer.echo("Cancelled.")
        raise typer.Exit()

    result = purge_work_action(
        run_dir,
        discard_incomplete=discard_incomplete,
        review_reason=reason,
    )
    if result.status is not ActionStatus.SUCCESS:
        typer.echo(f"Error: {result.message}", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"Purged work files for run {run_id}.")
    typer.echo(f"  Freed: {_format_size(total_freed)}")
    typer.echo(f"  Path: {run_dir}")


def cancel(
    runs: Annotated[
        Optional[list[str]],
        typer.Argument(
            help=(
                "Run identifiers or directories. Each item may be a run_id, "
                "a run directory, or a directory containing runs (recursive). "
                "Defaults to cwd."
            )
        ),
    ] = None,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip confirmation prompt."),
    ] = False,
) -> None:
    """Cancel active Slurm jobs (scancel) and sync run states.

    Combines ``scancel <job_id>`` and ``runo runs sync`` so each manifest is
    updated automatically.  Use this instead of bare ``scancel`` so run states
    end up consistent.

    Multiple targets and recursive survey directories are supported — any
    non-cancellable run (not submitted/running, or missing job_id) is reported
    and skipped in bulk mode.
    """
    targets = resolve_run_targets(runs, search_dir=Path.cwd())

    # Collect cancellable runs first so we can show a single confirmation.
    cancellable: list[tuple[Path, str, str]] = []  # (run_dir, run_id, job_id)
    skipped: list[tuple[str, str]] = []  # (run_id, reason)

    for run_dir in targets:
        try:
            manifest = read_manifest(run_dir)
        except SimctlError as e:
            skipped.append((run_dir.name, f"error reading manifest: {e}"))
            continue

        run_id = str(manifest.run.get("id", run_dir.name))
        current_status = str(manifest.run.get("status", ""))
        job_id = str(manifest.job.get("job_id", ""))

        if current_status not in {
            RunState.SUBMITTED.value,
            RunState.RUNNING.value,
        }:
            skipped.append((run_id, f"state is '{current_status}'"))
            continue
        if not job_id:
            skipped.append((run_id, "no job_id recorded"))
            continue

        cancellable.append((run_dir, run_id, job_id))

    # Single-target strict mode: surface explicit errors in the legacy format.
    if len(targets) == 1 and not cancellable and skipped:
        run_id, reason = skipped[0]
        if reason.startswith("state is"):
            state = reason.split("'")[1] if "'" in reason else "?"
            typer.echo(
                f"Error: can only cancel submitted/running runs, but run is '{state}'.",
                err=True,
            )
        elif "no job_id" in reason:
            typer.echo("Error: no job_id recorded in manifest.", err=True)
        else:
            typer.echo(f"Error: cannot cancel {run_id}: {reason}", err=True)
        raise typer.Exit(code=1)

    if not cancellable:
        typer.echo("No cancellable runs found.")
        for run_id, reason in skipped:
            typer.echo(f"  {run_id}: {reason}")
        return

    if not yes:
        if len(cancellable) == 1:
            _, run_id, job_id = cancellable[0]
            prompt = f"Cancel run {run_id} (Slurm job {job_id})?"
        else:
            ids = ", ".join(r[1] for r in cancellable[:5])
            if len(cancellable) > 5:
                ids += f", ... (+{len(cancellable) - 5} more)"
            prompt = f"Cancel {len(cancellable)} runs? [{ids}]"
        if not typer.confirm(prompt, default=False):
            typer.echo("Cancelled.")
            raise typer.Exit()

    failures = 0
    for run_dir, run_id, _ in cancellable:
        result = cancel_run_action(run_dir)
        if result.status is not ActionStatus.SUCCESS:
            typer.echo(f"{run_id}: error — {result.message}", err=True)
            failures += 1
            continue
        typer.echo(f"{run_id}: {result.message}")
        if result.state_after and result.state_before != result.state_after:
            typer.echo(f"  State: {result.state_before} -> {result.state_after}")

    if skipped:
        typer.echo(f"\nSkipped {len(skipped)} run(s):")
        for run_id, reason in skipped:
            typer.echo(f"  {run_id}: {reason}")

    if failures:
        raise typer.Exit(code=1)


def delete(
    run: str = typer.Argument(None, help="Run directory or run_id (defaults to cwd)."),
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation prompt."),
) -> None:
    """Hard-delete a run directory.

    Only allowed for terminal non-completed states (created, cancelled,
    failed) so existing results (completed/archived) are never lost.
    Removes the entire run directory irreversibly.
    """
    run_dir = resolve_run_or_cwd(run, search_dir=Path.cwd())

    try:
        manifest = read_manifest(run_dir)
    except SimctlError as e:
        typer.echo(f"Error reading manifest: {e}", err=True)
        raise typer.Exit(code=1) from None

    current_status = manifest.run.get("status", "")
    deletable = {
        RunState.CREATED.value,
        RunState.CANCELLED.value,
        RunState.FAILED.value,
    }
    if current_status not in deletable:
        typer.echo(
            "Error: can only delete created/cancelled/failed runs, "
            f"but run is '{current_status}'. "
            "Use `runo runs archive` (then purge-work) for completed runs.",
            err=True,
        )
        raise typer.Exit(code=1)

    run_id = manifest.run.get("id", "???")
    dir_size = _get_dir_size(run_dir)

    if not yes and not typer.confirm(
        f"Delete run {run_id} ({_format_size(dir_size)})? "
        "This removes the directory irreversibly.",
        default=False,
    ):
        typer.echo("Cancelled.")
        raise typer.Exit()

    result = delete_run_action(run_dir)
    if result.status is not ActionStatus.SUCCESS:
        typer.echo(f"Error: {result.message}", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"Deleted run {run_id}.")
    typer.echo(f"  Freed: {_format_size(dir_size)}")
    typer.echo(f"  Path: {run_dir}")
