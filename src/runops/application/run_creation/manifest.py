"""Manifest and job config helpers for run creation."""

from __future__ import annotations

from typing import Any

from runops.adapters.base import SimulatorAdapter
from runops.core.case import CaseData, JobData
from runops.core.manifest import ManifestData
from runops.core.project import ProjectConfig
from runops.core.run import RunInfo
from runops.core.site import SiteProfile

_SIMULATOR_SOURCE_STRING_FIELDS = (
    "resolver_mode",
    "source_repo",
    "git_commit",
    "build_command",
    "executable",
    "exe_hash",
    "package_version",
)

_OUTPUT_ONLY_LAUNCHER_FIELDS = frozenset({"stdout", "stderr"})
_OUTPUT_ONLY_SBATCH_PREFIXES = (
    "-o",
    "-e",
    "-J",
    "--output",
    "--error",
    "--job-name",
)


def get_simulator_config(
    project: ProjectConfig,
    simulator_name: str,
) -> dict[str, Any]:
    return dict(project.simulators.get(simulator_name, {}))


def is_rsc_site(site: SiteProfile | None) -> bool:
    """Return True when the active site emits ``--rsc`` directives."""
    return site is not None and site.resource_style == "rsc"


def build_job_config(
    job: JobData,
    site: SiteProfile | None,
) -> dict[str, Any]:
    """Translate JobData into the dict consumed by ``_render_script``."""
    config: dict[str, Any] = {
        "partition": job.partition,
        "walltime": job.walltime,
    }
    if job.qos:
        config["qos"] = job.qos
    if is_rsc_site(site):
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


def build_manifest_job(
    job: JobData,
    site: SiteProfile | None,
) -> dict[str, Any]:
    """Build the [job] section recorded in ``manifest.toml``."""
    result: dict[str, Any] = {
        "scheduler": "slurm",
        "job_id": "",
        "partition": job.partition,
        "walltime": job.walltime,
        "submitted_at": "",
    }
    if is_rsc_site(site):
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
    if job.qos:
        result["qos"] = job.qos
    if job.modules:
        result["modules"] = list(job.modules)
    if job.pre_commands:
        result["pre_commands"] = list(job.pre_commands)
    if job.post_commands:
        result["post_commands"] = list(job.post_commands)
    return result


def build_manifest(
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
    sim_config = get_simulator_config(project, case_data.simulator)
    provenance = _normalize_simulator_source(
        runtime_info,
        adapter.collect_provenance(runtime_info),
    )

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
        launcher=_build_manifest_launcher(
            project,
            case_data.launcher,
            site,
            case_data.simulator,
        ),
        simulator_source=provenance,
        job=build_manifest_job(case_data.job, site),
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


def _build_manifest_launcher(
    project: ProjectConfig,
    launcher_name: str,
    site: SiteProfile | None,
    simulator_name: str,
) -> dict[str, Any]:
    """Freeze path-independent launcher and site execution conditions."""
    launcher: dict[str, Any] = {"name": launcher_name}
    raw_config = project.launchers.get(launcher_name, {})
    config = {
        key: value
        for key, value in raw_config.items()
        if key not in _OUTPUT_ONLY_LAUNCHER_FIELDS
    }
    if config:
        launcher["config"] = config
    if site is not None:
        launcher["site"] = _build_site_execution_context(site, simulator_name)
    return launcher


def _build_site_execution_context(
    site: SiteProfile,
    simulator_name: str,
) -> dict[str, Any]:
    """Return site settings that can affect execution, excluding log paths."""
    return {
        "name": site.name,
        "resource_style": site.resource_style,
        "modules": site.modules_for(simulator_name),
        "extra_sbatch": [
            directive
            for directive in site.extra_sbatch
            if not _is_output_only_sbatch_directive(directive)
        ],
        "env": dict(site.env),
        "setup_commands": list(site.setup_commands),
    }


def _is_output_only_sbatch_directive(directive: str) -> bool:
    stripped = directive.lstrip()
    return any(
        stripped == prefix
        or stripped.startswith(f"{prefix}=")
        or stripped.startswith(f"{prefix} ")
        for prefix in _OUTPUT_ONLY_SBATCH_PREFIXES
    )


def _normalize_simulator_source(
    runtime_info: dict[str, Any],
    provenance: dict[str, Any],
) -> dict[str, Any]:
    """Return the stable canonical ``[simulator_source]`` shape."""
    source: dict[str, Any] = {
        "resolver_mode": runtime_info.get("resolver_mode", ""),
        "source_repo": runtime_info.get("source_repo", ""),
        "git_commit": runtime_info.get("git_commit", ""),
        "git_dirty": runtime_info.get("git_dirty", False),
        "git_state_observed": runtime_info.get("git_state_observed", False),
        "build_command": runtime_info.get("build_command", ""),
        "executable": runtime_info.get("executable", ""),
        "exe_hash": runtime_info.get("exe_hash", ""),
        "package_version": runtime_info.get("package_version", ""),
    }
    source.update(provenance)

    for field in _SIMULATOR_SOURCE_STRING_FIELDS:
        value = source[field]
        source[field] = value if isinstance(value, str) else str(value or "")
    if not isinstance(source["git_dirty"], bool):
        source["git_dirty"] = False
    if not isinstance(source["git_state_observed"], bool):
        source["git_state_observed"] = False
    return source


def merge_site_modules(
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


def rewrite_staging_paths(
    values: list[str],
    staging_run_dir: Any,
    final_run_dir: Any,
) -> list[str]:
    staging = str(staging_run_dir)
    final = str(final_run_dir)
    return [value.replace(staging, final) for value in values]
