"""Shared run creation workflows used by CLI commands and agents."""

from __future__ import annotations

import shlex
import shutil
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from runops.adapters import get as get_adapter
from runops.adapters.base import SimulatorAdapter
from runops.adapters.registry import AdapterImportError, load_from_config
from runops.core.case import (
    CaseData,
    ClassificationData,
    JobData,
    load_case,
    resolve_case,
)
from runops.core.discovery import collect_existing_run_ids
from runops.core.event_log import emit_artifact_event
from runops.core.exceptions import (
    DuplicateRunIdError,
    ParameterValidationError,
    ProjectConfigError,
)
from runops.core.manifest import ManifestData, write_manifest
from runops.core.project import ProjectConfig, find_project_root, load_project
from runops.core.run import RunInfo, create_run_directory, next_run_id
from runops.core.site import SiteProfile, load_site_profile
from runops.core.survey import (
    SurveyData,
    expand_survey,
    generate_display_name,
    load_survey,
)
from runops.jobgen.generator import generate_job_script
from runops.launchers.base import Launcher, load_launchers


@dataclass(frozen=True)
class CreatedRunResult:
    """One created run plus non-fatal validation warnings."""

    run_info: RunInfo
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class SurveyExpansionPlan:
    """Resolved survey expansion shared by dry-run and real sweep creation."""

    survey_data: SurveyData
    base_case: CaseData
    effective_case: CaseData
    combinations: tuple[dict[str, Any], ...]
    variation_keys: tuple[str, ...]


def load_project_from_path(path: Path) -> ProjectConfig:
    """Locate the project root for a path and load its configuration."""
    root = find_project_root(path)
    return load_project(root)


def load_adapter_for_simulator(
    project: ProjectConfig,
    simulator_name: str,
) -> SimulatorAdapter:
    """Instantiate the adapter referenced by a simulator entry."""
    try:
        load_from_config(project.simulators)
    except AdapterImportError as exc:
        raise ProjectConfigError(str(exc)) from exc
    sim_config = project.simulators.get(simulator_name, {})
    adapter_name = sim_config.get("adapter", simulator_name)
    try:
        adapter_cls = get_adapter(adapter_name)
    except KeyError as exc:
        raise ProjectConfigError(str(exc)) from exc
    return adapter_cls()


def load_launcher_for_name(
    project: ProjectConfig,
    launcher_name: str,
) -> Launcher:
    """Instantiate a launcher from project configuration."""
    try:
        launchers = load_launchers(project.launchers)
    except Exception as exc:
        raise ProjectConfigError(f"Error loading launchers: {exc}") from exc

    if launcher_name not in launchers:
        available = sorted(launchers.keys())
        raise ProjectConfigError(
            f"Launcher profile '{launcher_name}' not found. Available: {available}"
        )
    return launchers[launcher_name]


def validate_case_references(project: ProjectConfig, case_data: CaseData) -> None:
    """Ensure a case refers to known simulator and launcher entries."""
    if case_data.simulator not in project.simulators:
        available = ", ".join(project.simulators) or "(none)"
        raise ProjectConfigError(
            f"simulator '{case_data.simulator}' in case.toml "
            f"not found in simulators.toml. Available: {available}"
        )
    if case_data.launcher not in project.launchers:
        available = ", ".join(project.launchers) or "(none)"
        raise ProjectConfigError(
            f"launcher '{case_data.launcher}' in case.toml "
            f"not found in launchers.toml. Available: {available}"
        )


def _get_simulator_config(
    project: ProjectConfig,
    simulator_name: str,
) -> dict[str, Any]:
    return dict(project.simulators.get(simulator_name, {}))


def _is_rsc_site(site: SiteProfile | None) -> bool:
    """Return True when the active site emits ``--rsc`` directives."""
    return site is not None and site.resource_style == "rsc"


