"""Shared run and survey analysis helpers.

These helpers back both the human CLI commands and the agent-facing
action registry so analysis behavior stays consistent.
"""

from __future__ import annotations

import importlib.util
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runops.adapters.registry import get as get_adapter
from runops.core.discovery import discover_runs
from runops.core.exceptions import SimctlError
from runops.core.manifest import ManifestData, read_manifest
from runops.core.project import find_project_root
from runops.core.readiness import evaluate_run_readiness

_FIGURE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".pdf"}
_PLOT_KINDS = {"auto", "line", "scatter", "bar"}


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


def _resolve_adapter_name(manifest: ManifestData) -> str:
    adapter_name = manifest.simulator.get("adapter", "")
    if not adapter_name:
        adapter_name = manifest.simulator.get("name", "")
    if not adapter_name:
        raise SimctlError("no simulator/adapter specified in manifest")
    return str(adapter_name)


def _normalize_recipe_columns(
    value: Any,
    *,
    recipe_name: str,
    field_name: str,
    required: bool = True,
) -> tuple[str, ...]:
    columns: list[str] = []
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            columns.append(stripped)
    elif isinstance(value, list):
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise SimctlError(
                    f"Plot recipe '{recipe_name}' has invalid {field_name} "
                    f"entry: {item!r}"
                )
            columns.append(item.strip())
    elif value not in ("", None):
        raise SimctlError(
            f"Plot recipe '{recipe_name}' field {field_name!r} must be a string "
            "or list of strings"
        )

    if required and not columns:
        raise SimctlError(
            f"Plot recipe '{recipe_name}' must define at least one {field_name} column"
        )
    return tuple(columns)


def _coerce_plot_recipe(
    adapter_name: str,
    recipe_name: str,
    raw_recipe: dict[str, Any],
) -> SurveyPlotRecipe:
    kind = str(raw_recipe.get("kind", "auto")).strip().lower() or "auto"
    if kind not in _PLOT_KINDS:
        raise SimctlError(
            f"Plot recipe '{recipe_name}' has unknown kind {kind!r}. "
            f"Use one of: {', '.join(sorted(_PLOT_KINDS))}"
        )

    return SurveyPlotRecipe(
        name=recipe_name,
        adapter=adapter_name,
        description=str(raw_recipe.get("description", "")).strip(),
        x_candidates=_normalize_recipe_columns(
            raw_recipe.get("x"),
            recipe_name=recipe_name,
            field_name="x",
        ),
        y_candidates=_normalize_recipe_columns(
            raw_recipe.get("y"),
            recipe_name=recipe_name,
            field_name="y",
        ),
        kind=kind,
        group_by_candidates=_normalize_recipe_columns(
            raw_recipe.get("group_by"),
            recipe_name=recipe_name,
            field_name="group_by",
            required=False,
        ),
        title=str(raw_recipe.get("title", "")).strip(),
    )


def _survey_adapter_names(survey_dir: Path) -> tuple[str, ...]:
    run_dirs = discover_runs(survey_dir)
    if not run_dirs:
        raise SimctlError("No runs found in survey directory.")

    adapter_names: set[str] = set()
    for run_dir in run_dirs:
        try:
            manifest = read_manifest(run_dir)
            adapter_names.add(_resolve_adapter_name(manifest))
        except SimctlError:
            continue

    if not adapter_names:
        raise SimctlError("No adapter metadata found in survey manifests.")
    return tuple(sorted(adapter_names))


def list_survey_plot_recipes(survey_dir: Path) -> tuple[SurveyPlotRecipe, ...]:
    """Return adapter-provided plot recipes for a survey."""
    adapter_names = _survey_adapter_names(survey_dir)
    if len(adapter_names) > 1:
        raise SimctlError(
            "Multiple adapters found in survey. Plot recipes require a single adapter."
        )

    adapter_name = adapter_names[0]
    import runops.adapters  # noqa: F401

    adapter_cls = get_adapter(adapter_name)
    raw_recipes = adapter_cls.default_plot_recipes()
    recipes: list[SurveyPlotRecipe] = []
    for recipe_name, raw_recipe in sorted(raw_recipes.items()):
        if not isinstance(raw_recipe, dict):
            raise SimctlError(
                f"Plot recipe '{recipe_name}' for adapter {adapter_name!r} "
                "must be a table/dict"
            )
        recipes.append(_coerce_plot_recipe(adapter_name, recipe_name, raw_recipe))
    return tuple(recipes)


