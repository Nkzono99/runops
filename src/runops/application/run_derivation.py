"""Application workflows for deriving and inspecting formal Runs.

The CLI and Agent Gateway share these use cases so Experiment admission,
scientific-identity reuse, source locking, and atomic publication cannot drift.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runops.adapters.base import SimulatorAdapter
from runops.application.execution.submission import submission_guard
from runops.application.experiments import experiment_lock, resolve_experiment
from runops.application.run_budget import (
    collect_experiment_run_records,
    declared_manifest_core_hours,
    enforce_experiment_run_budget,
    enforce_project_unreviewed_completed_budget,
    persist_manifest_budget_usage,
)
from runops.application.run_creation import (
    RegenerateResult,
    allows_equivalent_execution,
    build_standalone_manifest_metadata,
    commit_staged_directory,
    create_case_run,
    finalize_manifest_metadata,
    find_equivalent_completed_run,
    regenerate_run,
    release_unused_run_id,
    require_formal_run_target,
    reserve_run_id,
)
from runops.application.run_namespace import run_namespace_guard
from runops.core.discovery import collect_existing_run_ids
from runops.core.exceptions import ProjectNotFoundError, SimctlError
from runops.core.experiment import ExperimentData, load_experiment
from runops.core.manifest import ManifestData, read_manifest, write_manifest
from runops.core.project import ProjectConfig, find_project_root, load_project
from runops.core.run import (
    RunInfo,
    create_run_directory,
    next_run_id,
    rewrite_job_script_references,
    sanitize_derived_manifest,
)

_COMPLETED_EQUIVALENT = frozenset({"completed", "archived", "purged"})


class _DerivationPublicationAmbiguousError(SimctlError):
    """Admission failed after publish and automatic rollback was inconclusive."""


@dataclass(frozen=True)
class CloneRunResult:
    """Outcome of a clone derivation."""

    source_run_id: str
    run_info: RunInfo
    reused: bool = False
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExtendRunResult:
    """Outcome of a continuation derivation."""

    source_run_id: str
    run_info: RunInfo
    continuation: dict[str, Any]
    reused: bool = False
    warnings: tuple[str, ...] = ()


def clone_run(
    source_dir: Path,
    *,
    dest_dir: Path | None = None,
    overrides: dict[str, str] | None = None,
    experiment_id: str | None = None,
    purpose: str | None = None,
) -> CloneRunResult:
    """Clone a completed-equivalent Run under one stable source snapshot."""
    source_dir = source_dir.resolve()
    initial_manifest = read_manifest(source_dir)
    source_run_id = str(initial_manifest.run.get("id", source_dir.name))
    dest_parent = (dest_dir or source_dir.parent).resolve()
    clean_overrides = dict(overrides or {})

    try:
        destination_project_root = find_project_root(dest_parent)
    except ProjectNotFoundError:
        destination_project_root = None

    if destination_project_root is not None and clean_overrides:
        # ``create_case_run`` acquires the Experiment lock.  Freeze the source
        # manifest first, then release its guard so this path never nests the
        # two locks in the opposite order from retry and copy derivations.
        with submission_guard(source_dir):
            source_manifest = read_manifest(source_dir)
            _require_stable_source(
                source_manifest,
                expected_run_id=source_run_id,
                operation="clone",
            )
            target_experiment, target_purpose = _resolve_target_intent(
                source_manifest,
                experiment_id=experiment_id,
                purpose=purpose,
            )
        return _clone_with_regenerated_inputs(
            project_root=destination_project_root,
            source_manifest=source_manifest,
            source_run_id=source_run_id,
            dest_parent=dest_parent,
            overrides=clean_overrides,
            experiment_id=target_experiment,
            purpose=target_purpose,
        )

    if destination_project_root is None:
        try:
            source_project_root = find_project_root(source_dir)
        except ProjectNotFoundError:
            source_project_root = None
        if source_project_root is not None:
            # A managed source cannot authorize publication outside a managed
            # destination.  Preserve the formal-target diagnostic used by the
            # normal managed creation paths.
            require_formal_run_target(source_project_root, dest_parent)
            raise SimctlError(
                "managed Run clone destination must belong to its project"
            )
        if clean_overrides:
            raise SimctlError(
                "--set requires a destination inside a managed runops project "
                "so the destination case can regenerate inputs"
            )
        with submission_guard(source_dir):
            source_manifest = read_manifest(source_dir)
            _require_stable_source(
                source_manifest,
                expected_run_id=source_run_id,
                operation="clone",
            )
            _, target_purpose = _resolve_target_intent(
                source_manifest,
                experiment_id=experiment_id,
                purpose=purpose,
            )
            return _clone_standalone_by_copy(
                source_dir=source_dir,
                source_manifest=source_manifest,
                source_run_id=source_run_id,
                dest_parent=dest_parent,
                purpose=target_purpose,
            )

    return _clone_managed_by_copy(
        project_root=destination_project_root,
        source_dir=source_dir,
        source_run_id=source_run_id,
        dest_parent=dest_parent,
        experiment_id=experiment_id,
        purpose=purpose,
    )


def _clone_managed_by_copy(
    *,
    project_root: Path,
    source_dir: Path,
    source_run_id: str,
    dest_parent: Path,
    experiment_id: str | None,
    purpose: str | None,
) -> CloneRunResult:
    """Apply the destination project's admission contract to a copied Run."""
    project = load_project(project_root)
    require_formal_run_target(project_root, dest_parent)
    # Global order for operations that need both locks: Experiment, then Run.
    with (
        experiment_lock(project_root),
        submission_guard(source_dir),
        run_namespace_guard(project_root),
    ):
        source_manifest = read_manifest(source_dir)
        _require_stable_source(
            source_manifest,
            expected_run_id=source_run_id,
            operation="clone",
        )
        target_experiment, target_purpose = _resolve_target_intent(
            source_manifest,
            experiment_id=experiment_id,
            purpose=purpose,
        )
        return _clone_managed_by_copy_locked(
            project=project,
            project_root=project_root,
            source_dir=source_dir,
            source_manifest=source_manifest,
            source_run_id=source_run_id,
            dest_parent=dest_parent,
            experiment_id=target_experiment,
            purpose=target_purpose,
        )


