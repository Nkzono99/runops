"""Shared helpers for resolving run directories from CLI arguments."""

from __future__ import annotations

from pathlib import Path

import typer

from runops.core.discovery import discover_runs, require_run_directory, resolve_run
from runops.core.exceptions import ProjectNotFoundError, RunNotFoundError, SimctlError
from runops.core.project import find_project_root


def find_project_runs_dir(start: Path | None = None) -> Path:
    """Walk upward from ``start`` to find the project's ``runs/`` directory."""
    try:
        project_root = find_project_root((start or Path.cwd()).resolve())
    except ProjectNotFoundError as exc:
        typer.echo(f"Error: {exc}")
        raise typer.Exit(code=1) from None
    return project_root / "runs"


def resolve_project_run_dir(identifier: str, *, start: Path | None = None) -> Path:
    """Resolve a run identifier relative to the nearest enclosing project."""
    try:
        runs_dir = find_project_runs_dir(start)
        return resolve_run(identifier, runs_dir)
    except RunNotFoundError as e:
        typer.echo(f"Error: {e}")
        raise typer.Exit(code=1) from None


def resolve_run_or_cwd(run: str | None, *, search_dir: Path | None = None) -> Path:
    """Resolve a run argument or fall back to the current run directory."""
    cwd = (search_dir or Path.cwd()).resolve()
    if run is None:
        if (cwd / "manifest.toml").exists():
            try:
                return require_run_directory(cwd)
            except SimctlError as e:
                typer.echo(f"Error: {e}", err=True)
                raise typer.Exit(code=1) from None
        typer.echo("Error: No manifest.toml in cwd. Specify a run.", err=True)
        raise typer.Exit(code=1)

    try:
        return _resolve_run_argument(run, search_dir=cwd)
    except SimctlError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from None


def _resolve_run_argument(identifier: str, *, search_dir: Path) -> Path:
    """Resolve an explicit run argument from any project subdirectory.

    Prefers path-like arguments relative to ``search_dir`` so callers can use
    ``./runs/...`` or absolute paths.  If no manifest is found at that path,
    falls back to project-wide run_id lookup under the nearest enclosing
    project's ``runs/`` directory.
    """
    try:
        candidate = Path(identifier)
    except OSError as e:
        raise RunNotFoundError(f"Invalid run path {identifier!r}: {e}") from None

    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        resolved = (search_dir / candidate).resolve()

    if (resolved / "manifest.toml").exists():
        return require_run_directory(resolved)

    runs_dir = find_project_runs_dir(search_dir)
    return resolve_run(identifier, runs_dir)


def resolve_run_targets(
    args: list[str] | None,
    *,
    search_dir: Path | None = None,
) -> list[Path]:
    """Resolve a list of CLI arguments into a list of run directories.

    Each argument may be:

    - a run identifier (run_id) → resolved to a single run directory;
    - a path to a run directory (containing ``manifest.toml``) → used as-is;
    - a path to a directory that *contains* runs (e.g. a survey directory or
      ``runs/``) → recursively discovered for all run directories underneath.

    If *args* is empty (or ``None``), the search falls back to the current
    working directory:
        - if cwd is itself a run directory, return ``[cwd]``;
        - otherwise discover runs under cwd.

    Args:
        args: List of run identifiers or paths from the CLI.
        search_dir: Override the search root (defaults to ``Path.cwd()``).

    Returns:
        A sorted list of unique run directories (by path).
    """
    cwd = (search_dir or Path.cwd()).resolve()

    # Empty arglist → use cwd as either a run dir or a discovery root.
    if not args:
        if (cwd / "manifest.toml").exists():
            try:
                return [require_run_directory(cwd)]
            except SimctlError as e:
                typer.echo(f"Error: {e}", err=True)
                raise typer.Exit(code=1) from None
        try:
            return _discover_or_error(cwd)
        except typer.Exit:
            typer.echo(
                "Error: cwd is not a run directory and contains no runs. "
                "Specify a run identifier or directory.",
                err=True,
            )
            raise

    seen: dict[Path, None] = {}  # ordered set
    for arg in args:
        candidate = Path(arg)
        # Direct path?
        if candidate.exists():
            resolved = candidate.resolve()
            if (resolved / "manifest.toml").exists():
                try:
                    seen.setdefault(require_run_directory(resolved), None)
                except SimctlError as e:
                    typer.echo(f"Error resolving {arg!r}: {e}", err=True)
                    raise typer.Exit(code=1) from None
                continue
            # Directory containing runs.
            for rd in _discover_or_error(resolved):
                seen.setdefault(rd, None)
            continue

        # Otherwise treat as run_id (looked up under the project's runs/).
        try:
            runs_dir = find_project_runs_dir(cwd)
            seen.setdefault(resolve_run(arg, runs_dir), None)
        except SimctlError as e:
            typer.echo(f"Error resolving {arg!r}: {e}", err=True)
            raise typer.Exit(code=1) from None

    return sorted(seen.keys())


def _discover_or_error(directory: Path) -> list[Path]:
    """Discover runs under a directory, exiting cleanly on error."""
    try:
        return [require_run_directory(path) for path in discover_runs(directory)]
    except SimctlError as e:
        typer.echo(f"Error discovering runs under {directory}: {e}", err=True)
        raise typer.Exit(code=1) from None