def _build_job_config(
    job: JobData,
    site: SiteProfile | None,
) -> dict[str, Any]:
    """Translate JobData into the dict consumed by ``_render_script``.

    The renderer reads ``ntasks`` / ``threads_per_process`` / ``cores_per_thread``
    in RSC mode and ``nodes`` / ``ntasks`` in standard mode.  This helper
    bridges the user-facing ``processes`` / ``threads`` / ``cores`` field names
    in ``case.toml`` to those internal names based on the active site profile.
    """
    config: dict[str, Any] = {
        "partition": job.partition,
        "walltime": job.walltime,
    }
    if job.qos:
        config["qos"] = job.qos
    if _is_rsc_site(site):
        config["ntasks"] = job.processes
        config["threads_per_process"] = job.threads
        config["cores_per_thread"] = job.cores
        if job.memory:
            config["memory"] = job.memory
        if job.gpus:
            config["gpus"] = job.gpus
    else:
        config["nodes"] = job.nodes
        config["ntasks"] = job.ntasks
    if job.modules:
        config["modules"] = list(job.modules)
    if job.pre_commands:
        config["pre_commands"] = list(job.pre_commands)
    if job.post_commands:
        config["post_commands"] = list(job.post_commands)
    return config


def _build_manifest_job(
    job: JobData,
    site: SiteProfile | None,
) -> dict[str, Any]:
    """Build the [job] section recorded in ``manifest.toml``.

    The manifest snapshot uses the user-facing field names from ``case.toml``
    (``processes`` / ``threads`` / ``cores`` for RSC sites, ``nodes`` /
    ``ntasks`` for standard Slurm sites) so that humans can read it directly.
    """
    result: dict[str, Any] = {
        "scheduler": "slurm",
        "job_id": "",
        "partition": job.partition,
        "walltime": job.walltime,
        "submitted_at": "",
    }
    if _is_rsc_site(site):
        result["processes"] = job.processes
        result["threads"] = job.threads
        result["cores"] = job.cores
        if job.memory:
            result["memory"] = job.memory
        if job.gpus:
            result["gpus"] = job.gpus
    else:
        result["nodes"] = job.nodes
        result["ntasks"] = job.ntasks
    return result


_CLASSIFICATION_OVERRIDE_FIELDS = frozenset({"model", "submodel", "tags"})
_JOB_OVERRIDE_FIELDS = frozenset(
    {
        "partition",
        "nodes",
        "ntasks",
        "walltime",
        "processes",
        "threads",
        "cores",
        "memory",
        "gpus",
        "qos",
        "modules",
        "pre_commands",
        "post_commands",
    }
)
_JOB_LIST_OVERRIDE_FIELDS = frozenset({"modules", "pre_commands", "post_commands"})


def _is_empty_scalar_override(value: Any) -> bool:
    return isinstance(value, str) and value == ""


def _present_override_fields(
    raw_section: object,
    allowed_fields: frozenset[str],
) -> set[str]:
    if not isinstance(raw_section, dict):
        return set()
    return {
        str(key)
        for key in raw_section
        if isinstance(key, str) and key in allowed_fields
    }


def _merge_classification(
    base: ClassificationData,
    override: ClassificationData,
    raw_override: object,
) -> ClassificationData:
    """Apply survey classification keys as a partial overlay."""
    fields = _present_override_fields(raw_override, _CLASSIFICATION_OVERRIDE_FIELDS)
    updates: dict[str, Any] = {}
    if "model" in fields and not _is_empty_scalar_override(override.model):
        updates["model"] = override.model
    if "submodel" in fields and not _is_empty_scalar_override(override.submodel):
        updates["submodel"] = override.submodel
    if "tags" in fields:
        updates["tags"] = list(override.tags)
    if not updates:
        return base
    return replace(base, **updates)


def _merge_job(
    base: JobData,
    override: JobData,
    raw_override: object,
) -> JobData:
    """Apply survey job keys as a partial overlay.

    ``load_survey`` fills omitted job keys with defaults, so raw TOML keys are
    the only reliable way to distinguish absent values from explicit empty or
    zero values. List fields replace the base list when the key is present.
    """
    fields = _present_override_fields(raw_override, _JOB_OVERRIDE_FIELDS)
    updates: dict[str, Any] = {}
    for field in fields:
        value = getattr(override, field)
        if field in _JOB_LIST_OVERRIDE_FIELDS and isinstance(value, list):
            value = list(value)
        elif _is_empty_scalar_override(value):
            continue
        updates[field] = value
    if not updates:
        return base
    return replace(base, **updates)