def _resolve_recipe_column(
    recipe_name: str,
    field_name: str,
    candidates: tuple[str, ...],
    available_columns: tuple[str, ...],
    *,
    required: bool = True,
) -> str:
    available = set(available_columns)
    for candidate in candidates:
        if candidate in available:
            return candidate

    if not required:
        return ""

    raise SimctlError(
        f"Plot recipe '{recipe_name}' could not resolve {field_name}. "
        f"Tried: {', '.join(candidates)}"
    )


def resolve_survey_plot_recipe(
    survey_dir: Path,
    recipe_name: str,
) -> ResolvedSurveyPlotRecipe:
    """Resolve an adapter recipe against the available survey columns."""
    recipes = list_survey_plot_recipes(survey_dir)
    recipe = next((item for item in recipes if item.name == recipe_name), None)
    if recipe is None:
        names = ", ".join(item.name for item in recipes) or "(none)"
        raise SimctlError(
            f"Unknown plot recipe: {recipe_name!r}. Available recipes: {names}"
        )

    table = load_survey_plot_table(survey_dir)
    return ResolvedSurveyPlotRecipe(
        recipe=recipe,
        x=_resolve_recipe_column(
            recipe.name,
            "x",
            recipe.x_candidates,
            table.columns,
        ),
        y=_resolve_recipe_column(
            recipe.name,
            "y",
            recipe.y_candidates,
            table.columns,
        ),
        group_by=_resolve_recipe_column(
            recipe.name,
            "group_by",
            recipe.group_by_candidates,
            table.columns,
            required=False,
        ),
    )


def _iter_case_script_candidates(
    project_root: Path,
    manifest: ManifestData,
) -> list[Path]:
    case_refs = [
        str(manifest.origin.get("case", "")),
        str(manifest.origin.get("base_case", "")),
        str(manifest.run.get("case", "")),
    ]
    simulator_name = str(manifest.simulator.get("name", ""))

    seen: set[Path] = set()
    candidates: list[Path] = []

    for case_ref_raw in case_refs:
        case_ref = case_ref_raw.strip()
        if not case_ref:
            continue

        case_path = Path(case_ref)
        direct = project_root / "cases" / case_path / "summarize.py"
        if direct not in seen:
            seen.add(direct)
            candidates.append(direct)

        if simulator_name and len(case_path.parts) == 1:
            sim_scoped = (
                project_root / "cases" / simulator_name / case_path / "summarize.py"
            )
            if sim_scoped not in seen:
                seen.add(sim_scoped)
                candidates.append(sim_scoped)

            # Fallback for multi-simulator layouts when the manifest stores only
            # the short case name.
            glob_pattern = f"*/{case_path.name}/summarize.py"
            for matched in sorted((project_root / "cases").glob(glob_pattern)):
                if matched not in seen:
                    seen.add(matched)
                    candidates.append(matched)

    return candidates


def find_summarize_script(
    manifest: ManifestData,
    run_dir: Path,
) -> Path | None:
    """Discover a project-level summarize.py script for a run."""
    try:
        project_root = find_project_root(run_dir)
    except SimctlError:
        return None

    for candidate in _iter_case_script_candidates(project_root, manifest):
        if candidate.is_file():
            return candidate

    project_script = project_root / "scripts" / "summarize.py"
    if project_script.is_file():
        return project_script

    return None


def run_summarize_script(
    script_path: Path,
    run_dir: Path,
    base_summary: dict[str, Any],
) -> dict[str, Any]:
    """Load and execute a project summarize.py hook."""
    spec = importlib.util.spec_from_file_location("_project_summarize", script_path)
    if spec is None or spec.loader is None:
        msg = f"Could not load script: {script_path}"
        raise RuntimeError(msg)

    module = importlib.util.module_from_spec(spec)
    script_parent = str(script_path.parent)
    path_added = script_parent not in sys.path
    if path_added:
        sys.path.insert(0, script_parent)
    try:
        spec.loader.exec_module(module)
    finally:
        if path_added and script_parent in sys.path:
            sys.path.remove(script_parent)

    fn = getattr(module, "summarize", None)
    if fn is None:
        msg = f"Script {script_path} has no 'summarize' function"
        raise RuntimeError(msg)

    return fn(run_dir, base_summary)  # type: ignore[no-any-return]


