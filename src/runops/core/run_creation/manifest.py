"""Manifest and job config helpers for run creation."""

from __future__ import annotations

from typing import Any

from runops.adapters.base import SimulatorAdapter
from runops.core.case import CaseData, JobData
from runops.core.manifest import ManifestData
from runops.core.project import ProjectConfig
from runops.core.run import RunInfo
from runops.core.site import SiteProfile


def get_simulator_config(
    project: ProjectConfig,
    simulator_name: str,
) -> dict[str, Any]:
    return dict(project.simulators.get(simulator_name, {}))


def is_rsc_site(site: SiteProfile | None) -> bool:
    """Return True when the active site emits ``--rsc`` directives."""
    return site is not None and site.resource_style == "rsc"


def is_pbs_site(site: SiteProfile | None) -> bool:
    """Return True when the active site emits PBS directives."""
    return site is not None and site.scheduler == "pbs"


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
    elif is_pbs_site(site):
        config["nodes"] = job.nodes
        config["ntasks"] = job.ntasks
        config["sockets"] = job.sockets
        if job.mpiprocs:
            config["mpiprocs"] = job.mpiprocs
        if job.ompthreads:
            config["ompthreads"] = job.ompthreads
        if job.group:
            config["group"] = job.group
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
    scheduler = site.scheduler if site is not None else "slurm"
    result: dict[str, Any] = {
        "scheduler": scheduler,
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
    elif scheduler == "pbs":
        result["queue"] = job.partition
        result["nodes"] = job.nodes
        result["ntasks"] = job.ntasks
        result["sockets"] = job.sockets
        if job.mpiprocs:
            result["mpiprocs"] = job.mpiprocs
        if job.ompthreads:
            result["ompthreads"] = job.ompthreads
        if job.group:
            result["group"] = job.group
        if job.gpus:
            result["gpus"] = job.gpus
    else:
        result["nodes"] = job.nodes
        result["ntasks"] = job.ntasks
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
        scheduler=site.scheduler,
        resource_style=site.resource_style,
        modules=list(site.modules),
        simulator_modules=merged_sim_modules,
        stdout_format=site.stdout_format,
        stderr_format=site.stderr_format,
        extra_sbatch=list(site.extra_sbatch),
        env=dict(site.env),
        setup_commands=list(site.setup_commands),
        extra_pbs=list(site.extra_pbs),
        pbs_group=site.pbs_group,
        codex_plugins=list(site.codex_plugins),
    )


def rewrite_staging_paths(
    values: list[str],
    staging_run_dir: Any,
    final_run_dir: Any,
) -> list[str]:
    staging = str(staging_run_dir)
    final = str(final_run_dir)
    return [value.replace(staging, final) for value in values]
