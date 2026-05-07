"""Survey plot data preparation and rendering helpers."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from runops.core._analysis_collection import load_survey_plot_table
from runops.core.exceptions import SimctlError
from runops.core.models import analysis as analysis_models

SurveyPlotDataResult = analysis_models.SurveyPlotDataResult
SurveyPlotResult = analysis_models.SurveyPlotResult
SurveyPlotSeries = analysis_models.SurveyPlotSeries

PLOT_KINDS = {"auto", "line", "scatter", "bar"}


def _coerce_plot_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        numeric = float(value)
        if math.isfinite(numeric):
            return numeric
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            numeric = float(stripped)
        except ValueError:
            return None
        if math.isfinite(numeric):
            return numeric
    return None


def prepare_survey_plot_data(
    survey_dir: Path,
    *,
    x: str,
    y: str,
    kind: str = "auto",
    group_by: str = "",
) -> SurveyPlotDataResult:
    """Prepare survey table data for plotting without rendering."""
    normalized_kind = kind.strip().lower()
    if normalized_kind not in PLOT_KINDS:
        raise SimctlError(
            f"Unknown plot kind: {kind!r}. Use one of: {', '.join(sorted(PLOT_KINDS))}"
        )

    table = load_survey_plot_table(survey_dir)
    available = set(table.columns)
    if x not in available:
        raise SimctlError(f"Unknown x column: {x!r}. Use --list-columns to inspect.")
    if y not in available:
        raise SimctlError(f"Unknown y column: {y!r}. Use --list-columns to inspect.")
    if group_by and group_by not in available:
        raise SimctlError(
            f"Unknown group column: {group_by!r}. Use --list-columns to inspect."
        )

    grouped_points: dict[str, list[tuple[Any, float, str]]] = {}
    x_is_numeric = True
    points_plotted = 0

    for row in table.rows:
        raw_x = row.get(x)
        raw_y = row.get(y)
        if raw_x in (None, "") or raw_y in (None, ""):
            continue

        numeric_y = _coerce_plot_number(raw_y)
        if numeric_y is None:
            continue

        numeric_x = _coerce_plot_number(raw_x)
        point_x: Any
        if numeric_x is None:
            x_is_numeric = False
            point_x = str(raw_x)
        else:
            point_x = numeric_x

        label_value = row.get(group_by, "") if group_by else ""
        label = str(label_value).strip() if label_value not in (None, "") else "all"
        grouped_points.setdefault(label, []).append(
            (point_x, numeric_y, str(row.get("run_id", "")))
        )
        points_plotted += 1

    if points_plotted == 0:
        raise SimctlError(
            f"No plottable rows found for x={x!r}, y={y!r} in survey {survey_dir}"
        )

    resolved_kind = normalized_kind
    if resolved_kind == "auto":
        resolved_kind = "line" if x_is_numeric else "bar"

    if resolved_kind in {"line", "scatter"} and not x_is_numeric:
        raise SimctlError(
            f"Plot kind '{resolved_kind}' requires numeric x values, but {x!r}"
            " contains non-numeric data. Use --kind bar or choose a numeric column."
        )

    series: list[SurveyPlotSeries] = []
    for label, points in sorted(grouped_points.items()):
        ordered_points = points
        if resolved_kind in {"line", "scatter"}:
            ordered_points = sorted(points, key=lambda item: float(item[0]))
        series.append(
            SurveyPlotSeries(
                label=label,
                points=tuple(ordered_points),
            )
        )

    return SurveyPlotDataResult(
        survey_dir=survey_dir,
        x=x,
        y=y,
        kind=resolved_kind,
        group_by=group_by,
        columns=table.columns,
        series=tuple(series),
        rows_considered=len(table.rows),
        points_plotted=points_plotted,
        generated_summaries=table.collection.generated_summaries,
    )


def _sanitize_plot_component(value: str) -> str:
    chars = [ch if ch.isalnum() else "_" for ch in value]
    sanitized = "".join(chars).strip("_")
    return sanitized or "plot"


def render_survey_plot(
    survey_dir: Path,
    *,
    x: str,
    y: str,
    kind: str = "auto",
    group_by: str = "",
    title: str = "",
    output_path: Path | None = None,
) -> SurveyPlotResult:
    """Render a simple survey plot from collected summary data."""
    plot_data = prepare_survey_plot_data(
        survey_dir,
        x=x,
        y=y,
        kind=kind,
        group_by=group_by,
    )

    if output_path is None:
        stem = f"{_sanitize_plot_component(y)}_vs_{_sanitize_plot_component(x)}"
        if group_by:
            stem += f"_by_{_sanitize_plot_component(group_by)}"
        output_path = survey_dir / "summary" / "plots" / f"{stem}.png"

    try:
        import matplotlib  # type: ignore[import-not-found]

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # type: ignore[import-not-found]
    except Exception as exc:
        raise SimctlError(
            "matplotlib is required for runops analyze plot. "
            "Install it in the project environment or use `uv run --with matplotlib`."
        ) from exc

    output_path.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(7.0, 4.5))
    series_list = list(plot_data.series)

    if plot_data.kind == "line":
        for series in series_list:
            xs = [float(point[0]) for point in series.points]
            ys = [point[1] for point in series.points]
            ax.plot(xs, ys, marker="o", linewidth=1.6, label=series.label)
    elif plot_data.kind == "scatter":
        for series in series_list:
            xs = [float(point[0]) for point in series.points]
            ys = [point[1] for point in series.points]
            ax.scatter(xs, ys, s=40, label=series.label)
    else:
        categories: list[str] = []
        seen_categories: set[str] = set()
        for series in series_list:
            for point in series.points:
                label = str(point[0])
                if label not in seen_categories:
                    seen_categories.add(label)
                    categories.append(label)

        base_positions = list(range(len(categories)))
        group_count = max(len(series_list), 1)
        width = 0.8 / group_count

        for idx, series in enumerate(series_list):
            values_by_category = {str(point[0]): point[1] for point in series.points}
            offsets = [
                pos + (idx - (group_count - 1) / 2.0) * width for pos in base_positions
            ]
            ys = [
                values_by_category.get(category, float("nan"))
                for category in categories
            ]
            ax.bar(offsets, ys, width=width, label=series.label)

        ax.set_xticks(base_positions)
        ax.set_xticklabels(categories, rotation=30, ha="right")

    default_title = f"{plot_data.y} vs {plot_data.x}"
    if plot_data.kind == "bar":
        default_title = f"{plot_data.y} by {plot_data.x}"
    ax.set_title(title or default_title)
    ax.set_xlabel(plot_data.x)
    ax.set_ylabel(plot_data.y)
    ax.grid(True, linestyle=":", alpha=0.35)
    if len(series_list) > 1 or (
        len(series_list) == 1 and series_list[0].label != "all"
    ):
        ax.legend()

    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)

    return SurveyPlotResult(
        survey_dir=survey_dir,
        output_path=output_path,
        x=plot_data.x,
        y=plot_data.y,
        kind=plot_data.kind,
        group_by=plot_data.group_by,
        points_plotted=plot_data.points_plotted,
        generated_summaries=plot_data.generated_summaries,
    )
