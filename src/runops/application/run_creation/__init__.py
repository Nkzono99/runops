"""Shared run creation workflows used by CLI commands and agents."""

from __future__ import annotations

from .identity import (
    RunIdentityAllocationError,
    create_reserved_run_directory,
    project_run_identity_lock,
    release_unused_run_id,
    reserve_run_id,
)
from .manifest import (
    build_job_config as _build_job_config,
)
from .manifest import (
    build_manifest as _build_manifest,
)
from .manifest import (
    build_manifest_job as _build_manifest_job,
)
from .manifest import (
    get_simulator_config as _get_simulator_config,
)
from .manifest import (
    is_rsc_site as _is_rsc_site,
)
from .manifest import (
    merge_site_modules as _merge_site_modules,
)
from .manifest import (
    rewrite_staging_paths as _rewrite_staging_paths,
)
from .merge import (
    merge_classification as _merge_classification,
)
from .merge import (
    merge_job as _merge_job,
)
from .plan import plan_survey_runs
from .regenerate import RegenerateResult, regenerate_run
from .resolve import (
    load_adapter_for_simulator,
    load_launcher_for_name,
    load_project_from_path,
    validate_case_references,
)
from .staging import commit_staged_directory
from .workflow import (
    CreatedRunResult,
    SurveyExpansionPlan,
    allows_equivalent_execution,
    build_standalone_manifest_metadata,
    create_case_run,
    create_prepared_run,
    create_survey_runs,
    finalize_manifest_metadata,
    find_equivalent_completed_run,
    materialized_point_identity_is_valid,
    materialized_scientific_identity_is_valid,
    require_formal_run_target,
)

__all__ = [
    "CreatedRunResult",
    "RegenerateResult",
    "RunIdentityAllocationError",
    "SurveyExpansionPlan",
    "_build_job_config",
    "_build_manifest",
    "_build_manifest_job",
    "_get_simulator_config",
    "_is_rsc_site",
    "_merge_classification",
    "_merge_job",
    "_merge_site_modules",
    "_rewrite_staging_paths",
    "allows_equivalent_execution",
    "build_standalone_manifest_metadata",
    "commit_staged_directory",
    "create_case_run",
    "create_prepared_run",
    "create_reserved_run_directory",
    "create_survey_runs",
    "finalize_manifest_metadata",
    "find_equivalent_completed_run",
    "load_adapter_for_simulator",
    "load_launcher_for_name",
    "load_project_from_path",
    "materialized_point_identity_is_valid",
    "materialized_scientific_identity_is_valid",
    "plan_survey_runs",
    "project_run_identity_lock",
    "regenerate_run",
    "release_unused_run_id",
    "require_formal_run_target",
    "reserve_run_id",
    "validate_case_references",
]