def _clone_with_regenerated_inputs(
    *,
    project_root: Path,
    source_manifest: ManifestData,
    source_run_id: str,
    dest_parent: Path,
    overrides: dict[str, str],
    experiment_id: str,
    purpose: str,
) -> CloneRunResult:
    case_name = str(source_manifest.origin.get("case", "")).strip()
    if not case_name:
        raise SimctlError(
            "--set requires a source manifest with origin.case so inputs "
            "can be regenerated"
        )
    project = load_project(project_root)
    require_formal_run_target(project_root, dest_parent)
    params = dict(source_manifest.params_snapshot)
    params.update(overrides)
    created = create_case_run(
        project,
        case_name,
        dest_dir=dest_parent,
        display_name=f"clone of {source_run_id}",
        params=params,
        experiment_id=experiment_id,
        purpose=purpose,
        created_by="human:clone",
        parent_run_id=source_run_id,
        changed_keys=tuple(overrides),
    )
    return CloneRunResult(
        source_run_id=source_run_id,
        run_info=created.run_info,
        reused=created.reused,
        warnings=created.warnings,
    )


def _clone_managed_by_copy_locked(
    *,
    project: ProjectConfig,
    project_root: Path,
    source_dir: Path,
    source_manifest: ManifestData,
    source_run_id: str,
    dest_parent: Path,
    experiment_id: str,
    purpose: str,
) -> CloneRunResult:
    """Copy a managed Run while the Experiment and source locks are held."""
    metadata = build_standalone_manifest_metadata(
        project,
        experiment_id=experiment_id,
        purpose=purpose,
        created_by="human:clone",
    )
    existing_ids = collect_existing_run_ids(project_root / "runs")
    # An external parent is outside the project-wide allocator scan, but the
    # derived Run must still not receive the same identity as its parent edge.
    existing_ids.add(source_run_id)
    run_id = reserve_run_id(project_root, existing_ids)
    reservation_token = f"run:{run_id}"
    metadata.setdefault("identity", {})["budget_reservation"] = reservation_token
    experiment = (
        load_experiment(resolve_experiment(project_root, experiment_id.strip()))
        if experiment_id.strip()
        else None
    )
    dest_parent.mkdir(parents=True, exist_ok=True)
    final_run_dir = dest_parent / run_id
    if final_run_dir.exists() or final_run_dir.is_symlink():
        raise SimctlError(f"Run destination already exists: {final_run_dir}")
    staging_run_dir = create_run_directory(dest_parent, f".tmp-{run_id}")
    run_info = RunInfo(
        run_id=run_id,
        run_dir=final_run_dir,
        display_name=f"clone of {source_run_id}",
        params=dict(source_manifest.params_snapshot),
        created_at=datetime.now(tz=timezone.utc).isoformat(),
    )
    committed = False
    try:
        source_input = source_dir / "input"
        if source_input.is_dir():
            _replace_tree(source_input, staging_run_dir / "input")
        source_submit = source_dir / "submit"
        if source_submit.is_dir():
            _replace_tree(source_submit, staging_run_dir / "submit")
            rewrite_job_script_references(
                staging_run_dir / "submit" / "job.sh",
                source_dir=source_dir,
                target_dir=final_run_dir,
                source_run_id=source_run_id,
                target_run_id=run_info.run_id,
            )

        new_manifest = sanitize_derived_manifest(
            source_manifest,
            run_info=run_info,
            parent_run_id=source_run_id,
            display_name=run_info.display_name,
            params_snapshot=run_info.params,
        )
        finalize_manifest_metadata(new_manifest, staging_run_dir, metadata)
        equivalent = find_equivalent_completed_run(project_root, new_manifest)
        if equivalent is not None and not allows_equivalent_execution(purpose):
            existing_dir, existing_manifest = equivalent
            release_unused_run_id(project_root, run_id)
            return CloneRunResult(
                source_run_id=source_run_id,
                run_info=_existing_run_info(existing_dir, existing_manifest),
                reused=True,
            )

        core_hours = declared_manifest_core_hours(source_manifest)
        if experiment is not None:
            enforce_experiment_run_budget(
                project,
                experiment,
                new_count=1,
                new_core_hours=core_hours,
                reservation_tokens=(reservation_token,),
                persist=False,
            )
        else:
            enforce_project_unreviewed_completed_budget(project)
        write_manifest(staging_run_dir, new_manifest)
        try:
            _commit_managed_derivation(
                project_root=project_root,
                parent_dir=dest_parent,
                staging_run_dir=staging_run_dir,
                final_run_dir=final_run_dir,
                experiment_snapshot=experiment,
                experiment_id=experiment_id,
                purpose=purpose,
                run_id=run_id,
                reservation_token=reservation_token,
                core_hours=core_hours,
            )
        except _DerivationPublicationAmbiguousError:
            committed = True
            raise
        committed = True
        warnings = _commit_usage_ledger(
            project,
            experiment,
            final_run_dir,
            new_manifest,
        )
        return CloneRunResult(
            source_run_id=source_run_id,
            run_info=run_info,
            warnings=warnings,
        )
    finally:
        if not committed and staging_run_dir.exists():
            shutil.rmtree(staging_run_dir, ignore_errors=True)


