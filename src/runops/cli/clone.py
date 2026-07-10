"""CLI command for cloning and deriving runs."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional

import typer

from runops.application.run_creation import create_case_run
from runops.cli.run_lookup import resolve_run_or_cwd
from runops.core.discovery import collect_existing_run_ids
from runops.core.exceptions import SimctlError
from runops.core.manifest import ManifestData, read_manifest, write_manifest
from runops.core.project import find_project_root, load_project
from runops.core.run import (
    create_run,
    rewrite_job_script_references,
    sanitize_derived_manifest,
)


def clone(
    run: str = typer.Argument(None, help="Run directory or run_id (defaults to cwd)."),
    dest: Optional[Path] = typer.Option(
        None, "--dest", "-d", help="Destination directory (defaults to cwd)."
    ),
    set_params: Optional[list[str]] = typer.Option(
        None, "--set", help="Override parameters as key=value."
    ),
) -> None:
    """Clone a run, optionally modifying parameters."""
    search_dir = Path.cwd()
    source_dir = resolve_run_or_cwd(run, search_dir=search_dir)

    try:
        source_manifest = read_manifest(source_dir)
    except SimctlError as e:
        typer.echo(f"Error reading manifest: {e}", err=True)
        raise typer.Exit(code=1) from None

    dest_parent = dest or source_dir.parent
    dest_parent = dest_parent.resolve()

    try:
        overrides = _parse_set_params(set_params or [])
    except SimctlError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from None

    source_run_id = str(source_manifest.run.get("id", source_dir.name))
    if overrides:
        _clone_with_regenerated_inputs(
            source_dir=source_dir,
            source_manifest=source_manifest,
            source_run_id=source_run_id,
            dest_parent=dest_parent,
            overrides=overrides,
        )
        return

    _clone_by_copy(
        source_dir=source_dir,
        source_manifest=source_manifest,
        source_run_id=source_run_id,
        dest_parent=dest_parent,
    )


def _parse_set_params(set_params: list[str]) -> dict[str, str]:
    """Parse ``--set key=value`` options."""
    overrides: dict[str, str] = {}
    for param in set_params:
        if "=" not in param:
            raise SimctlError(f"invalid --set format {param!r}, expected key=value")
        key, value = param.split("=", 1)
        key = key.strip()
        if not key:
            raise SimctlError(f"invalid --set format {param!r}, key must not be empty")
        overrides[key] = value.strip()
    return overrides


def _clone_with_regenerated_inputs(
    *,
    source_dir: Path,
    source_manifest: ManifestData,
    source_run_id: str,
    dest_parent: Path,
    overrides: dict[str, str],
) -> None:
    """Clone by regenerating inputs from the source case."""
    case_name = str(source_manifest.origin.get("case", "")).strip()
    if not case_name:
        typer.echo(
            "Error: --set requires a source manifest with origin.case so inputs "
            "can be regenerated.",
            err=True,
        )
        raise typer.Exit(code=1)

    try:
        project_root = find_project_root(source_dir)
        project = load_project(project_root)
        params = dict(source_manifest.params_snapshot)
        params.update(overrides)
        result = create_case_run(
            project,
            case_name,
            dest_dir=dest_parent,
            display_name=f"clone of {source_run_id}",
            params=params,
        )
        manifest = read_manifest(result.run_info.run_dir)
        manifest.origin["parent_run"] = source_run_id
        manifest.origin["survey"] = ""
        manifest.variation = {"changed_keys": sorted(overrides)}
        write_manifest(result.run_info.run_dir, manifest)
    except SimctlError as e:
        typer.echo(f"Error creating clone: {e}", err=True)
        raise typer.Exit(code=1) from None

    typer.echo(f"Cloned {source_run_id} -> {result.run_info.run_id}")
    typer.echo(f"  Path: {result.run_info.run_dir}")


def _clone_by_copy(
    *,
    source_dir: Path,
    source_manifest: ManifestData,
    source_run_id: str,
    dest_parent: Path,
) -> None:
    """Clone by copying stable artifacts and sanitizing copied metadata."""
    dest_parent.mkdir(parents=True, exist_ok=True)

    try:
        existing_ids = _collect_existing_ids(source_dir, dest_parent)
        run_info = create_run(
            dest_parent,
            existing_ids,
            display_name=f"clone of {source_run_id}",
            params=dict(source_manifest.params_snapshot),
        )
    except SimctlError as e:
        typer.echo(f"Error generating run_id: {e}", err=True)
        raise typer.Exit(code=1) from None

    new_run_dir = run_info.run_dir

    try:
        source_input = source_dir / "input"
        if source_input.is_dir():
            _replace_tree(source_input, new_run_dir / "input")

        source_submit = source_dir / "submit"
        if source_submit.is_dir():
            _replace_tree(source_submit, new_run_dir / "submit")
            rewrite_job_script_references(
                new_run_dir / "submit" / "job.sh",
                source_dir=source_dir,
                target_dir=new_run_dir,
                source_run_id=source_run_id,
                target_run_id=run_info.run_id,
            )

        new_manifest = sanitize_derived_manifest(
            source_manifest,
            run_info=run_info,
            parent_run_id=source_run_id,
            display_name=f"clone of {source_run_id}",
            params_snapshot=run_info.params,
        )
        write_manifest(new_run_dir, new_manifest)

    except SimctlError as e:
        typer.echo(f"Error creating clone: {e}", err=True)
        raise typer.Exit(code=1) from None
    except OSError as e:
        typer.echo(f"Error creating clone directory: {e}", err=True)
        raise typer.Exit(code=1) from None

    typer.echo(f"Cloned {source_run_id} -> {run_info.run_id}")
    typer.echo(f"  Path: {new_run_dir}")


def _replace_tree(source: Path, destination: Path) -> None:
    """Replace a pre-created directory with a copy of *source*."""
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)


def _collect_existing_ids(source_dir: Path, dest_parent: Path) -> set[str]:
    """Collect nearby run IDs for clone allocation."""
    existing_ids = collect_existing_run_ids(dest_parent)
    try:
        project_root = find_project_root(source_dir)
    except SimctlError:
        project_root = None
    if project_root is not None:
        existing_ids |= collect_existing_run_ids(project_root / "runs")
    return existing_ids
