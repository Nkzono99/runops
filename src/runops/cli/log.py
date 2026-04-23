"""CLI command for viewing job output logs and progress."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Any, Optional

import typer

from runops.cli.run_lookup import resolve_run_or_cwd
from runops.core.exceptions import SimctlError
from runops.core.manifest import read_manifest


def _find_latest_log(work_dir: Path, pattern: str) -> Path | None:
    """Find the most recently modified log file matching a glob pattern."""
    if not work_dir.is_dir():
        return None
    candidates = sorted(
        work_dir.glob(pattern),
        key=lambda p: p.stat().st_mtime if p.exists() else 0,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _tail_file(path: Path, lines: int) -> list[str]:
    """Read the last N lines of a file efficiently."""
    try:
        with open(path, "rb") as f:
            # Seek from end
            f.seek(0, os.SEEK_END)
            size = f.tell()
            # Read enough to get N lines (estimate 200 bytes/line)
            read_size = min(size, lines * 200)
            f.seek(max(0, size - read_size))
            data = f.read().decode("utf-8", errors="replace")
        all_lines = data.splitlines()
        return all_lines[-lines:]
    except OSError:
        return []


def _get_progress(run_dir: Path, manifest_data: dict[str, Any]) -> str | None:
    """Try to get progress info from the adapter."""
    adapter_name = manifest_data.get("simulator", {}).get("adapter", "")
    if not adapter_name:
        adapter_name = manifest_data.get("simulator", {}).get("name", "")
    if not adapter_name:
        return None

    try:
        import runops.adapters  # noqa: F401
        from runops.adapters.registry import get as get_adapter

        adapter_cls = get_adapter(adapter_name)
        adapter = adapter_cls()
        summary = adapter.summarize(run_dir)
        # Build progress string from summary
        last_step = summary.get("last_step")
        nstep = summary.get("nstep")
        status = summary.get("status", "")
        if last_step is not None and nstep:
            pct = last_step / nstep * 100
            return f"Progress: {last_step}/{nstep} ({pct:.1f}%) [{status}]"
        elif status:
            return f"Status: {status}"
    except Exception:
        pass
    return None


def log(
    run: Annotated[
        Optional[str],
        typer.Argument(help="Run directory or run_id (defaults to cwd)."),
    ] = None,
    lines: Annotated[
        int,
        typer.Option("-n", "--lines", help="Number of lines to show."),
    ] = 20,
    stderr: Annotated[
        bool,
        typer.Option("-e", "--stderr", help="Show stderr instead of stdout."),
    ] = False,
    follow: Annotated[
        bool,
        typer.Option("-f", "--follow", help="Follow log output (like tail -f)."),
    ] = False,
) -> None:
    """Show latest job output log with progress.

    Examples:
      runo runs log              # stdout of cwd run
      runo runs log -e           # stderr
      runo runs log -n 50        # last 50 lines
    """
    run_dir = resolve_run_or_cwd(run, search_dir=Path.cwd())
    work_dir = run_dir / "work"

    # Read manifest for job info and progress
    try:
        manifest = read_manifest(run_dir)
    except SimctlError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from None

    run_id = manifest.run.get("id", run_dir.name)
    job_id = manifest.job.get("job_id", "")

    # Find log file
    if stderr:
        patterns = [f"stderr.{job_id}.log", f"*.{job_id}.err", "*.err"]
    else:
        patterns = [f"stdout.{job_id}.log", f"*.{job_id}.out", "*.out"]

    log_file = None
    for pat in patterns:
        log_file = _find_latest_log(work_dir, pat)
        if log_file:
            break

    if log_file is None:
        # Fallback: any log-like file
        fallback_pat = "stderr*" if stderr else "stdout*"
        log_file = _find_latest_log(work_dir, fallback_pat)

    if log_file is None:
        stream = "stderr" if stderr else "stdout"
        typer.echo(f"No {stream} log found for {run_id}")
        if job_id:
            typer.echo(f"  (job_id: {job_id})")
        raise typer.Exit(code=1)

    # Show progress
    progress = _get_progress(
        run_dir,
        {
            "simulator": dict(manifest.simulator),
        },
    )
    typer.echo(f"Run: {run_id}  Log: {log_file.name}")
    if progress:
        typer.echo(progress)
    typer.echo("---")

    if follow:
        # tail -f mode
        import subprocess
        import sys

        try:
            subprocess.run(
                ["tail", f"-n{lines}", "-f", str(log_file)],
                check=False,
            )
        except KeyboardInterrupt:
            sys.exit(0)
    else:
        tail_lines = _tail_file(log_file, lines)
        for line in tail_lines:
            typer.echo(line)