def _clone_standalone_by_copy(
    *,
    source_dir: Path,
    source_manifest: ManifestData,
    source_run_id: str,
    dest_parent: Path,
    purpose: str,
) -> CloneRunResult:
    """Preserve explicit legacy cloning outside a managed project."""
    dest_parent.mkdir(parents=True, exist_ok=True)
    run_id = next_run_id(_collect_existing_ids(source_dir, dest_parent))
    final_run_dir = dest_parent / run_id
    staging_run_dir = create_run_directory(dest_parent, f".tmp-{run_id}")
    run_info = RunInfo(
        run_id=run_id,
        run_dir=final_run_dir,
        display_name=f"clone of {source_run_id}",
        params=dict(source_manifest.params_snapshot),
        created_at=datetime.now(tz=timezone.utc).isoformat(),
    )
    committed = False
    try:
        source_input = source_dir / "input"
        if source_input.is_dir():
            _replace_tree(source_input, staging_run_dir / "input")
        source_submit = source_dir / "submit"
        if source_submit.is_dir():
            _replace_tree(source_submit, staging_run_dir / "submit")
            rewrite_job_script_references(
                staging_run_dir / "submit" / "job.sh",
                source_dir=source_dir,
                target_dir=final_run_dir,
                source_run_id=source_run_id,
                target_run_id=run_id,
            )
        manifest = sanitize_derived_manifest(
            source_manifest,
            run_info=run_info,
            parent_run_id=source_run_id,
            display_name=run_info.display_name,
            params_snapshot=run_info.params,
        )
        finalize_manifest_metadata(
            manifest,
            staging_run_dir,
            {"intent": {"purpose": purpose, "created_by": "human:clone"}},
        )
        write_manifest(staging_run_dir, manifest)
        commit_staged_directory(staging_run_dir, final_run_dir)
        committed = True
        return CloneRunResult(source_run_id=source_run_id, run_info=run_info)
    finally:
        if not committed and staging_run_dir.exists():
            shutil.rmtree(staging_run_dir, ignore_errors=True)


