"""Result and recipe models for run/survey analysis helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RunSummaryResult:
    """Result of generating one run summary."""

    run_dir: Path
    run_id: str
    summary: dict[str, Any]
    summary_path: Path
    script_path: Path | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class SurveyCollectionResult:
    """Artifacts generated from survey-level summary collection."""

    survey_dir: Path
    total_runs: int
    summaries_collected: int
    generated_summaries: int
    missing_summaries: int
    readiness_counts: dict[str, int]
    readiness_issues: tuple[dict[str, Any], ...]
    state_counts: dict[str, int]
    csv_path: Path
    json_path: Path
    figures_path: Path
    report_path: Path
    figures: tuple[dict[str, str], ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class SurveyTableResult:
    """Flattened survey table for downstream plotting or inspection."""

    survey_dir: Path
    collection: SurveyCollectionResult
    rows: tuple[dict[str, Any], ...]
    columns: tuple[str, ...]


@dataclass(frozen=True)
class SurveyPlotSeries:
    """One plotted data series."""

    label: str
    points: tuple[tuple[Any, float, str], ...]


@dataclass(frozen=True)
class SurveyPlotDataResult:
    """Prepared survey data ready for rendering."""

    survey_dir: Path
    x: str
    y: str
    kind: str
    group_by: str
    columns: tuple[str, ...]
    series: tuple[SurveyPlotSeries, ...]
    rows_considered: int
    points_plotted: int
    generated_summaries: int


@dataclass(frozen=True)
class SurveyPlotResult:
    """Saved survey plot artifact."""

    survey_dir: Path
    output_path: Path
    x: str
    y: str
    kind: str
    group_by: str
    points_plotted: int
    generated_summaries: int


@dataclass(frozen=True)
class SurveyPlotRecipe:
    """Adapter-aware survey plot recipe definition."""

    name: str
    adapter: str
    description: str
    x_candidates: tuple[str, ...]
    y_candidates: tuple[str, ...]
    kind: str = "auto"
    group_by_candidates: tuple[str, ...] = ()
    title: str = ""


@dataclass(frozen=True)
class ResolvedSurveyPlotRecipe:
    """Concrete plot settings after resolving recipe column fallbacks."""

    recipe: SurveyPlotRecipe
    x: str
    y: str
    group_by: str
