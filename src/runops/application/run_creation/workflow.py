"""Shared run creation workflows used by CLI commands and agents."""

from __future__ import annotations

import hashlib
import os
import shlex
import shutil
import stat
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runops.adapters.base import SimulatorAdapter
from runops.application.experiments import experiment_lock, resolve_experiment
from runops.application.run_budget import (
    collect_experiment_run_records,
    declared_job_core_hours,
    enforce_experiment_run_budget,
    enforce_project_unreviewed_completed_budget,
    persist_manifest_budget_usage,
)
from runops.application.run_discovery import resolve_project_run_strict
from runops.application.run_namespace import run_namespace_guard
from runops.core.case import (
    CaseData,
    load_case,
    resolve_case,
)
from runops.core.discovery import collect_existing_run_ids, discover_runs
from runops.core.event_log import emit_artifact_event
from runops.core.exceptions import (
    DuplicateRunIdError,
    ParameterValidationError,
    SimctlError,
)
from runops.core.experiment import (
    discover_experiments,
    experiment_is_expired,
    load_experiment,
)
from runops.core.manifest import ManifestData, read_manifest, write_manifest
from runops.core.models import run_creation as run_creation_models
from runops.core.project import ProjectConfig, load_project
from runops.core.run import RunInfo, create_run_directory
from runops.core.site import SiteProfile, load_site_profile
from runops.core.survey import (
    NamingConfig,
    canonical_data_hash,
)
from runops.jobgen.generator import generate_job_script
from runops.launchers.base import Launcher

from . import manifest as run_creation_manifest
from .identity import release_unused_run_id, reserve_run_id
from .resolve import (
    load_adapter_for_simulator,
    load_launcher_for_name,
    validate_case_references,
)
from .staging import (
    commit_staged_directory,
)
from .staging import (
    copy_case_files as _copy_case_files,
)
from .staging import (
    next_available_run_target as _next_available_run_target,
)
from .staging import reserved_run_target as _reserved_run_target

_RUN_ID_ALLOCATION_ATTEMPTS = 10_000
_CALLER_IDENTITY_FIELDS = frozenset({"budget_reservation", "plan_hash", "point_id"})
_EXECUTION_JOB_FIELDS = frozenset(
    {
        "cores",
        "gpus",
        "memory",
        "modules",
        "nodes",
        "ntasks",
        "partition",
        "post_commands",
        "pre_commands",
        "processes",
        "qos",
        "scheduler",
        "threads",
        "walltime",
    }
)
_PROVENANCE_LOCATION_FIELDS = frozenset(
    {
        "build_command",
        "executable",
        "pre_job_setup_executable",
        "source_repo",
    }
)

CreatedRunResult = run_creation_models.CreatedRunResult
RegenerateResult = run_creation_models.RegenerateResult
SurveyExpansionPlan = run_creation_models.SurveyExpansionPlan

_build_job_config = run_creation_manifest.build_job_config
_build_manifest = run_creation_manifest.build_manifest
_build_manifest_job = run_creation_manifest.build_manifest_job
_build_site_execution_context = run_creation_manifest._build_site_execution_context
_get_simulator_config = run_creation_manifest.get_simulator_config
_is_rsc_site = run_creation_manifest.is_rsc_site
_merge_site_modules = run_creation_manifest.merge_site_modules
_rewrite_staging_paths = run_creation_manifest.rewrite_staging_paths


class _RunIdCollisionError(Exception):
    """Internal signal that a run_id was claimed before commit."""

    def __init__(self, run_id: str) -> None:
        super().__init__(run_id)
        self.run_id = run_id