def extend_run(
    source_dir: Path,
    *,
    dest_dir: Path | None = None,
    nstep: int | None = None,
    experiment_id: str | None = None,
    purpose: str | None = None,
) -> ExtendRunResult:
    """Create a continuation from a completed-equivalent source snapshot."""
    source_dir = source_dir.resolve()
    initial_manifest = read_manifest(source_dir)
    source_id = str(initial_manifest.run.get("id", source_dir.name))
    _require_stable_source(
        initial_manifest,
        expected_run_id=source_id,
        operation="continuation",
    )
    target_dir = (dest_dir or source_dir.parent).resolve()
    project_root = find_project_root(source_dir)
    project = load_project(project_root)
    require_formal_run_target(project_root, target_dir)
    adapter = _load_adapter(project, initial_manifest)

    # Match retry and managed clone: Experiment admission always precedes the
    # per-Run source lock, so the pair cannot deadlock by lock inversion.
    with (
        experiment_lock(project_root),
        submission_guard(source_dir),
        run_namespace_guard(project_root),
    ):
        source_manifest = read_manifest(source_dir)
        _require_stable_source(
            source_manifest,
            expected_run_id=source_id,
            operation="continuation",
        )
        if source_manifest.simulator != initial_manifest.simulator:
            raise SimctlError("continuation source simulator metadata changed")
        target_experiment, target_purpose = _resolve_target_intent(
            source_manifest,
            experiment_id=experiment_id,
            purpose=purpose,
        )
        return _extend_locked(
            project=project,
            project_root=project_root,
            source_dir=source_dir,
            source_manifest=source_manifest,
            source_id=source_id,
            target_dir=target_dir,
            experiment_id=target_experiment,
            purpose=target_purpose,
            adapter=adapter,
            nstep=nstep,
        )


