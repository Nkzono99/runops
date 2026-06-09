"""CLI commands for run lifecycle management: archive, purge, cancel, delete."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer

from runops.cli.run_lookup import resolve_run_or_cwd, resolve_run_targets
from runops.core.actions import ActionStatus, default_archive_destination
from runops.core.actions import archive_run as archive_run_action
from runops.core.actions import cancel_run as cancel_run_action
from runops.core.actions import delete_run as delete_run_action
from runops.core.actions import purge_work as purge_work_action
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
) -> None:
    """Archive completed runs and move them under ``runs/_archive`` by default."""
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


def purge_work(
    run: str = typer.Argument(None, help="Run directory or run_id (defaults to cwd)."),
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation prompt."),
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

    result = purge_work_action(run_dir)
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
    """Cancel active scheduler jobs and sync run states.

    Combines scheduler cancellation and ``runo runs sync`` so each manifest is
    updated automatically.  Use this instead of bare scheduler commands so run
    states end up consistent.

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
            prompt = f"Cancel run {run_id} (job {job_id})?"
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
