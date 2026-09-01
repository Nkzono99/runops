"""Survey planning for run creation."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

from runops.core.case import CaseData, load_case, parse_walltime_hours, resolve_case
from runops.core.exceptions import SimctlError
from runops.core.models import run_creation as run_creation_models
from runops.core.project import ProjectConfig, load_project
from runops.core.survey import (
    canonical_data_hash,
    count_survey_points,
    load_survey,
)

from .merge import merge_classification, merge_job
from .resolve import validate_case_references

SurveyExpansionPlan = run_creation_models.SurveyExpansionPlan


def plan_survey_runs(
    project: ProjectConfig,
    survey_dir: Path,
) -> SurveyExpansionPlan:
    """Resolve a survey into the exact run plan used by sweep creation."""
    execution_config = _stable_execution_config_snapshot(project)
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
        classification=merge_classification(
            case_data.classification,
            survey_data.classification,
            survey_data.raw.get("classification", {}),
        ),
        job=merge_job(
            case_data.job,
            survey_data.job,
            survey_data.raw.get("job", {}),
        ),
        params=case_data.params,
        case_dir=case_data.case_dir,
        raw=case_data.raw,
    )
    validate_case_references(project, effective_case)

    variation_keys = list(survey_data.axes.keys())
    for group in survey_data.linked:
        variation_keys.extend(group.keys())

    candidate_count = count_survey_points(
        survey_data.axes,
        survey_data.linked,
    )
    plan_hash = canonical_data_hash(
        {
            "survey": survey_data.raw,
            # TOML table order controls Cartesian enumeration and therefore
            # pNNNN aliases, while canonical mapping hashes sort keys.
            "candidate_order": {
                "axes": list(survey_data.axes),
                "linked_groups": [list(group) for group in survey_data.linked],
            },
            "base_case": case_data.raw,
            "base_case_files": _tree_content_hash(case_data.case_dir),
            "project_execution_config": execution_config,
        }
    )
    if _execution_config_hashes(project.root_dir) != execution_config:
        raise SimctlError(
            "Project execution configuration changed while planning; preview again"
        )
    return SurveyExpansionPlan(
        survey_data=survey_data,
        base_case=case_data,
        effective_case=effective_case,
        variation_keys=tuple(variation_keys),
        candidate_count=candidate_count,
        plan_hash=plan_hash,
        estimated_core_hours=_estimated_core_hours(
            effective_case.job,
            candidate_count,
        ),
    )


def _estimated_core_hours(job: object, candidate_count: int) -> float | None:
    """Return a conservative declared-resource estimate for a full plan."""
    if candidate_count < 1:
        return 0.0
    walltime = _walltime_hours(str(getattr(job, "walltime", "")))
    if walltime is None:
        return None
    processes = max(int(getattr(job, "processes", 1)), 1)
    cores = max(int(getattr(job, "cores", 1)), 1)
    ntasks = max(int(getattr(job, "ntasks", 1)), 1)
    width = max(processes * cores, ntasks)
    return candidate_count * width * walltime


def _walltime_hours(value: str) -> float | None:
    return parse_walltime_hours(value)


def _tree_content_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise SimctlError(f"Case tree must not contain symlinks: {path}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise SimctlError(f"Case tree must contain only regular files: {path}")
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _file_content_hash(path: Path) -> str:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return ""
    except OSError as exc:
        raise SimctlError(
            f"Cannot inspect project configuration {path}: {exc}"
        ) from exc
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise SimctlError(
            "Project execution configuration must be a single-link regular file: "
            f"{path}"
        )
    digest = hashlib.sha256()
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if (
                opened.st_dev != metadata.st_dev
                or opened.st_ino != metadata.st_ino
                or opened.st_nlink != 1
                or not stat.S_ISREG(opened.st_mode)
            ):
                raise SimctlError(
                    f"Project execution configuration changed while opening: {path}"
                )
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise SimctlError(f"Cannot read project configuration {path}: {exc}") from exc
    return f"sha256:{digest.hexdigest()}"


def _execution_config_hashes(project_root: Path) -> dict[str, str]:
    return {
        name: _file_content_hash(project_root / name)
        for name in (
            "runops.toml",
            "simulators.toml",
            "launchers.toml",
            "site.toml",
        )
    }


def _stable_execution_config_snapshot(project: ProjectConfig) -> dict[str, str]:
    """Bind a loaded ProjectConfig to one stable set of on-disk bytes."""
    before = _execution_config_hashes(project.root_dir)
    current = load_project(project.root_dir)
    after = _execution_config_hashes(project.root_dir)
    if before != after:
        raise SimctlError(
            "Project execution configuration changed while loading; preview again"
        )
    if (
        project.raw != current.raw
        or project.simulators != current.simulators
        or project.launchers != current.launchers
    ):
        raise SimctlError(
            "Project execution configuration changed after it was loaded; "
            "reload and preview again"
        )
    return after