def _extend_locked(
    *,
    project: ProjectConfig,
    project_root: Path,
    source_dir: Path,
    source_manifest: ManifestData,
    source_id: str,
    target_dir: Path,
    experiment_id: str,
    purpose: str,
    adapter: SimulatorAdapter,
    nstep: int | None,
) -> ExtendRunResult:
    """Create a continuation while the Experiment and source locks are held."""
    params = dict(source_manifest.params_snapshot)
    metadata = build_standalone_manifest_metadata(
        project,
        experiment_id=experiment_id,
        purpose=purpose,
        created_by="human:extend",
    )
    existing_ids = collect_existing_run_ids(project_root / "runs")
    run_id = reserve_run_id(project_root, existing_ids)
    reservation_token = f"run:{run_id}"
    metadata.setdefault("identity", {})["budget_reservation"] = reservation_token
    experiment = (
        load_experiment(resolve_experiment(project_root, experiment_id.strip()))
        if experiment_id.strip()
        else None
    )
    target_dir.mkdir(parents=True, exist_ok=True)
    final_run_dir = target_dir / run_id
    if final_run_dir.exists() or final_run_dir.is_symlink():
        raise SimctlError(f"Run destination already exists: {final_run_dir}")
    staging_run_dir = create_run_directory(target_dir, f".tmp-{run_id}")
    run_info = RunInfo(
        run_id=run_id,
        run_dir=final_run_dir,
        display_name=f"extend_{source_id}",
        params=params,
        created_at=datetime.now(tz=timezone.utc).isoformat(),
    )
    committed = False
    try:
        _copy_continuation_inputs(source_dir, staging_run_dir)
        continuation = _setup_continuation(
            adapter,
            source_dir=source_dir,
            staging_run_dir=staging_run_dir,
            nstep=nstep,
        )
        _copy_continuation_job(
            source_dir=source_dir,
            staging_run_dir=staging_run_dir,
            final_run_dir=final_run_dir,
            source_id=source_id,
            run_id=run_id,
        )
        for name in ("work", "analysis", "status"):
            (staging_run_dir / name).mkdir(exist_ok=True)

        new_manifest = sanitize_derived_manifest(
            source_manifest,
            run_info=run_info,
            parent_run_id=source_id,
            display_name=run_info.display_name,
            params_snapshot=params,
        )
        finalize_manifest_metadata(new_manifest, staging_run_dir, metadata)
        equivalent = find_equivalent_completed_run(project_root, new_manifest)
        if equivalent is not None and not allows_equivalent_execution(purpose):
            existing_dir, existing_manifest = equivalent
            release_unused_run_id(project_root, run_id)
            return ExtendRunResult(
                source_run_id=source_id,
                run_info=_existing_run_info(existing_dir, existing_manifest),
                continuation={"reused": "equivalent scientific_hash"},
                reused=True,
            )

        core_hours = declared_manifest_core_hours(source_manifest)
        if experiment is not None:
            enforce_experiment_run_budget(
                project,
                experiment,
                new_count=1,
                new_core_hours=core_hours,
                reservation_tokens=(reservation_token,),
                persist=False,
            )
        else:
            enforce_project_unreviewed_completed_budget(project)
        write_manifest(staging_run_dir, new_manifest)
        try:
            _commit_managed_derivation(
                project_root=project_root,
                parent_dir=target_dir,
                staging_run_dir=staging_run_dir,
                final_run_dir=final_run_dir,
                experiment_snapshot=experiment,
                experiment_id=experiment_id,
                purpose=purpose,
                run_id=run_id,
                reservation_token=reservation_token,
                core_hours=core_hours,
            )
        except _DerivationPublicationAmbiguousError:
            committed = True
            raise
        committed = True
        warnings = _commit_usage_ledger(
            project,
            experiment,
            final_run_dir,
            new_manifest,
        )
        return ExtendRunResult(
            source_run_id=source_id,
            run_info=run_info,
            continuation=continuation,
            warnings=warnings,
        )
    finally:
        if not committed and staging_run_dir.exists():
            shutil.rmtree(staging_run_dir, ignore_errors=True)