def _build_manifest(
    run_info: RunInfo,
    case_data: CaseData,
    project: ProjectConfig,
    runtime_info: dict[str, Any],
    adapter: SimulatorAdapter,
    site: SiteProfile | None,
    *,
    survey_id: str = "",
    variation_keys: list[str] | None = None,
) -> ManifestData:
    sim_config = _get_simulator_config(project, case_data.simulator)
    provenance = adapter.collect_provenance(runtime_info)

    return ManifestData(
        run={
            "id": run_info.run_id,
            "display_name": run_info.display_name,
            "status": "created",
            "created_at": run_info.created_at,
        },
        path={
            "run_dir": str(run_info.run_dir),
        },
        origin={
            "case": case_data.name,
            "survey": survey_id,
            "parent_run": "",
        },
        classification={
            "model": case_data.classification.model,
            "submodel": case_data.classification.submodel,
            "tags": list(case_data.classification.tags),
        },
        simulator={
            "name": case_data.simulator,
            "adapter": sim_config.get("adapter", ""),
            "resolver_mode": sim_config.get("resolver_mode", "package"),
        },
        launcher={
            "name": case_data.launcher,
        },
        simulator_source=provenance,
        job=_build_manifest_job(case_data.job, site),
        variation={
            "changed_keys": list(variation_keys) if variation_keys else [],
        },
        params_snapshot=dict(run_info.params),
        files={
            "input_dir": "input",
            "submit_dir": "submit",
            "work_dir": "work",
            "analysis_dir": "analysis",
            "status_dir": "status",
        },
    )


def _copy_case_files(case_dir: Path, input_dir: Path) -> list[str]:
    src_dir = case_dir / "input"
    if not src_dir.is_dir():
        return []
    input_dir.mkdir(parents=True, exist_ok=True)
    created: list[str] = []
    for src in src_dir.rglob("*"):
        if not src.is_file():
            continue
        rel = src.relative_to(src_dir)
        dest = input_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        created.append(str(Path("input") / rel))
    return created


def _merge_site_modules(
    site: SiteProfile,
    simulator_name: str,
    sim_config: dict[str, Any],
) -> SiteProfile:
    sim_extra_modules = list(sim_config.get("modules", []))
    if not sim_extra_modules:
        return site

    merged_sim_modules = dict(site.simulator_modules)
    existing = list(merged_sim_modules.get(simulator_name, []))
    for module in sim_extra_modules:
        if module not in existing:
            existing.append(module)
    merged_sim_modules[simulator_name] = existing
    return SiteProfile(
        name=site.name,
        resource_style=site.resource_style,
        modules=list(site.modules),
        simulator_modules=merged_sim_modules,
        stdout_format=site.stdout_format,
        stderr_format=site.stderr_format,
        extra_sbatch=list(site.extra_sbatch),
        env=dict(site.env),
        setup_commands=list(site.setup_commands),
    )


def _rewrite_staging_paths(
    values: list[str],
    staging_run_dir: Path,
    final_run_dir: Path,
) -> list[str]:
    staging = str(staging_run_dir)
    final = str(final_run_dir)
    return [value.replace(staging, final) for value in values]


