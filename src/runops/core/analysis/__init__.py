"""Shared run and survey analysis helpers."""

from __future__ import annotations

from .comparison import (
    ComparisonWorkspaceResult,
    create_comparison_workspace,
    slugify_comparison_id,
)
from .story import (
    StoryAuditResult,
    StoryWorkspaceResult,
    audit_story_workspace,
    create_story_workspace,
    slugify_story_id,
)
from .workflow import (
    PLOT_KINDS,
    ResolvedSurveyPlotRecipe,
    RunSummaryResult,
    SurveyCollectionResult,
    SurveyPlotDataResult,
    SurveyPlotRecipe,
    SurveyPlotResult,
    SurveyPlotSeries,
    SurveyTableResult,
    collect_survey_summaries,
    extract_run_figures,
    find_summarize_script,
    generate_run_summary,
    list_survey_plot_recipes,
    load_survey_plot_table,
    prepare_survey_plot_data,
    render_survey_plot,
    resolve_survey_plot_recipe,
    run_summarize_script,
)

__all__ = [
    "PLOT_KINDS",
    "ComparisonWorkspaceResult",
    "ResolvedSurveyPlotRecipe",
    "RunSummaryResult",
    "StoryAuditResult",
    "StoryWorkspaceResult",
    "SurveyCollectionResult",
    "SurveyPlotDataResult",
    "SurveyPlotRecipe",
    "SurveyPlotResult",
    "SurveyPlotSeries",
    "SurveyTableResult",
    "audit_story_workspace",
    "collect_survey_summaries",
    "create_comparison_workspace",
    "create_story_workspace",
    "extract_run_figures",
    "find_summarize_script",
    "generate_run_summary",
    "list_survey_plot_recipes",
    "load_survey_plot_table",
    "prepare_survey_plot_data",
    "render_survey_plot",
    "resolve_survey_plot_recipe",
    "run_summarize_script",
    "slugify_comparison_id",
    "slugify_story_id",
]