def _commit_managed_derivation(
    *,
    project_root: Path,
    parent_dir: Path,
    staging_run_dir: Path,
    final_run_dir: Path,
    experiment_snapshot: ExperimentData | None,
    experiment_id: str,
    purpose: str,
    run_id: str,
    reservation_token: str,
    core_hours: float,
) -> None:
    """Publish one derivation across current-admission checks on both sides."""

    def require_current_admission() -> None:
        current_project = load_project(project_root)
        build_standalone_manifest_metadata(
            current_project,
            experiment_id=experiment_id,
            purpose=purpose,
            created_by="derivation:publication-cas",
        )
        if experiment_snapshot is None:
            enforce_project_unreviewed_completed_budget(current_project)
            return

        current_experiment = load_experiment(
            resolve_experiment(project_root, experiment_id)
        )
        if current_experiment != experiment_snapshot:
            raise SimctlError(
                f"Experiment {experiment_id} changed while the Run was staged; "
                "retry the derivation from current admission metadata"
            )
        records = collect_experiment_run_records(project_root, experiment_id)
        published = any(
            str(record.manifest.run.get("id", "")) == run_id for record in records
        )
        enforce_experiment_run_budget(
            current_project,
            current_experiment,
            new_count=0 if published else 1,
            new_core_hours=0.0 if published else core_hours,
            reservation_tokens=() if published else (reservation_token,),
            records=records,
            persist=False,
        )

    with run_namespace_guard(project_root):
        require_formal_run_target(project_root, parent_dir)
        require_current_admission()
        commit_staged_directory(staging_run_dir, final_run_dir)
        try:
            require_current_admission()
        except BaseException as guard_exc:
            try:
                commit_staged_directory(final_run_dir, staging_run_dir)
            except BaseException as rollback_exc:
                raise _DerivationPublicationAmbiguousError(
                    "Derived Run was published but its admission CAS failed, and "
                    "automatic publication rollback also failed; published state "
                    f"was retained for recovery: {rollback_exc}"
                ) from guard_exc
            raise


def inspect_run_regeneration(
    run_dir: Path,
    *,
    dry_run: bool = False,
) -> RegenerateResult:
    """Inspect case-template drift without permitting in-place identity changes."""
    run_dir = run_dir.resolve()
    project_root = find_project_root(run_dir)
    project = load_project(project_root)
    return regenerate_run(project, run_dir, dry_run=dry_run)


def _load_adapter(
    project: ProjectConfig,
    source_manifest: ManifestData,
) -> SimulatorAdapter:
    adapter_name = str(source_manifest.simulator.get("adapter", "")).strip()
    if not adapter_name:
        adapter_name = str(source_manifest.simulator.get("name", "")).strip()
    if not adapter_name:
        raise SimctlError("source Run has no simulator adapter or name")
    try:
        from runops.adapters.registry import get as get_adapter
        from runops.adapters.registry import load_from_config

        load_from_config(project.simulators)
        adapter_cls = get_adapter(adapter_name)
        return adapter_cls()
    except Exception as exc:
        raise SimctlError(f"Error loading adapter {adapter_name!r}: {exc}") from exc


def _copy_continuation_inputs(source_dir: Path, staging_run_dir: Path) -> None:
    new_input = staging_run_dir / "input"
    new_input.mkdir(parents=True, exist_ok=True)
    source_input = source_dir / "input"
    if not source_input.is_dir():
        return
    _require_safe_copy_tree(source_input)
    for item in source_input.iterdir():
        destination = new_input / item.name
        if item.is_file():
            shutil.copy2(item, destination)
        elif item.is_dir():
            shutil.copytree(item, destination, dirs_exist_ok=True)


def _setup_continuation(
    adapter: SimulatorAdapter,
    *,
    source_dir: Path,
    staging_run_dir: Path,
    nstep: int | None,
) -> dict[str, Any]:
    setup = getattr(adapter, "setup_continuation", None)
    if setup is None:
        return {}
    try:
        raw = setup(
            source_dir=source_dir,
            new_dir=staging_run_dir,
            nstep_override=nstep,
        )
    except Exception as exc:
        raise SimctlError(f"adapter continuation setup failed: {exc}") from exc
    return dict(raw or {})


