"""Survey planning for run creation."""

from __future__ import annotations

from pathlib import Path

from runops.core.case import CaseData, load_case, resolve_case
from runops.core.models import run_creation as run_creation_models
from runops.core.project import ProjectConfig
from runops.core.survey import expand_survey, load_survey

from .merge import merge_classification, merge_job
from .resolve import validate_case_references

SurveyExpansionPlan = run_creation_models.SurveyExpansionPlan


def plan_survey_runs(
    project: ProjectConfig,
    survey_dir: Path,
) -> SurveyExpansionPlan:
    """Resolve a survey into the exact run plan used by sweep creation."""
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