def generate_run_summary(run_dir: Path) -> RunSummaryResult:
    """Generate or update ``analysis/summary.json`` for one run."""
    manifest = read_manifest(run_dir)
    adapter_name = _resolve_adapter_name(manifest)
    import runops.adapters  # noqa: F401

    adapter_cls = get_adapter(adapter_name)
    adapter = adapter_cls()

    summary = adapter.summarize(run_dir)
    script_path = find_summarize_script(manifest, run_dir)
    warnings: list[str] = []
    if script_path is not None:
        try:
            summary = run_summarize_script(script_path, run_dir, summary)
        except Exception as exc:
            warnings.append(f"summarize script failed: {exc}")

    analysis_dir = run_dir / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    summary_path = analysis_dir / "summary.json"

    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
        f.write("\n")

    run_id = str(manifest.run.get("id", run_dir.name))
    return RunSummaryResult(
        run_dir=run_dir,
        run_id=run_id,
        summary=summary,
        summary_path=summary_path,
        script_path=script_path,
        warnings=tuple(warnings),
    )


def _flatten_summary(summary: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in summary.items():
        flat_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            nested = _flatten_summary(value, flat_key)
            if nested:
                flat.update(nested)
            else:
                flat[flat_key] = value
            continue
        flat[flat_key] = value
    return flat


def _csv_cell_value(value: Any) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _flatten_manifest_context(manifest: ManifestData) -> dict[str, Any]:
    flat: dict[str, Any] = {}
    sections = {
        "origin": manifest.origin,
        "classification": manifest.classification,
        "simulator": manifest.simulator,
        "launcher": manifest.launcher,
        "variation": manifest.variation,
        "param": manifest.params_snapshot,
    }
    for prefix, section in sections.items():
        if not section:
            continue
        flat.update(_flatten_summary(section, prefix))
    return flat


def _collect_numeric_stats(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    metric_values: dict[str, list[float]] = {}
    for row in rows:
        for key, value in row.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            numeric = float(value)
            if not math.isfinite(numeric):
                continue
            metric_values.setdefault(key, []).append(numeric)

    stats: dict[str, dict[str, float]] = {}
    for key, values in metric_values.items():
        if not values:
            continue
        stats[key] = {
            "count": float(len(values)),
            "min": min(values),
            "max": max(values),
            "mean": sum(values) / len(values),
        }
    return stats


def _extract_figures(run_dir: Path, summary: dict[str, Any]) -> list[dict[str, str]]:
    figures: list[dict[str, str]] = []
    seen_paths: set[str] = set()

    raw_figures = summary.get("figures", [])
    if isinstance(raw_figures, list):
        for item in raw_figures:
            rel_path = ""
            caption = ""
            if isinstance(item, dict):
                rel_path = str(item.get("path", "")).strip()
                caption = str(item.get("caption", "")).strip()
            elif isinstance(item, str):
                rel_path = item.strip()
            if not rel_path:
                continue
            seen_paths.add(rel_path)
            figures.append({"path": rel_path, "caption": caption})

    auto_fig_dir = run_dir / "analysis" / "figures"
    if auto_fig_dir.is_dir():
        for path in sorted(auto_fig_dir.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in _FIGURE_EXTENSIONS:
                continue
            rel_path = str(path.relative_to(run_dir / "analysis")).replace("\\", "/")
            if rel_path in seen_paths:
                continue
            seen_paths.add(rel_path)
            figures.append({"path": rel_path, "caption": ""})

    return figures


def extract_run_figures(
    run_dir: Path, summary: dict[str, Any]
) -> tuple[dict[str, str], ...]:
    """Return normalized figure metadata for a run summary.

    This exposes the same discovery rules used by survey collection so other
    features can safely reuse the run-facing analysis artifacts.
    """

    return tuple(_extract_figures(run_dir, summary))


def _format_float(value: float) -> str:
    if (
        math.isfinite(value)
        and value != 0.0
        and (abs(value) >= 1e4 or abs(value) < 1e-3)
    ):
        return f"{value:.6e}"
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _write_survey_report(
    report_path: Path,
    *,
    survey_dir: Path,
    total_runs: int,
    summaries_collected: int,
    generated_summaries: int,
    missing_summaries: int,
    readiness_counts: dict[str, int],
    readiness_issues: list[dict[str, Any]],
    state_counts: dict[str, int],
    numeric_stats: dict[str, dict[str, float]],
    figures: list[dict[str, str]],
    warnings: list[str],
) -> None:
    lines: list[str] = [
        "# Survey Summary",
        "",
        f"- Survey directory: `{survey_dir}`",
        f"- Generated at: `{datetime.now(timezone.utc).isoformat(timespec='seconds')}`",
        f"- Total runs: {total_runs}",
        f"- Summaries collected: {summaries_collected}",
        f"- Summaries auto-generated by collect: {generated_summaries}",
        f"- Runs missing summary.json: {missing_summaries}",
        "",
        "## State Counts",
        "",
    ]

    if state_counts:
        for state, count in sorted(state_counts.items()):
            lines.append(f"- `{state}`: {count}")
    else:
        lines.append("- No manifest states found.")

    lines.extend(["", "## Analysis Readiness", ""])
    if readiness_counts:
        for status, count in sorted(readiness_counts.items()):
            lines.append(f"- `{status}`: {count}")
    else:
        lines.append("- No readiness diagnostics were available.")

    if readiness_issues:
        lines.extend(["", "### Runs Requiring Attention", ""])
        for issue in readiness_issues:
            missing = issue.get("missing_required_artifacts", [])
            missing_text = ", ".join(missing) if missing else "none"
            warnings_text = "; ".join(issue.get("warnings", [])) or "not ready"
            lines.append(
                f"- `{issue.get('run_id', '')}`: "
                f"{issue.get('analysis_status', 'unknown')} "
                f"(missing: {missing_text}) - {warnings_text}"
            )

    lines.extend(["", "## Numeric Metrics", ""])
    if numeric_stats:
        lines.append("| metric | count | min | max | mean |")
        lines.append("| --- | ---: | ---: | ---: | ---: |")
        for metric, stats in sorted(numeric_stats.items()):
            lines.append(
                "| "
                f"{metric} | {int(stats['count'])} | {_format_float(stats['min'])}"
                f" | {_format_float(stats['max'])} | {_format_float(stats['mean'])} |"
            )
    else:
        lines.append("No numeric scalar metrics were found across collected summaries.")

    lines.extend(["", "## Figures", ""])
    if figures:
        for fig in figures:
            caption = f" - {fig['caption']}" if fig["caption"] else ""
            lines.append(f"- `{fig['run_id']}`: `{fig['path']}`{caption}")
    else:
        lines.append("No figure artifacts were indexed.")

    if warnings:
        lines.extend(["", "## Warnings", ""])
        for warning in warnings:
            lines.append(f"- {warning}")

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _ordered_columns(rows: list[dict[str, Any]]) -> list[str]:
    columns: set[str] = set()
    for row in rows:
        columns.update(row.keys())
    preferred = [
        "run_id",
        "display_name",
        "status",
        "analysis_status",
        "analysis_ready",
        "simulator_status",
        "summary_available",
        "summary_status",
        "summary_partial",
        "missing_required_artifacts",
    ]
    return [
        *[column for column in preferred if column in columns],
        *sorted(columns - set(preferred)),
    ]


def _load_survey_aggregate(json_path: Path) -> dict[str, Any]:
    with open(json_path, encoding="utf-8") as f:
        aggregate = json.load(f)
    if not isinstance(aggregate, dict):
        raise SimctlError(f"Invalid survey aggregate at {json_path}")
    return aggregate


def _flatten_aggregate_run_row(run: dict[str, Any]) -> dict[str, Any]:
    row = {
        "run_id": run.get("run_id", ""),
        "display_name": run.get("display_name", ""),
        "status": run.get("status", ""),
    }
    for key in (
        "analysis_status",
        "analysis_ready",
        "simulator_status",
        "summary_available",
        "summary_status",
        "summary_partial",
        "missing_required_artifacts",
    ):
        if key in run:
            row[key] = run[key]
    flat_metadata = run.get("flat_metadata", {})
    if isinstance(flat_metadata, dict):
        row.update(flat_metadata)
    flat_summary = run.get("flat_summary", {})
    if isinstance(flat_summary, dict):
        row.update(flat_summary)
    return row


def load_survey_plot_table(survey_dir: Path) -> SurveyTableResult:
    """Collect survey summaries and expose a flat table for plotting."""
    collection = collect_survey_summaries(survey_dir)
    aggregate = _load_survey_aggregate(collection.json_path)

    rows: list[dict[str, Any]] = []
    raw_runs = aggregate.get("runs", [])
    if isinstance(raw_runs, list):
        for item in raw_runs:
            if not isinstance(item, dict):
                continue
            rows.append(_flatten_aggregate_run_row(item))

    return SurveyTableResult(
        survey_dir=survey_dir,
        collection=collection,
        rows=tuple(rows),
        columns=tuple(_ordered_columns(rows)),
    )


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
    if normalized_kind not in _PLOT_KINDS:
        raise SimctlError(
            f"Unknown plot kind: {kind!r}. Use one of: {', '.join(sorted(_PLOT_KINDS))}"
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


def collect_survey_summaries(survey_dir: Path) -> SurveyCollectionResult:
    """Collect run summaries from a survey and write aggregate artifacts."""
    survey_dir = Path(survey_dir).resolve()
    run_dirs = discover_runs(survey_dir)
    if not run_dirs:
        raise SimctlError("No runs found in survey directory.")

    run_rows: list[dict[str, Any]] = []
    csv_rows: list[dict[str, Any]] = []
    figure_rows: list[dict[str, str]] = []
    state_counts: dict[str, int] = {}
    readiness_counts: dict[str, int] = {}
    readiness_issues: list[dict[str, Any]] = []
    generated_count = 0
    missing_count = 0
    warnings: list[str] = []

    for run_dir in run_dirs:
        run_id = run_dir.name
        display_name = ""
        state = ""
        flat_metadata: dict[str, Any] = {}
        metadata_sections: dict[str, Any] = {}
        analysis_ready = False
        analysis_status = ""
        simulator_status = ""
        missing_required_artifacts: list[str] = []
        readiness_warnings: list[str] = []
        try:
            manifest = read_manifest(run_dir)
            run_id = str(manifest.run.get("id", run_id))
            display_name = str(manifest.run.get("display_name", ""))
            state = str(manifest.run.get("status", ""))
            if state:
                state_counts[state] = state_counts.get(state, 0) + 1
            flat_metadata = _flatten_manifest_context(manifest)
            metadata_sections = {
                "origin": dict(manifest.origin),
                "classification": dict(manifest.classification),
                "simulator": dict(manifest.simulator),
                "launcher": dict(manifest.launcher),
                "variation": dict(manifest.variation),
                "param": dict(manifest.params_snapshot),
            }
            readiness = evaluate_run_readiness(run_dir, manifest=manifest)
            analysis_ready = readiness.analysis_ready
            analysis_status = readiness.analysis_status
            simulator_status = readiness.simulator_status
            missing_required_artifacts = list(readiness.missing_required_artifacts)
            readiness_warnings = list(readiness.warnings)
        except SimctlError:
            manifest = None

        summary_path = run_dir / "analysis" / "summary.json"
        row: dict[str, Any] = {
            "run_id": run_id,
            "display_name": display_name,
            "status": state,
            "summary_available": summary_path.is_file(),
            "summary_path": (
                str(summary_path.relative_to(survey_dir)).replace("\\", "/")
                if summary_path.is_file()
                else ""
            ),
            "analysis_status": analysis_status,
            "analysis_ready": analysis_ready,
            "simulator_status": simulator_status,
            "missing_required_artifacts": missing_required_artifacts,
            "readiness_warnings": readiness_warnings,
        }

        if not summary_path.is_file():
            missing_count += 1
            if state == "completed":
                analysis_ready = False
                if analysis_status in {"", "ready"}:
                    analysis_status = "incomplete"
                readiness_warnings.append("analysis/summary.json missing")
                row["analysis_status"] = analysis_status
                row["analysis_ready"] = analysis_ready
                row["readiness_warnings"] = readiness_warnings
            if analysis_status:
                readiness_counts[analysis_status] = (
                    readiness_counts.get(analysis_status, 0) + 1
                )
            if state == "completed" and not analysis_ready:
                readiness_issues.append(
                    {
                        "run_id": run_id,
                        "run_dir": str(run_dir),
                        "analysis_status": analysis_status or "unknown",
                        "missing_required_artifacts": missing_required_artifacts,
                        "warnings": readiness_warnings,
                    }
                )
                warnings.extend(
                    f"{run_id}: {warning}" for warning in readiness_warnings
                )
            run_rows.append(row)
            continue

        with open(summary_path, encoding="utf-8") as f:
            summary: dict[str, Any] = json.load(f)
        summary_status = str(summary.get("status", "")).strip()
        summary_partial = bool(summary.get("partial", False))
        if summary_status and summary_status != "completed":
            summary_partial = True
        if summary_partial:
            analysis_ready = False
            if analysis_status in {"", "ready"}:
                analysis_status = "incomplete"
            warning_status = summary_status or "partial"
            readiness_warnings.append(
                f"analysis/summary.json status is {warning_status}"
            )

        flat_summary = _flatten_summary(summary)
        csv_row: dict[str, Any] = {
            "run_id": run_id,
            "display_name": display_name,
            "status": state,
            "analysis_status": analysis_status,
            "analysis_ready": analysis_ready,
            "simulator_status": simulator_status,
            "summary_available": True,
            "summary_status": summary_status,
            "summary_partial": summary_partial,
            "missing_required_artifacts": missing_required_artifacts,
        }
        csv_row.update(flat_metadata)
        csv_row.update(flat_summary)
        csv_rows.append(csv_row)

        figures = _extract_figures(run_dir, summary)
        for figure in figures:
            figure_path = (run_dir / "analysis" / figure["path"]).relative_to(
                survey_dir
            )
            figure_rows.append(
                {
                    "run_id": run_id,
                    "display_name": display_name,
                    "path": str(figure_path).replace("\\", "/"),
                    "caption": figure["caption"],
                }
            )

        row["summary"] = summary
        row["analysis_status"] = analysis_status
        row["analysis_ready"] = analysis_ready
        row["summary_status"] = summary_status
        row["summary_partial"] = summary_partial
        row["readiness_warnings"] = readiness_warnings
        row["metadata"] = metadata_sections
        row["flat_metadata"] = {
            key: _csv_cell_value(value) for key, value in flat_metadata.items()
        }
        row["flat_summary"] = {
            key: _csv_cell_value(value) for key, value in flat_summary.items()
        }
        row["figures"] = figures
        if analysis_status:
            readiness_counts[analysis_status] = (
                readiness_counts.get(analysis_status, 0) + 1
            )
        if state == "completed" and not analysis_ready:
            readiness_issues.append(
                {
                    "run_id": run_id,
                    "run_dir": str(run_dir),
                    "analysis_status": analysis_status or "unknown",
                    "missing_required_artifacts": missing_required_artifacts,
                    "warnings": readiness_warnings,
                }
            )
            warnings.extend(f"{run_id}: {warning}" for warning in readiness_warnings)
        run_rows.append(row)

    if not csv_rows:
        raise SimctlError("No summaries found. Run 'runops analyze summarize' first.")

    ordered_columns = _ordered_columns(csv_rows)

    summary_dir = survey_dir / "summary"
    summary_dir.mkdir(parents=True, exist_ok=True)
    csv_path = summary_dir / "survey_summary.csv"
    json_path = summary_dir / "survey_summary.json"
    figures_path = summary_dir / "figures_index.json"
    report_path = summary_dir / "survey_summary.md"

    csv_output_rows: list[dict[str, object]] = []
    for row in csv_rows:
        csv_output_rows.append(
            {key: _csv_cell_value(value) for key, value in row.items()}
        )

    import csv

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ordered_columns, extrasaction="ignore")
        writer.writeheader()
        for row in csv_output_rows:
            writer.writerow(row)

    numeric_stats = _collect_numeric_stats(csv_rows)
    aggregate = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "survey_dir": str(survey_dir),
        "total_runs": len(run_dirs),
        "summaries_collected": len(csv_rows),
        "generated_summaries": generated_count,
        "missing_summaries": missing_count,
        "readiness_counts": readiness_counts,
        "readiness_issues": readiness_issues,
        "state_counts": state_counts,
        "numeric_stats": numeric_stats,
        "warnings": warnings,
        "runs": run_rows,
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(aggregate, f, indent=2)
        f.write("\n")

    with open(figures_path, "w", encoding="utf-8") as f:
        json.dump({"figures": figure_rows}, f, indent=2)
        f.write("\n")

    _write_survey_report(
        report_path,
        survey_dir=survey_dir,
        total_runs=len(run_dirs),
        summaries_collected=len(csv_rows),
        generated_summaries=generated_count,
        missing_summaries=missing_count,
        readiness_counts=readiness_counts,
        readiness_issues=readiness_issues,
        state_counts=state_counts,
        numeric_stats=numeric_stats,
        figures=figure_rows,
        warnings=warnings,
    )

    return SurveyCollectionResult(
        survey_dir=survey_dir,
        total_runs=len(run_dirs),
        summaries_collected=len(csv_rows),
        generated_summaries=generated_count,
        missing_summaries=missing_count,
        readiness_counts=readiness_counts,
        readiness_issues=tuple(readiness_issues),
        state_counts=state_counts,
        csv_path=csv_path,
        json_path=json_path,
        figures_path=figures_path,
        report_path=report_path,
        figures=tuple(figure_rows),
        warnings=tuple(warnings),
    )