def _copy_continuation_job(
    *,
    source_dir: Path,
    staging_run_dir: Path,
    final_run_dir: Path,
    source_id: str,
    run_id: str,
) -> None:
    source_job = source_dir / "submit" / "job.sh"
    new_submit = staging_run_dir / "submit"
    new_submit.mkdir(parents=True, exist_ok=True)
    if not source_job.is_file():
        return
    if source_job.is_symlink():
        raise SimctlError(
            f"continuation job source must not be a symlink: {source_job}"
        )
    new_job = new_submit / "job.sh"
    shutil.copy2(source_job, new_job)
    rewrite_job_script_references(
        new_job,
        source_dir=source_dir,
        target_dir=final_run_dir,
        source_run_id=source_id,
        target_run_id=run_id,
    )


def _commit_usage_ledger(
    project: ProjectConfig,
    experiment: ExperimentData | None,
    run_dir: Path,
    manifest: ManifestData,
) -> tuple[str, ...]:
    if experiment is None:
        return ()
    try:
        persist_manifest_budget_usage(project.root_dir, run_dir, manifest)
    except SimctlError as exc:
        return (
            "Run committed; Experiment usage ledger will be rebuilt from its "
            f"manifest ({exc})",
        )
    return ()


def _existing_run_info(run_dir: Path, manifest: ManifestData) -> RunInfo:
    run_id = str(manifest.run.get("id", run_dir.name))
    return RunInfo(
        run_id=run_id,
        run_dir=run_dir,
        display_name=str(manifest.run.get("display_name", run_id)),
        created_at=str(manifest.run.get("created_at", "")),
        params=dict(manifest.params_snapshot),
    )


def _replace_tree(source: Path, destination: Path) -> None:
    _require_safe_copy_tree(source)
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)


def _require_safe_copy_tree(source: Path) -> None:
    if source.is_symlink() or not source.is_dir():
        raise SimctlError(f"copy source must be a real directory: {source}")
    for path in source.rglob("*"):
        if path.is_symlink():
            raise SimctlError(f"copy source must not contain symlinks: {path}")
        if not path.is_file() and not path.is_dir():
            raise SimctlError(f"copy source contains a special file: {path}")


def _require_stable_source(
    manifest: ManifestData,
    *,
    expected_run_id: str,
    operation: str,
) -> None:
    run_id = str(manifest.run.get("id", ""))
    if run_id != expected_run_id:
        raise SimctlError(
            f"{operation} source identity changed: expected {expected_run_id}, "
            f"found {run_id}"
        )
    status = str(manifest.run.get("status", ""))
    if status not in _COMPLETED_EQUIVALENT:
        raise SimctlError(
            f"{operation} source {run_id} is {status!r}; expected a "
            "completed-equivalent snapshot"
        )


def _resolve_target_intent(
    source_manifest: ManifestData,
    *,
    experiment_id: str | None,
    purpose: str | None,
) -> tuple[str, str]:
    """Resolve inherited intent from the source snapshot held by the caller."""
    source_experiment = str(source_manifest.intent.get("experiment_id", ""))
    source_purpose = str(source_manifest.intent.get("purpose", ""))
    return (
        source_experiment if experiment_id is None else experiment_id,
        source_purpose if purpose is None else purpose,
    )


def _collect_existing_ids(source_dir: Path, dest_parent: Path) -> set[str]:
    existing_ids = collect_existing_run_ids(dest_parent)
    try:
        project_root = find_project_root(source_dir)
    except SimctlError:
        return existing_ids
    return existing_ids | collect_existing_run_ids(project_root / "runs")


__all__ = [
    "CloneRunResult",
    "ExtendRunResult",
    "clone_run",
    "extend_run",
    "inspect_run_regeneration",
]
