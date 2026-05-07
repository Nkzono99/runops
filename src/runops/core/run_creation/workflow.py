"""Shared run creation workflows used by CLI commands and agents."""

from __future__ import annotations

import shlex
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from runops.adapters.base import SimulatorAdapter
from runops.core.case import (
    CaseData,
    load_case,
    resolve_case,
)
from runops.core.discovery import collect_existing_run_ids
from runops.core.event_log import emit_artifact_event
from runops.core.exceptions import (
    ParameterValidationError,
    SimctlError,
)
from runops.core.manifest import write_manifest
from runops.core.models import run_creation as run_creation_models
from runops.core.project import ProjectConfig
from runops.core.run import RunInfo, create_run_directory
from runops.core.site import SiteProfile, load_site_profile
from runops.core.survey import (
    generate_display_name,
)
from runops.jobgen.generator import generate_job_script
from runops.launchers.base import Launcher

from . import manifest as run_creation_manifest
from .plan import plan_survey_runs
from .resolve import (
    load_adapter_for_simulator,
    load_launcher_for_name,
    validate_case_references,
)
from .staging import (
    copy_case_files as _copy_case_files,
)
from .staging import (
    next_available_run_target as _next_available_run_target,
)

_RUN_ID_ALLOCATION_ATTEMPTS = 10_000

CreatedRunResult = run_creation_models.CreatedRunResult
RegenerateResult = run_creation_models.RegenerateResult
SurveyExpansionPlan = run_creation_models.SurveyExpansionPlan

_build_job_config = run_creation_manifest.build_job_config
_build_manifest = run_creation_manifest.build_manifest
_build_manifest_job = run_creation_manifest.build_manifest_job
_get_simulator_config = run_creation_manifest.get_simulator_config
_is_rsc_site = run_creation_manifest.is_rsc_site
_merge_site_modules = run_creation_manifest.merge_site_modules
_rewrite_staging_paths = run_creation_manifest.rewrite_staging_paths


class _RunIdCollisionError(Exception):
    """Internal signal that a run_id was claimed before commit."""

    def __init__(self, run_id: str) -> None:
        super().__init__(run_id)
        self.run_id = run_id


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

    for _ in range(_RUN_ID_ALLOCATION_ATTEMPTS):
        run_id, final_run_dir = _next_available_run_target(parent_dir, known_ids)
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
                raise _RunIdCollisionError(run_id)
            try:
                staging_run_dir.rename(final_run_dir)
            except FileExistsError as exc:
                raise _RunIdCollisionError(run_id) from exc
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
            continue
        finally:
            if not committed and staging_run_dir.exists():
                shutil.rmtree(staging_run_dir, ignore_errors=True)

        known_ids.add(final_run_info.run_id)
        return CreatedRunResult(run_info=final_run_info, warnings=warnings)

    raise SimctlError(
        f"Could not allocate a free run_id after {_RUN_ID_ALLOCATION_ATTEMPTS} attempts"
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
