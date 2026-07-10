"""CLI command for extending/continuing a simulation from a snapshot."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Annotated, Any, Optional

import typer

from runops.cli.run_lookup import resolve_run_or_cwd
from runops.core.discovery import collect_existing_run_ids
from runops.core.exceptions import SimctlError
from runops.core.manifest import ManifestData, read_manifest, write_manifest
from runops.core.project import find_project_root, load_project
from runops.core.run import create_run, rewrite_job_script_references


def extend(
    run: Annotated[
        Optional[str],
        typer.Argument(help="Source run to continue from (defaults to cwd)."),
    ] = None,
    dest: Annotated[
        Optional[Path],
        typer.Option(
            "--dest", "-d", help="Destination directory (defaults to source's parent)."
        ),
    ] = None,
    nstep: Annotated[
        Optional[int],
        typer.Option("--nstep", help="Override total step count for continuation."),
    ] = None,
    submit: Annotated[
        bool,
        typer.Option("--run", help="Automatically submit the continuation run."),
    ] = False,
) -> None:
    """Create a continuation run from a completed simulation's snapshot.

    Copies input files, links snapshots, and updates restart parameters.
    The adapter handles simulator-specific continuation setup.

    Examples:
      runo runs extend                      # continue cwd run
      runo runs extend R0001 --nstep 200000 # continue with more steps
      runo runs extend --run                # continue and submit
    """
    source_dir = resolve_run_or_cwd(run, search_dir=Path.cwd())

    # Read source manifest
    try:
        source_manifest = read_manifest(source_dir)
    except SimctlError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from None

    source_id = source_manifest.run.get("id", source_dir.name)
    source_status = source_manifest.run.get("status", "")

    if source_status not in ("completed", "running", "failed"):
        typer.echo(
            f"Warning: source run {source_id} is '{source_status}'. "
            "Continuation is typically from completed runs."
        )

    # Determine destination
    target_dir = dest or source_dir.parent
    target_dir = target_dir.resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    # Load project for adapter/launcher
    try:
        project_root = find_project_root(target_dir)
        project = load_project(project_root)
    except SimctlError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from None

    # Get adapter
    adapter_name = source_manifest.simulator.get("adapter", "")
    if not adapter_name:
        adapter_name = source_manifest.simulator.get("name", "")

    try:
        from runops.adapters.registry import get as get_adapter
        from runops.adapters.registry import load_from_config

        load_from_config(project.simulators)
        adapter_cls = get_adapter(adapter_name)
        adapter = adapter_cls()
    except (KeyError, Exception) as e:
        typer.echo(f"Error loading adapter '{adapter_name}': {e}", err=True)
        raise typer.Exit(code=1) from None

    # Collect existing run IDs
    runs_dir = project_root / "runs"
    existing_ids = collect_existing_run_ids(runs_dir)

    # Create new run directory
    params = dict(source_manifest.params_snapshot)
    try:
        run_info = create_run(
            target_dir,
            existing_ids,
            display_name=f"extend_{source_id}",
            params=params,
        )
    except SimctlError as e:
        typer.echo(f"Error creating run: {e}", err=True)
        raise typer.Exit(code=1) from None

    new_dir = run_info.run_dir
    new_input = new_dir / "input"
    new_input.mkdir(parents=True, exist_ok=True)

    # Copy input files from source
    source_input = source_dir / "input"
    if source_input.is_dir():
        for item in source_input.iterdir():
            dest_item = new_input / item.name
            if item.is_file():
                shutil.copy2(item, dest_item)
            elif item.is_dir():
                shutil.copytree(item, dest_item, dirs_exist_ok=True)

    # Let adapter set up continuation (snapshot links, parameter updates)
    continuation_info: dict[str, Any] = {}
    if hasattr(adapter, "setup_continuation"):
        try:
            continuation_info = adapter.setup_continuation(
                source_dir=source_dir,
                new_dir=new_dir,
                nstep_override=nstep,
            )
        except Exception as e:
            typer.echo(f"Error in adapter continuation setup: {e}", err=True)
            raise typer.Exit(code=1) from None

    # Copy job script from source if exists
    source_submit = source_dir / "submit"
    new_submit = new_dir / "submit"
    new_submit.mkdir(parents=True, exist_ok=True)
    source_job = source_submit / "job.sh"
    if source_job.is_file():
        new_job = new_submit / "job.sh"
        shutil.copy2(source_job, new_job)
        rewrite_job_script_references(
            new_job,
            source_dir=source_dir,
            target_dir=new_dir,
            source_run_id=source_id,
            target_run_id=run_info.run_id,
        )

    # Create work directory
    (new_dir / "work").mkdir(exist_ok=True)

    # Write manifest
    new_manifest = ManifestData(
        run={
            "id": run_info.run_id,
            "display_name": run_info.display_name,
            "status": "created",
            "created_at": run_info.created_at,
        },
        path={"run_dir": str(new_dir)},
        origin={
            "case": source_manifest.origin.get("case", ""),
            "survey": "",
            "parent_run": source_id,
        },
        classification=dict(source_manifest.classification),
        simulator=dict(source_manifest.simulator),
        launcher=dict(source_manifest.launcher),
        simulator_source=dict(source_manifest.simulator_source),
        job={
            "scheduler": "slurm",
            "job_id": "",
            "partition": source_manifest.job.get("partition", ""),
            "nodes": source_manifest.job.get("nodes", 1),
            "ntasks": source_manifest.job.get("ntasks", 1),
            "walltime": source_manifest.job.get("walltime", "01:00:00"),
            "submitted_at": "",
        },
        variation={"changed_keys": []},
        params_snapshot=params,
        files={
            "input_dir": "input",
            "submit_dir": "submit",
            "work_dir": "work",
            "analysis_dir": "analysis",
            "status_dir": "status",
        },
    )
    write_manifest(new_dir, new_manifest)

    typer.echo(f"Created continuation run: {run_info.run_id}")
    typer.echo(f"  Source: {source_id}")
    typer.echo(f"  Path:   {new_dir}")
    if continuation_info:
        for key, val in continuation_info.items():
            typer.echo(f"  {key}: {val}")

    # Auto-submit if requested
    if submit:
        from runops.cli.submit import _build_submit_plan, _submit_single_run

        try:
            plan = _build_submit_plan(new_dir)
        except SimctlError as exc:
            typer.echo(f"Warning: auto-submit planning failed: {exc}")
            raise typer.Exit(code=1) from exc
        job_id = _submit_single_run(plan)
        if job_id is None:
            typer.echo("Warning: auto-submit failed")
            raise typer.Exit(code=1)
