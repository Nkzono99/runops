"""Shared run and survey analysis helpers.

These helpers back both the human CLI commands and the agent-facing
action registry so analysis behavior stays consistent.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

from runops.adapters.registry import get as get_adapter
from runops.core import _analysis_collection as analysis_collection
from runops.core import _analysis_plotting as analysis_plotting
from runops.core.discovery import discover_runs
from runops.core.exceptions import SimctlError
from runops.core.manifest import ManifestData, read_manifest
from runops.core.models import analysis as analysis_models
from runops.core.project import find_project_root

ResolvedSurveyPlotRecipe = analysis_models.ResolvedSurveyPlotRecipe
RunSummaryResult = analysis_models.RunSummaryResult
SurveyCollectionResult = analysis_models.SurveyCollectionResult
SurveyPlotDataResult = analysis_models.SurveyPlotDataResult
SurveyPlotRecipe = analysis_models.SurveyPlotRecipe
SurveyPlotResult = analysis_models.SurveyPlotResult
SurveyPlotSeries = analysis_models.SurveyPlotSeries
SurveyTableResult = analysis_models.SurveyTableResult

PLOT_KINDS = analysis_plotting.PLOT_KINDS
collect_survey_summaries = analysis_collection.collect_survey_summaries
extract_run_figures = analysis_collection.extract_run_figures
load_survey_plot_table = analysis_collection.load_survey_plot_table
prepare_survey_plot_data = analysis_plotting.prepare_survey_plot_data
render_survey_plot = analysis_plotting.render_survey_plot


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
    if kind not in PLOT_KINDS:
        raise SimctlError(
            f"Plot recipe '{recipe_name}' has unknown kind {kind!r}. "
            f"Use one of: {', '.join(sorted(PLOT_KINDS))}"
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
