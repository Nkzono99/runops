"""Safe run-directory relabeling without changing immutable run IDs."""

from __future__ import annotations

from pathlib import Path

from runops.application.actions.result import ActionResult, ActionStatus
from runops.core.manifest import read_manifest, write_manifest
from runops.core.state import RunState
from runops.core.survey.naming import render_run_directory_name

_ACTIVE_STATES = {RunState.SUBMITTED.value, RunState.RUNNING.value}


def plan_run_relabel(run_dir: Path) -> ActionResult:
    """Plan a legacy run-directory relabel from its manifest display name."""
    source = run_dir.resolve()
    try:
        manifest = read_manifest(source)
    except Exception as exc:
        return _error(f"Cannot read {source}: {exc}")

    run_id = str(manifest.run.get("id", "")).strip()
    display_name = str(manifest.run.get("display_name", "")).strip()
    state = str(manifest.run.get("status", "")).strip()
    if not run_id:
        return _precondition("Manifest has no run.id.", source=source)
    if source.name != run_id:
        return ActionResult(
            action="relabel_run",
            status=ActionStatus.SUCCESS,
            message="Run directory already has a label.",
            data={"source_path": str(source), "run_id": run_id, "changed": False},
            state_before=state,
            state_after=state,
        )
    if state in _ACTIVE_STATES:
        return _precondition(
            f"Run state is {state!r}; active runs cannot be relabeled.",
            source=source,
            run_id=run_id,
            state=state,
        )
    if not display_name:
        return _precondition(
            "Manifest has no run.display_name to use as a directory label.",
            source=source,
            run_id=run_id,
            state=state,
        )

    destination = source.with_name(render_run_directory_name(run_id, display_name))
    if destination == source:
        return _precondition(
            "Display name does not produce a usable directory label.",
            source=source,
            run_id=run_id,
            state=state,
        )
    if destination.exists():
        return _precondition(
            f"Destination already exists: {destination}",
            source=source,
            run_id=run_id,
            state=state,
        )

    return ActionResult(
        action="relabel_run",
        status=ActionStatus.SUCCESS,
        message=f"Relabel {source.name} as {destination.name}.",
        data={
            "source_path": str(source),
            "destination_path": str(destination),
            "run_id": run_id,
            "display_name": display_name,
            "changed": True,
        },
        state_before=state,
        state_after=state,
    )


def relabel_run(run_dir: Path) -> ActionResult:
    """Relabel one inactive run directory and update path-bearing metadata."""
    plan = plan_run_relabel(run_dir)
    if plan.status is not ActionStatus.SUCCESS or not plan.data.get("changed"):
        return plan

    source = Path(str(plan.data["source_path"]))
    destination = Path(str(plan.data["destination_path"]))
    state = plan.state_before
    try:
        manifest = read_manifest(source)
        original_manifest = (source / "manifest.toml").read_bytes()
        job_path = source / "submit" / "job.sh"
        original_job = job_path.read_bytes() if job_path.is_file() else None
        original_job_mode = (
            job_path.stat().st_mode if original_job is not None else None
        )
        replacements = _path_replacements(manifest.path, source, destination)
        manifest.path["run_dir"] = str(destination)
        archived_from = manifest.path.get("archived_from")
        if isinstance(archived_from, str):
            replacement = replacements.get(archived_from)
            if replacement is not None:
                manifest.path["archived_from"] = replacement

        source.rename(destination)
        try:
            destination_job = destination / "submit" / "job.sh"
            if original_job is not None:
                text = original_job.decode("utf-8")
                for old_path, new_path in replacements.items():
                    text = text.replace(old_path, new_path)
                destination_job.write_text(text, encoding="utf-8")
                if original_job_mode is not None:
                    destination_job.chmod(original_job_mode)
            write_manifest(destination, manifest, log_event=False)
        except Exception:
            (destination / "manifest.toml").write_bytes(original_manifest)
            if original_job is not None:
                rollback_job = destination / "submit" / "job.sh"
                rollback_job.write_bytes(original_job)
            destination.rename(source)
            raise
    except Exception as exc:
        return _error(f"Failed to relabel {source}: {exc}", state=state)

    return ActionResult(
        action="relabel_run",
        status=ActionStatus.SUCCESS,
        message=f"Relabeled {source.name} as {destination.name}.",
        data={
            "source_path": str(source),
            "destination_path": str(destination),
            "run_id": str(plan.data["run_id"]),
            "changed": True,
        },
        state_before=state,
        state_after=state,
    )


def _path_replacements(
    manifest_paths: dict[str, object], source: Path, destination: Path
) -> dict[str, str]:
    replacements = {str(source): str(destination)}
    run_id = source.name
    for value in manifest_paths.values():
        if not isinstance(value, str) or not value:
            continue
        path = Path(value)
        if path.name == run_id:
            replacements[value] = str(path.with_name(destination.name))
    return replacements


def _precondition(
    message: str,
    *,
    source: Path,
    run_id: str = "",
    state: str = "",
) -> ActionResult:
    return ActionResult(
        action="relabel_run",
        status=ActionStatus.PRECONDITION_FAILED,
        message=message,
        data={"source_path": str(source), "run_id": run_id, "changed": False},
        state_before=state,
        state_after=state,
    )


def _error(message: str, *, state: str = "") -> ActionResult:
    return ActionResult(
        action="relabel_run",
        status=ActionStatus.ERROR,
        message=message,
        state_before=state,
        state_after=state,
    )