def plan_survey_runs(
    project: ProjectConfig,
    survey_dir: Path,
) -> SurveyExpansionPlan:
    """Resolve a survey into the exact run plan used by sweep creation.

    Args:
        project: Loaded project configuration.
        survey_dir: Directory containing ``survey.toml``.

    Returns:
        Resolved survey data, merged case metadata/job settings, parameter
        combinations, and variation keys.
    """
    survey_data = load_survey(survey_dir)
    case_dir = resolve_case(survey_data.base_case, project.root_dir)
    case_data = load_case(case_dir)

    simulator_name = survey_data.simulator or case_data.simulator
    launcher_name = survey_data.launcher or case_data.launcher
    effective_case = CaseData(
        name=case_data.name,
        simulator=simulator_name,
        launcher=launcher_name,
        description=case_data.description,
        classification=_merge_classification(
            case_data.classification,
            survey_data.classification,
            survey_data.raw.get("classification", {}),
        ),
        job=_merge_job(
            case_data.job,
            survey_data.job,
            survey_data.raw.get("job", {}),
        ),
        params=case_data.params,
        case_dir=case_data.case_dir,
        raw=case_data.raw,
    )
    validate_case_references(project, effective_case)

    combinations = tuple(expand_survey(survey_data.axes, survey_data.linked))
    variation_keys = list(survey_data.axes.keys())
    for group in survey_data.linked:
        variation_keys.extend(group.keys())

    return SurveyExpansionPlan(
        survey_data=survey_data,
        base_case=case_data,
        effective_case=effective_case,
        combinations=combinations,
        variation_keys=tuple(variation_keys),
    )


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
    survey_id: str = "",
    variation_keys: list[str] | None = None,
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

    warnings = tuple(i.message for i in issues if i.severity == "warning")
    errors = [i for i in issues if i.severity == "error"]
    if errors:
        raise ParameterValidationError(issues)

    known_ids = existing_ids
    if known_ids is None:
        known_ids = collect_existing_run_ids(project.root_dir / "runs")

    run_id = next_run_id(known_ids)
    final_run_dir = (parent_dir / run_id).resolve()
    if final_run_dir.exists():
        raise DuplicateRunIdError(run_id, [str(final_run_dir)])

    staging_name = f".tmp-{run_id}-{uuid4().hex}"
    staging_run_dir = create_run_directory(parent_dir, staging_name)
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
    try:
        copied_inputs = _copy_case_files(case_data.case_dir, staging_run_dir / "input")
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
        venv_activate = project.root_dir / ".venv" / "bin" / "activate"
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
        write_manifest(
            staging_run_dir,
            manifest,
            event_path=final_run_dir / "manifest.toml",
            log_event=False,
        )
        if final_run_dir.exists():
            raise DuplicateRunIdError(run_id, [str(final_run_dir)])
        staging_run_dir.rename(final_run_dir)
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
    finally:
        if not committed and staging_run_dir.exists():
            shutil.rmtree(staging_run_dir, ignore_errors=True)

    known_ids.add(final_run_info.run_id)
    return CreatedRunResult(run_info=final_run_info, warnings=warnings)


@dataclass(frozen=True)
class RegenerateResult:
    """File-level diff of a ``regenerate_run`` call."""

    run_id: str
    case_name: str
    added: tuple[str, ...]
    modified: tuple[str, ...]
    removed: tuple[str, ...]
    unchanged: tuple[str, ...]
    work_exists: bool

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.modified or self.removed)


_REGENERATE_ALLOWED_STATES = frozenset({"created", "failed", "cancelled"})