def _is_plain_executable_name(executable: str) -> bool:
    """Return True for command names that can live under ``.venv/bin``."""
    path = Path(executable)
    return executable == path.name and not path.is_absolute()


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _align_package_runtime_with_job_environment(
    sim_config: dict[str, Any],
    runtime_info: dict[str, Any],
    project_root: Path,
    venv_activate: Path,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Prefer the project virtualenv executable when job.sh activates it."""
    if runtime_info.get("resolver_mode") != "package" or not venv_activate.is_file():
        return runtime_info, ()

    configured_executable = str(sim_config.get("executable", "")).strip()
    if not configured_executable or not _is_plain_executable_name(
        configured_executable
    ):
        return runtime_info, ()

    venv_dir = project_root / ".venv"
    venv_executable = venv_activate.parent / configured_executable
    resolved_executable = str(runtime_info.get("executable", "")).strip()
    warnings: list[str] = []

    if not venv_executable.is_file():
        resolved_path = Path(resolved_executable)
        if resolved_path.is_absolute() and not _path_is_within(resolved_path, venv_dir):
            warnings.append(
                f"package executable {configured_executable!r} resolved to "
                f"{resolved_executable} before job setup; job.sh activates .venv "
                f"but {venv_executable} was not found, so the generated job may "
                "bypass the project virtualenv."
            )
        return runtime_info, tuple(warnings)

    if resolved_executable == str(venv_executable):
        return runtime_info, ()

    aligned_runtime = dict(runtime_info)
    aligned_runtime["executable"] = str(venv_executable)
    if resolved_executable:
        aligned_runtime["pre_job_setup_executable"] = resolved_executable

    resolved_path = Path(resolved_executable)
    if resolved_path.is_absolute() and not _path_is_within(resolved_path, venv_dir):
        warnings.append(
            f"package executable {configured_executable!r} resolved to "
            f"{resolved_executable} before job setup; using project virtualenv "
            f"executable {venv_executable} because job.sh activates .venv."
        )

    return aligned_runtime, tuple(warnings)


def create_prepared_run(
    parent_dir: Path,
    case_data: CaseData,
    project: ProjectConfig,
    adapter: SimulatorAdapter,
    launcher: Launcher,
    site: SiteProfile,
    *,
    existing_ids: set[str] | None = None,
    params: dict[str, Any] | None = None,
    display_name: str = "",
    naming: NamingConfig | None = None,
    survey_id: str = "",
    variation_keys: list[str] | None = None,
    reserved_run_id: str = "",
    manifest_metadata: dict[str, dict[str, Any]] | None = None,
    commit_guard: Callable[[], None] | None = None,
) -> CreatedRunResult:
    """Generate one Run while excluding parent-directory bundle moves."""
    with run_namespace_guard(project.root_dir):
        return _create_prepared_run_locked(
            parent_dir,
            case_data,
            project,
            adapter,
            launcher,
            site,
            existing_ids=existing_ids,
            params=params,
            display_name=display_name,
            naming=naming,
            survey_id=survey_id,
            variation_keys=variation_keys,
            reserved_run_id=reserved_run_id,
            manifest_metadata=manifest_metadata,
            commit_guard=commit_guard,
        )


def _create_prepared_run_locked(
    parent_dir: Path,
    case_data: CaseData,
    project: ProjectConfig,
    adapter: SimulatorAdapter,
    launcher: Launcher,
    site: SiteProfile,
    *,
    existing_ids: set[str] | None = None,
    params: dict[str, Any] | None = None,
    display_name: str = "",
    naming: NamingConfig | None = None,
    survey_id: str = "",
    variation_keys: list[str] | None = None,
    reserved_run_id: str = "",
    manifest_metadata: dict[str, dict[str, Any]] | None = None,
    commit_guard: Callable[[], None] | None = None,
) -> CreatedRunResult:
    """Generate one run from already-resolved project/case dependencies."""
    effective_params = dict(case_data.params)
    if params:
        effective_params.update(params)

    case_section = {
        **case_data.raw.get("case", {}),
        "case_dir": str(case_data.case_dir),
    }
    validation_data = {"case": case_section, "params": effective_params}
    issues = adapter.validate_params(validation_data)

    base_warnings = tuple(i.message for i in issues if i.severity == "warning")
    errors = [i for i in issues if i.severity == "error"]
    if errors:
        raise ParameterValidationError(issues)

    known_ids = existing_ids
    if known_ids is None:
        known_ids = collect_existing_run_ids(project.root_dir / "runs")

    attempts = 1 if reserved_run_id else _RUN_ID_ALLOCATION_ATTEMPTS
    for _ in range(attempts):
        if reserved_run_id:
            run_id = reserved_run_id
            final_run_dir = _reserved_run_target(
                parent_dir,
                run_id,
                display_name=display_name,
                naming=naming,
            )
        else:
            run_id, final_run_dir = _next_available_run_target(
                parent_dir,
                known_ids,
                display_name=display_name,
                naming=naming,
            )
        staging_name = f".tmp-{run_id}"
        try:
            staging_run_dir = create_run_directory(parent_dir, staging_name)
        except FileExistsError:
            known_ids.add(run_id)
            continue
        created_at = datetime.now(tz=timezone.utc).isoformat()
        final_run_info = RunInfo(
            run_id=run_id,
            run_dir=final_run_dir,
            display_name=display_name,
            params=effective_params,
            created_at=created_at,
        )
        committed = False
        pending_artifacts: list[tuple[Path, str, str, str]] = []
        warnings = list(base_warnings)
        try:
            copied_inputs = _copy_case_files(
                case_data.case_dir,
                staging_run_dir / "input",
            )
            created_inputs = adapter.render_inputs(validation_data, staging_run_dir)
            for rel_path in copied_inputs + created_inputs:
                pending_artifacts.append(
                    (
                        final_run_dir / rel_path,
                        "create",
                        "input",
                        f"Create {rel_path}",
                    )
                )

            sim_config = _get_simulator_config(project, case_data.simulator)
            resolver_mode = sim_config.get("resolver_mode", "package")
            runtime_info = adapter.resolve_runtime(sim_config, resolver_mode)
            venv_activate = project.root_dir / ".venv" / "bin" / "activate"
            runtime_info, runtime_warnings = (
                _align_package_runtime_with_job_environment(
                    sim_config,
                    runtime_info,
                    project.root_dir,
                    venv_activate,
                )
            )
            warnings.extend(runtime_warnings)
            program_cmd = adapter.build_program_command(runtime_info, staging_run_dir)
            program_cmd = _rewrite_staging_paths(
                program_cmd,
                staging_run_dir,
                final_run_dir,
            )
            version_commands = adapter.build_version_capture_commands(
                runtime_info,
                program_cmd,
                final_run_dir,
            )

            effective_site = _merge_site_modules(site, case_data.simulator, sim_config)
            ntasks = (
                case_data.job.processes
                if _is_rsc_site(effective_site)
                else case_data.job.ntasks
            )
            exec_line = launcher.build_exec_line(program_cmd, ntasks)
            job_config = _build_job_config(case_data.job, effective_site)

            extra_setup: list[str] = []
            if venv_activate.exists():
                extra_setup.append(f"source {shlex.quote(str(venv_activate))}")

            generate_job_script(
                staging_run_dir,
                job_config,
                exec_line,
                run_id=final_run_info.run_id,
                site=effective_site,
                simulator_name=case_data.simulator,
                extra_setup_commands=extra_setup,
                version_commands=version_commands,
                script_run_dir=final_run_dir,
            )
            pending_artifacts.append(
                (
                    final_run_dir / "submit" / "job.sh",
                    "create",
                    "job_script",
                    "Create submit/job.sh",
                )
            )

            manifest = _build_manifest(
                final_run_info,
                case_data,
                project,
                runtime_info,
                adapter,
                effective_site,
                survey_id=survey_id,
                variation_keys=variation_keys,
            )
            finalize_manifest_metadata(
                manifest,
                staging_run_dir,
                manifest_metadata,
                site=effective_site,
            )
            equivalent = find_equivalent_completed_run(project.root_dir, manifest)
            if equivalent is not None and not allows_equivalent_execution(
                str(manifest.intent.get("purpose", ""))
            ):
                existing_dir, existing_manifest = equivalent
                existing_id = str(existing_manifest.run.get("id", existing_dir.name))
                return CreatedRunResult(
                    run_info=RunInfo(
                        run_id=existing_id,
                        run_dir=existing_dir,
                        display_name=str(
                            existing_manifest.run.get("display_name", existing_id)
                        ),
                        params=dict(existing_manifest.params_snapshot),
                        created_at=str(existing_manifest.run.get("created_at", "")),
                    ),
                    warnings=(
                        "Equivalent completed Run reused by scientific_hash: "
                        f"{existing_id}; use purpose=reproduce for an intentional "
                        "independent execution.",
                    ),
                    reused=True,
                )
            write_manifest(
                staging_run_dir,
                manifest,
                event_path=final_run_dir / "manifest.toml",
                log_event=False,
            )
            if commit_guard is not None:
                commit_guard()
            # The initial destination check can become stale while inputs are
            # rendered.  Revalidate under the namespace guard at the actual
            # publication boundary so a newly published ancestor Run cannot
            # turn this Run into undiscoverable nested payload.
            require_formal_run_target(project.root_dir, parent_dir)
            existing_id_paths = list(parent_dir.glob(f"{run_id}*"))
            if existing_id_paths or final_run_dir.exists():
                raise _RunIdCollisionError(run_id)
            try:
                commit_staged_directory(staging_run_dir, final_run_dir)
            except FileExistsError as exc:
                raise _RunIdCollisionError(run_id) from exc
            if commit_guard is not None:
                try:
                    # Close the check/publication race: a source edit after the
                    # pre-commit CAS is detected while the just-published Run
                    # still has an unambiguous rollback path.
                    commit_guard()
                except BaseException as guard_exc:
                    try:
                        commit_staged_directory(final_run_dir, staging_run_dir)
                    except BaseException as rollback_exc:
                        committed = True
                        raise SimctlError(
                            "Run was published but its source-version CAS failed, "
                            "and automatic publication rollback also failed: "
                            f"{rollback_exc}"
                        ) from guard_exc
                    raise
            committed = True
            pending_artifacts.append(
                (
                    final_run_dir / "manifest.toml",
                    "create",
                    "manifest",
                    "Create manifest.toml",
                )
            )
            for artifact_path, operation, artifact_kind, summary in pending_artifacts:
                emit_artifact_event(
                    artifact_path,
                    operation=operation,
                    artifact_kind=artifact_kind,
                    summary=summary,
                )
        except _RunIdCollisionError as exc:
            known_ids.add(exc.run_id)
            if reserved_run_id:
                raise DuplicateRunIdError(
                    exc.run_id,
                    [str(path) for path in parent_dir.glob(f"{exc.run_id}*")],
                ) from exc
            continue
        finally:
            if not committed and staging_run_dir.exists():
                shutil.rmtree(staging_run_dir, ignore_errors=True)

        known_ids.add(final_run_info.run_id)
        return CreatedRunResult(run_info=final_run_info, warnings=tuple(warnings))

    raise SimctlError(
        f"Could not allocate a free run_id after {_RUN_ID_ALLOCATION_ATTEMPTS} attempts"
    )


def finalize_manifest_metadata(
    manifest: ManifestData,
    staging_run_dir: Path,
    metadata: dict[str, dict[str, Any]] | None,
    *,
    site: SiteProfile | None = None,
) -> None:
    """Freeze identity, curation, and storage at a Run commit boundary."""
    provided = metadata or {}
    identity_metadata = provided.get("identity", {})
    if not isinstance(identity_metadata, dict):
        raise SimctlError("manifest identity metadata must be a table")
    unsupported_identity = set(identity_metadata) - _CALLER_IDENTITY_FIELDS
    if unsupported_identity:
        fields = ", ".join(sorted(unsupported_identity))
        raise SimctlError(
            f"caller metadata cannot override derived identity fields: {fields}"
        )
    manifest.origin.update(provided.get("origin", {}))
    manifest.variation.update(provided.get("variation", {}))
    manifest.intent.update(
        {
            key: value
            for key, value in provided.get("intent", {}).items()
            if value not in (None, "")
        }
    )
    if site is not None:
        manifest.launcher["site"] = _build_site_execution_context(
            site,
            str(manifest.simulator.get("name", "")),
        )
    scientific_identity = _compute_scientific_identity(
        manifest,
        staging_run_dir / "input",
    )
    scientific_hash = scientific_identity["scientific_hash"]
    manifest.identity.update(
        {
            **scientific_identity,
            "execution_hash": _compute_execution_hash(manifest, scientific_hash),
        }
    )
    manifest.identity.update(identity_metadata)
    # A Run can only become reviewed through the terminal-Run review workflow.
    # Case/caller metadata must not pre-authorize a Run before it has executed.
    manifest.curation = {
        "review_status": "unreviewed",
        "reviewed_at": "",
        "reviewed_by": "",
        "reason": "",
    }
    manifest.storage.update({"tier": "hot", "form": "full"})
    manifest.storage.update(provided.get("storage", {}))


def _compute_scientific_identity(
    manifest: ManifestData,
    input_dir: Path,
) -> dict[str, str]:
    condition_hash = canonical_data_hash(manifest.params_snapshot)
    input_hash = directory_content_hash(input_dir)
    provenance_hash = canonical_data_hash(
        _canonical_provenance(manifest.simulator_source)
    )
    scientific_hash = _scientific_hash_from_components(
        manifest,
        condition_hash=condition_hash,
        input_hash=input_hash,
        provenance_hash=provenance_hash,
    )
    return {
        "condition_hash": condition_hash,
        "input_hash": input_hash,
        "provenance_hash": provenance_hash,
        "scientific_hash": scientific_hash,
    }


def _scientific_hash_from_components(
    manifest: ManifestData,
    *,
    condition_hash: str,
    input_hash: str,
    provenance_hash: str,
) -> str:
    return canonical_data_hash(
        {
            "condition_hash": condition_hash,
            "input_hash": input_hash,
            "provenance_hash": provenance_hash,
            "simulator": manifest.simulator,
        }
    )


def _canonical_provenance(provenance: dict[str, Any]) -> dict[str, Any]:
    """Canonicalize strong identity; retain weak locations only to avoid collision."""
    canonical = {
        key: value
        for key, value in provenance.items()
        if key not in _PROVENANCE_LOCATION_FIELDS
    }
    executable = str(provenance.get("executable", "")).strip()
    if executable and not str(provenance.get("exe_hash", "")).strip():
        # A basename is not evidence that two unresolved executables are the
        # same binary.  Keep the full observed path only as a discriminator;
        # weak provenance is never eligible for hard reuse below.
        canonical["unverified_executable"] = executable
    source_repo = str(provenance.get("source_repo", "")).strip()
    if source_repo and not str(provenance.get("git_commit", "")).strip():
        canonical["unverified_source_repo"] = source_repo
    return canonical


def _compute_execution_hash(manifest: ManifestData, scientific_hash: str) -> str:
    launcher = {
        key: value
        for key, value in manifest.launcher.items()
        if key in {"name", "config", "site"}
    }
    job = {
        key: value
        for key, value in manifest.job.items()
        if key in _EXECUTION_JOB_FIELDS
    }
    return canonical_data_hash(
        {
            "scientific_hash": scientific_hash,
            "launcher": launcher,
            "job": job,
        }
    )


def find_equivalent_completed_run(
    project_root: Path,
    candidate: ManifestData,
) -> tuple[Path, ManifestData] | None:
    """Return a reusable duplicate without losing Experiment/Survey ownership.

    An equivalent Run owned by a different Experiment or Survey is evidence,
    not a materialization of the new owner.  Silently returning it would leave
    no durable edge for the requested point, so fail closed and ask callers to
    reference it explicitly.  ``reproduce`` and ``validate`` intentionally
    allow an independent execution.
    """
    if allows_equivalent_execution(str(candidate.intent.get("purpose", ""))):
        return None
    scientific_hash = str(candidate.identity.get("scientific_hash", "")).strip()
    if not scientific_hash:
        return None
    if not _has_strong_reuse_provenance(candidate):
        return None
    if not _candidate_scientific_identity_is_consistent(candidate):
        raise SimctlError("candidate scientific identity is internally inconsistent")
    foreign: list[str] = []
    for run_dir in discover_runs(project_root / "runs"):
        try:
            manifest = read_manifest(run_dir)
        except SimctlError:
            continue
        if manifest.run.get("status") not in {"completed", "archived", "purged"}:
            continue
        if manifest.identity.get("scientific_hash") != scientific_hash:
            continue
        if not materialized_scientific_identity_is_valid(run_dir, manifest):
            continue
        if _same_reuse_owner(candidate, manifest):
            return run_dir, manifest
        foreign.append(str(manifest.run.get("id", run_dir.name)))
    if foreign:
        raise SimctlError(
            "Equivalent completed Run exists under a different Experiment/Survey "
            f"owner ({', '.join(sorted(foreign))}); reference it as baseline or "
            "Result evidence, or use purpose=reproduce/validate for an intentional "
            "independent execution"
        )
    return None


def _candidate_scientific_identity_is_consistent(manifest: ManifestData) -> bool:
    condition_hash = str(manifest.identity.get("condition_hash", ""))
    input_hash = str(manifest.identity.get("input_hash", ""))
    provenance_hash = str(manifest.identity.get("provenance_hash", ""))
    scientific_hash = str(manifest.identity.get("scientific_hash", ""))
    if not all(
        _is_canonical_sha256(value)
        for value in (condition_hash, input_hash, provenance_hash, scientific_hash)
    ):
        return False
    return (
        condition_hash == canonical_data_hash(manifest.params_snapshot)
        and provenance_hash
        == canonical_data_hash(_canonical_provenance(manifest.simulator_source))
        and scientific_hash
        == _scientific_hash_from_components(
            manifest,
            condition_hash=condition_hash,
            input_hash=input_hash,
            provenance_hash=provenance_hash,
        )
    )


def materialized_scientific_identity_is_valid(
    run_dir: Path,
    manifest: ManifestData,
) -> bool:
    if not _has_strong_reuse_provenance(manifest):
        return False
    return materialized_point_identity_is_valid(run_dir, manifest)


def materialized_point_identity_is_valid(
    run_dir: Path,
    manifest: ManifestData,
) -> bool:
    """Validate one already-owned materialization without inferring equivalence.

    Exact ``survey.id + point_id + plan_hash`` retries return the same Run, so
    they do not use weak provenance to equate two different executions.  They
    still re-hash the frozen parameters, input tree, and recorded provenance
    to detect mutation before treating the operation as idempotent.
    """
    input_dir = run_dir / "input"
    try:
        input_metadata = input_dir.lstat()
    except OSError:
        return False
    if not stat.S_ISDIR(input_metadata.st_mode) or stat.S_ISLNK(input_metadata.st_mode):
        return False
    try:
        actual = _compute_scientific_identity(manifest, input_dir)
    except SimctlError:
        return False
    return all(manifest.identity.get(key) == value for key, value in actual.items())


def _has_strong_reuse_provenance(manifest: ManifestData) -> bool:
    """Require content-addressed code provenance before exact reuse.

    Runtime resolution may legitimately defer an executable to a compute node.
    Such a Run can still be materialized, but a path or basename cannot prove
    scientific equivalence.  Local-source builds additionally need a clean,
    identified source revision whose commit and dirty state were both
    successfully observed.  A default ``git_dirty = false`` cannot prove that
    a failed Git query saw a clean tree.
    """
    provenance = manifest.simulator_source
    if not _is_canonical_sha256(str(provenance.get("exe_hash", "")).strip()):
        return False
    source_mode = str(provenance.get("resolver_mode", "")).strip()
    simulator_mode = str(manifest.simulator.get("resolver_mode", "")).strip()
    if source_mode and simulator_mode and source_mode != simulator_mode:
        return False
    resolver_mode = source_mode or simulator_mode
    if resolver_mode not in {"local_executable", "local_source", "package"}:
        return False
    if resolver_mode == "local_source":
        git_commit = provenance.get("git_commit")
        return (
            isinstance(git_commit, str)
            and bool(git_commit.strip())
            and provenance.get("git_state_observed") is True
            and provenance.get("git_dirty") is False
        )
    return True


def _is_canonical_sha256(value: str) -> bool:
    if len(value) != 71 or not value.startswith("sha256:"):
        return False
    return all(character in "0123456789abcdef" for character in value[7:])


def _same_reuse_owner(candidate: ManifestData, existing: ManifestData) -> bool:
    """Return whether scientific reuse preserves durable ownership identity."""
    candidate_experiment = str(candidate.intent.get("experiment_id", ""))
    existing_experiment = str(existing.intent.get("experiment_id", ""))
    if candidate_experiment != existing_experiment:
        return False
    candidate_survey = str(candidate.intent.get("survey_id", ""))
    existing_survey = str(existing.intent.get("survey_id", ""))
    if candidate_survey != existing_survey:
        return False
    if candidate_survey:
        return candidate.identity.get("point_id") == existing.identity.get("point_id")
    return True


def allows_equivalent_execution(purpose: str) -> bool:
    """Allow an intentional independent execution of a scientific duplicate."""
    return purpose in {"reproduce", "validate"}


def directory_content_hash(root: Path) -> str:
    """Hash a closed tree of single-link regular files without following links.

    Formal Run inputs are immutable scientific evidence.  Hashing a symlink's
    target text (or silently ignoring a FIFO/socket) would let mutable external
    state escape the committed identity, so every non-directory entry must be a
    single-link regular file and is opened with ``O_NOFOLLOW``.
    """
    digest = hashlib.sha256()
    try:
        root_stat = os.stat(root, follow_symlinks=False)
    except FileNotFoundError:
        return f"sha256:{digest.hexdigest()}"
    except OSError as exc:
        raise SimctlError(f"cannot inspect input snapshot {root}: {exc}") from exc
    if not stat.S_ISDIR(root_stat.st_mode):
        raise SimctlError(
            f"input snapshot must be a regular non-symlink directory: {root}"
        )

    directory_flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_DIRECTORY

    def scan_names(directory_fd: int, directory: Path) -> tuple[str, ...]:
        scan_fd = -1
        try:
            scan_fd = os.open(".", directory_flags, dir_fd=directory_fd)
            with os.scandir(scan_fd) as entries:
                return tuple(sorted(entry.name for entry in entries))
        except OSError as exc:
            raise SimctlError(
                f"cannot inspect input snapshot directory {directory}: {exc}"
            ) from exc
        finally:
            if scan_fd >= 0:
                os.close(scan_fd)

    def visit(
        directory_fd: int,
        directory: Path,
        relative_parts: tuple[str, ...],
        expected: os.stat_result,
        *,
        parent_fd: int | None,
        entry_name: str,
    ) -> None:
        opened_directory = os.fstat(directory_fd)
        if not stat.S_ISDIR(opened_directory.st_mode) or _filesystem_identity(
            opened_directory
        ) != _filesystem_identity(expected):
            raise SimctlError(
                f"input snapshot directory changed while being opened: {directory}"
            )
        initial_names = scan_names(directory_fd, directory)
        for name in initial_names:
            path = directory / name
            try:
                before = os.stat(
                    name,
                    dir_fd=directory_fd,
                    follow_symlinks=False,
                )
            except OSError as exc:
                raise SimctlError(
                    f"cannot inspect input snapshot entry {path}: {exc}"
                ) from exc
            if stat.S_ISLNK(before.st_mode):
                raise SimctlError(
                    f"input snapshot must not contain symbolic links: {path}"
                )
            if stat.S_ISDIR(before.st_mode):
                relative = "/".join((*relative_parts, name)).encode("utf-8")
                digest.update(len(relative).to_bytes(8, "big"))
                digest.update(relative)
                digest.update(b"D")
                child_fd = -1
                try:
                    child_fd = os.open(name, directory_flags, dir_fd=directory_fd)
                    visit(
                        child_fd,
                        path,
                        (*relative_parts, name),
                        before,
                        parent_fd=directory_fd,
                        entry_name=name,
                    )
                except OSError as exc:
                    raise SimctlError(
                        f"cannot safely hash input snapshot directory {path}: {exc}"
                    ) from exc
                finally:
                    if child_fd >= 0:
                        os.close(child_fd)
                continue
            if not stat.S_ISREG(before.st_mode):
                raise SimctlError(
                    f"input snapshot must contain only regular files: {path}"
                )
            if before.st_nlink != 1:
                raise SimctlError(
                    f"input snapshot files must be single-link regular files: {path}"
                )

            relative = "/".join((*relative_parts, name)).encode("utf-8")
            flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
            descriptor = -1
            try:
                descriptor = os.open(name, flags, dir_fd=directory_fd)
                opened = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(opened.st_mode)
                    or opened.st_nlink != 1
                    or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
                ):
                    raise SimctlError(
                        f"input snapshot entry changed while being opened: {path}"
                    )
                digest.update(len(relative).to_bytes(8, "big"))
                digest.update(relative)
                digest.update(b"F")
                while chunk := os.read(descriptor, 1024 * 1024):
                    digest.update(chunk)
                after = os.fstat(descriptor)
                after_path = os.stat(
                    name,
                    dir_fd=directory_fd,
                    follow_symlinks=False,
                )
                if _file_snapshot(after) != _file_snapshot(opened) or _file_snapshot(
                    after_path
                ) != _file_snapshot(after):
                    raise SimctlError(
                        f"input snapshot entry changed while being hashed: {path}"
                    )
            except OSError as exc:
                raise SimctlError(
                    f"cannot safely hash input snapshot file {path}: {exc}"
                ) from exc
            finally:
                if descriptor >= 0:
                    os.close(descriptor)

        final_names = scan_names(directory_fd, directory)
        if final_names != initial_names:
            raise SimctlError(
                f"input snapshot directory entry set changed while being hashed: "
                f"{directory}"
            )
        final_directory = os.fstat(directory_fd)
        try:
            if parent_fd is None:
                final_path = os.stat(directory, follow_symlinks=False)
            else:
                final_path = os.stat(
                    entry_name,
                    dir_fd=parent_fd,
                    follow_symlinks=False,
                )
        except OSError as exc:
            raise SimctlError(
                f"input snapshot directory changed while being hashed: {directory}"
            ) from exc
        if (
            _directory_snapshot(final_directory)
            != _directory_snapshot(opened_directory)
            or _filesystem_identity(final_path) != _filesystem_identity(final_directory)
            or not stat.S_ISDIR(final_path.st_mode)
        ):
            raise SimctlError(
                f"input snapshot directory changed while being hashed: {directory}"
            )

    root_fd = -1
    try:
        root_fd = os.open(root, directory_flags)
        visit(
            root_fd,
            root,
            (),
            root_stat,
            parent_fd=None,
            entry_name="",
        )
    except OSError as exc:
        raise SimctlError(f"cannot safely hash input snapshot {root}: {exc}") from exc
    finally:
        if root_fd >= 0:
            os.close(root_fd)
    return f"sha256:{digest.hexdigest()}"


def _filesystem_identity(metadata: os.stat_result) -> tuple[int, int]:
    return metadata.st_dev, metadata.st_ino


def _file_snapshot(metadata: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_nlink,
    )


def _directory_snapshot(
    metadata: os.stat_result,
) -> tuple[int, int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
        metadata.st_nlink,
    )


def create_case_run(
    project: ProjectConfig,
    case_name: str,
    *,
    dest_dir: Path | None = None,
    display_name: str = "",
    params: dict[str, Any] | None = None,
    experiment_id: str = "",
    purpose: str = "",
    created_by: str = "human",
    parent_run_id: str = "",
    changed_keys: tuple[str, ...] = (),
) -> CreatedRunResult:
    """Resolve a case and create one run."""
    case_dir = resolve_case(case_name, project.root_dir)
    case_data = load_case(case_dir)
    validate_case_references(project, case_data)

    adapter = load_adapter_for_simulator(project, case_data.simulator)
    launcher = load_launcher_for_name(project, case_data.launcher)
    site = load_site_profile(project.root_dir)
    target_dir = dest_dir or (project.root_dir / "runs" / case_name)
    require_formal_run_target(project.root_dir, target_dir)
    project_file = project.root_dir / "runops.toml"
    project_is_persisted = project_file.exists() or project_file.is_symlink()
    with experiment_lock(project.root_dir), run_namespace_guard(project.root_dir):
        manifest_metadata = build_standalone_manifest_metadata(
            project,
            experiment_id=experiment_id,
            purpose=purpose,
            created_by=created_by,
        )
        if parent_run_id:
            manifest_metadata.setdefault("origin", {}).update(
                {"parent_run": parent_run_id, "survey": ""}
            )
        if changed_keys:
            manifest_metadata["variation"] = {"changed_keys": sorted(set(changed_keys))}
        expected_intent = dict(manifest_metadata.get("intent", {}))
        existing_ids = collect_existing_run_ids(project.root_dir / "runs")
        run_id = reserve_run_id(project.root_dir, existing_ids)
        reservation_token = f"run:{run_id}"
        manifest_metadata.setdefault("identity", {})["budget_reservation"] = (
            reservation_token
        )
        experiment = None
        if experiment_id.strip():
            experiment = load_experiment(
                resolve_experiment(project.root_dir, experiment_id.strip())
            )

        def commit_budget_guard() -> None:
            current_project = (
                load_project(project.root_dir) if project_is_persisted else project
            )
            current_metadata = build_standalone_manifest_metadata(
                current_project,
                experiment_id=experiment_id,
                purpose=purpose,
                created_by=created_by,
            )
            if current_metadata.get("intent", {}) != expected_intent:
                raise SimctlError(
                    "Experiment admission metadata changed while the Run was "
                    "staged; retry creation from the current Experiment definition"
                )
            if experiment is None:
                enforce_project_unreviewed_completed_budget(current_project)
                return
            current_experiment = load_experiment(
                resolve_experiment(project.root_dir, experiment.id)
            )
            if current_experiment != experiment:
                raise SimctlError(
                    f"Experiment {experiment.id} changed while the Run was staged; "
                    "retry creation from the current Experiment definition"
                )
            records = collect_experiment_run_records(
                project.root_dir,
                current_experiment.id,
            )
            published = any(
                record.manifest.run.get("id") == run_id for record in records
            )
            enforce_experiment_run_budget(
                current_project,
                current_experiment,
                new_count=0 if published else 1,
                new_core_hours=(
                    0.0 if published else declared_job_core_hours(case_data.job)
                ),
                reservation_tokens=() if published else (reservation_token,),
                records=records,
                persist=False,
            )

        target_dir.mkdir(parents=True, exist_ok=True)

        created = create_prepared_run(
            parent_dir=target_dir,
            case_data=case_data,
            project=project,
            adapter=adapter,
            launcher=launcher,
            site=site,
            params=params,
            display_name=display_name or case_data.name,
            naming=NamingConfig(),
            existing_ids=existing_ids,
            reserved_run_id=run_id,
            manifest_metadata=manifest_metadata,
            commit_guard=commit_budget_guard,
        )
        if created.reused:
            release_unused_run_id(project.root_dir, run_id)
        if experiment is not None and not created.reused:
            try:
                persist_manifest_budget_usage(
                    project.root_dir,
                    created.run_info.run_dir,
                    read_manifest(created.run_info.run_dir),
                )
            except SimctlError as exc:
                created = CreatedRunResult(
                    run_info=created.run_info,
                    warnings=(
                        *created.warnings,
                        "Run committed; Experiment usage ledger will be rebuilt "
                        f"from its manifest ({exc})",
                    ),
                    reused=created.reused,
                )
        return created


def require_formal_run_target(project_root: Path, target_dir: Path) -> None:
    runs_root = (project_root / "runs").resolve()
    target = target_dir.resolve()
    try:
        relative = target.relative_to(runs_root)
    except ValueError as exc:
        raise SimctlError(
            f"formal Run destination must be inside project runs/: {target}"
        ) from exc
    hidden_components = tuple(
        component
        for component in relative.parts
        if component.startswith((".tmp-", ".delete-"))
    )
    if hidden_components:
        raise SimctlError(
            "formal Run destination must not be inside a transaction directory "
            "pruned from strict discovery: " + "/".join(hidden_components)
        )
    current = target
    while True:
        if current.name == "_archive" or (current / ".runops-archive.toml").exists():
            raise SimctlError(
                f"formal Run destination must be in the active runs view: {target}"
            )
        manifest_path = current / "manifest.toml"
        try:
            manifest_path.lstat()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise SimctlError(
                f"cannot verify formal Run destination ancestor {manifest_path}: {exc}"
            ) from exc
        else:
            raise SimctlError(
                "formal Run destination must not be inside existing formal Run "
                f"at {current}: {target}"
            )
        if current == runs_root:
            break
        current = current.parent


def build_standalone_manifest_metadata(
    project: ProjectConfig,
    *,
    experiment_id: str,
    purpose: str,
    created_by: str,
    now: datetime | None = None,
) -> dict[str, dict[str, Any]]:
    """Validate and freeze intent for a non-Survey formal Run."""
    clean_experiment = experiment_id.strip()
    clean_purpose = purpose.strip()
    if project.experiment_policy.require_experiment and not clean_experiment:
        raise SimctlError(
            "project policy requires --experiment for formal Runs; use "
            "`runo test smoke` for ephemeral verification"
        )
    if not clean_experiment:
        if clean_purpose and clean_purpose not in {
            "explore",
            "confirm",
            "validate",
            "reproduce",
        }:
            raise SimctlError(f"invalid Run purpose: {clean_purpose!r}")
        return {
            "intent": {
                "purpose": clean_purpose,
                "created_by": created_by.strip() or "human",
            }
        }

    experiments = discover_experiments(project.root_dir)
    active_count = sum(item.lifecycle == "active" for item in experiments)
    if active_count > project.experiment_policy.max_active_experiments:
        raise SimctlError(
            "active Experiment WIP limit is exceeded: "
            f"{active_count}/{project.experiment_policy.max_active_experiments}; "
            "close an Experiment before creating formal Runs"
        )
    matches = [item for item in experiments if item.id == clean_experiment]
    if len(matches) != 1:
        raise SimctlError(
            f"Experiment {clean_experiment!r} was not found uniquely in the project"
        )
    experiment = matches[0]
    if experiment.lifecycle != "active":
        raise SimctlError(
            f"Experiment {experiment.id} is {experiment.lifecycle!r}; expected 'active'"
        )
    if experiment_is_expired(experiment, now=now):
        raise SimctlError(
            f"Experiment {experiment.id} expired at {experiment.budget.expires_at}; "
            "review and close it or admit a successor before creating formal Runs"
        )
    if experiment.decision not in {"pending", "expand"}:
        raise SimctlError(
            f"Experiment {experiment.id} decision={experiment.decision!r} blocks "
            "new formal Runs; review it back to expand or open a successor"
        )
    if not clean_purpose:
        clean_purpose = experiment.intent
    if clean_purpose != experiment.intent:
        raise SimctlError(
            f"Run purpose {clean_purpose!r} does not match Experiment intent "
            f"{experiment.intent!r}"
        )
    for baseline_id in experiment.baseline.run_ids:
        try:
            _baseline_dir, baseline_manifest = resolve_project_run_strict(
                project.root_dir,
                baseline_id,
            )
            baseline_status = str(baseline_manifest.run.get("status", ""))
        except SimctlError as exc:
            raise SimctlError(
                f"Experiment baseline Run {baseline_id} is not resolvable: {exc}"
            ) from exc
        if baseline_status not in {"completed", "archived", "purged"}:
            raise SimctlError(
                f"Experiment baseline Run {baseline_id} is not "
                f"completed-equivalent: {baseline_status!r}"
            )
    return {
        "intent": {
            "experiment_id": experiment.id,
            "purpose": clean_purpose,
            "created_by": created_by.strip() or "human",
            "baseline_run": (
                experiment.baseline.run_ids[0] if experiment.baseline.run_ids else ""
            ),
            "baseline_runs": list(experiment.baseline.run_ids),
            "baseline_reason": experiment.baseline.reason,
        }
    }


def create_survey_runs(
    project: ProjectConfig,
    survey_dir: Path,
) -> list[CreatedRunResult]:
    """Reject the legacy unbounded expansion API.

    Use ``materialize_survey_points`` with an expected plan hash and explicit
    point selection.  Keeping this fail-closed shim prevents old agent code
    from silently recreating the directory-proliferation behavior.
    """
    del project, survey_dir
    raise SimctlError(
        "create_survey_runs() no longer expands every candidate; use "
        "preview_survey_plan() then materialize_survey_points()"
    )