def regenerate_run(
    project: ProjectConfig,
    run_dir: Path,
    *,
    dry_run: bool = False,
) -> RegenerateResult:
    """Re-render ``input/`` for an existing run from its recorded case.

    Preserves ``run_id``, ``manifest.toml``, and ``analysis/`` while
    regenerating ``input/`` via the adapter so changes to the case template
    (or survey-level param overrides) take effect on an already-created run.

    Only safe states (``created``, ``failed``, ``cancelled``) are accepted —
    regenerating a submitted / running run would desynchronise the job from
    its inputs. If ``work/`` already exists the caller should treat the
    returned ``work_exists`` flag as a warning: the stale outputs may no
    longer correspond to the new inputs.
    """
    from runops.core.manifest import read_manifest

    manifest = read_manifest(run_dir)
    run_id = str(manifest.run.get("id", run_dir.name))
    state = str(manifest.run.get("status", ""))
    if state not in _REGENERATE_ALLOWED_STATES:
        raise ProjectConfigError(
            f"cannot regenerate run in state '{state}': "
            f"expected one of {sorted(_REGENERATE_ALLOWED_STATES)}"
        )

    case_name = str(manifest.origin.get("case", "")) if manifest.origin else ""
    if not case_name:
        raise ProjectConfigError(
            f"run {run_id} has no origin.case recorded; cannot regenerate"
        )

    simulator_name = (
        str(manifest.simulator.get("name", "")) if manifest.simulator else ""
    )
    if not simulator_name:
        raise ProjectConfigError(
            f"run {run_id} has no simulator.name recorded; cannot regenerate"
        )

    case_dir = resolve_case(case_name, project.root_dir)
    case_data = load_case(case_dir)
    adapter = load_adapter_for_simulator(project, simulator_name)

    effective_params = dict(case_data.params)
    if manifest.params_snapshot:
        effective_params.update(manifest.params_snapshot)

    case_section = {
        **case_data.raw.get("case", {}),
        "case_dir": str(case_data.case_dir),
    }
    validation_data = {"case": case_section, "params": effective_params}

    input_dir = run_dir / "input"
    work_exists = (run_dir / "work").is_dir() and any((run_dir / "work").iterdir())

    # Stage the new inputs in a run_dir-like layout (<tmp>/input/) so the
    # adapter's render_inputs sees the same relative structure it does during
    # create_prepared_run. This lets us compute a precise diff before touching
    # the live input/.
    import tempfile

    with tempfile.TemporaryDirectory(prefix="runops-regen-") as staging_root:
        staged_run = Path(staging_root)
        (staged_run / "input").mkdir()
        _copy_case_files(case_data.case_dir, staged_run / "input")
        adapter.render_inputs(validation_data, staged_run)

        staged_input = staged_run / "input"
        old_files: dict[str, bytes] = {}
        if input_dir.is_dir():
            for path in input_dir.rglob("*"):
                if path.is_file():
                    rel = str(path.relative_to(input_dir)).replace("\\", "/")
                    old_files[rel] = path.read_bytes()

        new_files: dict[str, bytes] = {}
        for path in staged_input.rglob("*"):
            if path.is_file():
                rel = str(path.relative_to(staged_input)).replace("\\", "/")
                new_files[rel] = path.read_bytes()

        added = tuple(sorted(set(new_files) - set(old_files)))
        removed = tuple(sorted(set(old_files) - set(new_files)))
        common = set(new_files) & set(old_files)
        modified = tuple(sorted(p for p in common if new_files[p] != old_files[p]))
        unchanged = tuple(sorted(p for p in common if new_files[p] == old_files[p]))

        if dry_run:
            return RegenerateResult(
                run_id=run_id,
                case_name=case_name,
                added=added,
                modified=modified,
                removed=removed,
                unchanged=unchanged,
                work_exists=work_exists,
            )

        # Apply: replace input/ with staged contents.
        if input_dir.is_dir():
            shutil.rmtree(input_dir)
        shutil.copytree(staged_input, input_dir)

    return RegenerateResult(
        run_id=run_id,
        case_name=case_name,
        added=added,
        modified=modified,
        removed=removed,
        unchanged=unchanged,
        work_exists=work_exists,
    )


def create_case_run(
    project: ProjectConfig,
    case_name: str,
    *,
    dest_dir: Path | None = None,
    display_name: str = "",
    params: dict[str, Any] | None = None,
) -> CreatedRunResult:
    """Resolve a case and create one run."""
    case_dir = resolve_case(case_name, project.root_dir)
    case_data = load_case(case_dir)
    validate_case_references(project, case_data)

    adapter = load_adapter_for_simulator(project, case_data.simulator)
    launcher = load_launcher_for_name(project, case_data.launcher)
    site = load_site_profile(project.root_dir)
    target_dir = dest_dir or (project.root_dir / "runs" / case_name)
    target_dir.mkdir(parents=True, exist_ok=True)

    return create_prepared_run(
        parent_dir=target_dir,
        case_data=case_data,
        project=project,
        adapter=adapter,
        launcher=launcher,
        site=site,
        params=params,
        display_name=display_name or case_data.name,
        existing_ids=collect_existing_run_ids(project.root_dir / "runs"),
    )


def create_survey_runs(
    project: ProjectConfig,
    survey_dir: Path,
) -> list[CreatedRunResult]:
    """Expand a survey and create all runs declared by it."""
    plan = plan_survey_runs(project, survey_dir)
    if not plan.combinations:
        return []

    adapter = load_adapter_for_simulator(project, plan.effective_case.simulator)
    launcher = load_launcher_for_name(project, plan.effective_case.launcher)
    site = load_site_profile(project.root_dir)

    existing_ids = collect_existing_run_ids(project.root_dir / "runs")
    results: list[CreatedRunResult] = []
    for combo in plan.combinations:
        merged_params = {**plan.base_case.params, **combo}
        display_name = generate_display_name(
            plan.survey_data.naming_template,
            merged_params,
        )
        results.append(
            create_prepared_run(
                parent_dir=survey_dir,
                case_data=plan.effective_case,
                project=project,
                adapter=adapter,
                launcher=launcher,
                site=site,
                existing_ids=existing_ids,
                params=merged_params,
                display_name=display_name,
                survey_id=plan.survey_data.id,
                variation_keys=list(plan.variation_keys),
            )
        )
    return results
