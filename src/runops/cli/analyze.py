"""CLI commands for analysis: summarize, collect, and plot."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from runops.application.actions import ActionStatus, execute_action
from runops.cli.run_lookup import find_project_runs_dir, resolve_run_or_cwd
from runops.core.analysis import (
    audit_story_workspace,
    create_comparison_workspace,
    create_story_workspace,
    list_survey_plot_recipes,
    load_survey_plot_table,
    render_survey_plot,
    resolve_survey_plot_recipe,
)
from runops.core.discovery import discover_runs, resolve_run
from runops.core.exceptions import SimctlError
from runops.core.project import find_project_root


def _resolve_export_target(target: str | None, *, search_dir: Path) -> Path:
    cwd = search_dir.resolve()

    def _looks_like_collection(path: Path) -> bool:
        return (path / "survey.toml").is_file() or bool(discover_runs(path))

    if target is None:
        if (cwd / "manifest.toml").is_file():
            return cwd
        if _looks_like_collection(cwd):
            return cwd
        typer.echo(
            "Error: cwd is neither a run directory nor a directory containing runs. "
            "Specify a run, run_id, or survey directory.",
            err=True,
        )
        raise typer.Exit(code=1)

    candidate = Path(target)
    resolved = (
        candidate.resolve() if candidate.is_absolute() else (cwd / candidate).resolve()
    )
    if resolved.exists():
        if (resolved / "manifest.toml").is_file():
            return resolved
        if resolved.is_dir() and _looks_like_collection(resolved):
            return resolved
        typer.echo(
            f"Error: {resolved} is neither a run directory"
            " nor a directory containing runs.",
            err=True,
        )
        raise typer.Exit(code=1)

    try:
        return resolve_run(target, find_project_runs_dir(cwd))
    except SimctlError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from None


def summarize(
    run: str = typer.Argument(None, help="Run directory or run_id (defaults to cwd)."),
) -> None:
    """Generate or update analysis/summary.json for a run."""
    run_dir = resolve_run_or_cwd(run, search_dir=Path.cwd())

    try:
        result = execute_action("summarize_run", run_dir=run_dir)
    except (OSError, TypeError, json.JSONDecodeError, SimctlError) as e:
        typer.echo(f"Error generating summary: {e}", err=True)
        raise typer.Exit(code=1) from None

    if result.status is not ActionStatus.SUCCESS:
        typer.echo(f"Error generating summary: {result.message}", err=True)
        raise typer.Exit(code=1)

    script_path = str(result.data.get("script_path", ""))
    if script_path:
        typer.echo(f"  Applied script: {Path(script_path).name}")
    for warning in result.data.get("warnings", []):
        typer.echo(f"Warning: {warning}", err=True)

    summary = result.data.get("summary", {})
    run_id = result.data.get("run_id", "???")
    typer.echo(f"Summary written: {result.data.get('summary_path', '')}")
    typer.echo(f"  Artifacts: {result.data.get('artifacts_path', '')}")
    typer.echo(f"  Run: {run_id}")
    typer.echo(f"  Keys: {', '.join(sorted(summary.keys()))}")


def collect(
    survey_dir: Path = typer.Argument(None, help="Survey directory (defaults to cwd)."),
) -> None:
    """Collect summaries from all runs in a survey into aggregate artifacts."""
    if survey_dir is None:
        survey_dir = Path.cwd()
    if not survey_dir.is_dir():
        typer.echo(f"Error: directory not found: {survey_dir}", err=True)
        raise typer.Exit(code=1)

    try:
        result = execute_action("collect_survey", survey_dir=survey_dir)
    except (OSError, TypeError, json.JSONDecodeError, SimctlError) as e:
        typer.echo(f"Error collecting summaries: {e}", err=True)
        raise typer.Exit(code=1) from None

    if result.status is not ActionStatus.SUCCESS:
        typer.echo(f"Error collecting summaries: {result.message}", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"Collected {result.message.removeprefix('Collected ').strip()}")
    typer.echo(f"  CSV: {result.data.get('csv_path', '')}")
    typer.echo(f"  JSON: {result.data.get('json_path', '')}")
    typer.echo(f"  Artifacts: {result.data.get('artifacts_path', '')}")
    typer.echo(f"  Report: {result.data.get('report_path', '')}")
    generated_summaries = int(result.data.get("generated_summaries", 0))
    if generated_summaries > 0:
        typer.echo(
            f"  Auto-summarized: {generated_summaries} completed runs during collect"
        )
    missing_summaries = int(result.data.get("missing_summaries", 0))
    if missing_summaries > 0:
        typer.echo(f"  ({missing_summaries} runs missing summary.json)")
    readiness_issues = result.data.get("readiness_issues", [])
    if readiness_issues:
        typer.echo(f"  Readiness issues: {len(readiness_issues)} run(s)")
    for warning in result.data.get("warnings", []):
        typer.echo(f"Warning: {warning}", err=True)


def plot(
    survey_dir: Path = typer.Argument(None, help="Survey directory (defaults to cwd)."),
    x: str | None = typer.Option(None, "--x", help="Column for the x-axis."),
    y: str | None = typer.Option(None, "--y", help="Column for the y-axis."),
    recipe: str = typer.Option(
        "",
        "--recipe",
        help="Adapter-aware plot recipe name.",
    ),
    kind: str = typer.Option(
        "auto",
        "--kind",
        help="Plot kind: auto, line, scatter, or bar.",
    ),
    group_by: str = typer.Option(
        "",
        "--group",
        help="Optional column used to split data into multiple series.",
    ),
    title: str = typer.Option("", "--title", help="Optional plot title."),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Output image path (default: summary/plots/<y>_vs_<x>.png).",
    ),
    list_columns: bool = typer.Option(
        False,
        "--list-columns",
        help="Print available plot columns and exit.",
    ),
    list_recipes: bool = typer.Option(
        False,
        "--list-recipes",
        help="Print available adapter plot recipes and exit.",
    ),
) -> None:
    """Render a survey plot from explicit columns or an adapter recipe."""
    if survey_dir is None:
        survey_dir = Path.cwd()
    if not survey_dir.is_dir():
        typer.echo(f"Error: directory not found: {survey_dir}", err=True)
        raise typer.Exit(code=1)

    if list_columns:
        try:
            table = load_survey_plot_table(survey_dir)
        except (OSError, TypeError, json.JSONDecodeError, SimctlError) as e:
            typer.echo(f"Error loading plot columns: {e}", err=True)
            raise typer.Exit(code=1) from None

        typer.echo("Available columns:")
        for column in table.columns:
            typer.echo(f"  {column}")
        return

    if list_recipes:
        try:
            recipes = list_survey_plot_recipes(survey_dir)
        except (OSError, TypeError, json.JSONDecodeError, SimctlError) as e:
            typer.echo(f"Error loading plot recipes: {e}", err=True)
            raise typer.Exit(code=1) from None

        if not recipes:
            typer.echo("No adapter plot recipes available for this survey.")
            return

        typer.echo("Available plot recipes:")
        for item in recipes:
            x_candidates = ", ".join(item.x_candidates)
            y_candidates = ", ".join(item.y_candidates)
            group_candidates = (
                ", ".join(item.group_by_candidates)
                if item.group_by_candidates
                else "(none)"
            )
            typer.echo(f"  {item.name} [{item.adapter}]")
            if item.description:
                typer.echo(f"    {item.description}")
            typer.echo(f"    x: {x_candidates}")
            typer.echo(f"    y: {y_candidates}")
            typer.echo(f"    kind: {item.kind}")
            typer.echo(f"    group_by: {group_candidates}")
        return

    resolved_recipe = None
    if recipe:
        try:
            resolved_recipe = resolve_survey_plot_recipe(survey_dir, recipe)
        except (OSError, TypeError, json.JSONDecodeError, SimctlError) as e:
            typer.echo(f"Error resolving plot recipe: {e}", err=True)
            raise typer.Exit(code=1) from None

    if not x and resolved_recipe is not None:
        x = resolved_recipe.x
    if not y and resolved_recipe is not None:
        y = resolved_recipe.y
    if not group_by and resolved_recipe is not None:
        group_by = resolved_recipe.group_by
    if kind == "auto" and resolved_recipe is not None:
        kind = resolved_recipe.recipe.kind
    if not title and resolved_recipe is not None:
        title = resolved_recipe.recipe.title

    if not x or not y:
        typer.echo(
            "Error: --x and --y are required unless --recipe, --list-columns, "
            "or --list-recipes is used.",
            err=True,
        )
        raise typer.Exit(code=1)

    try:
        result = render_survey_plot(
            survey_dir,
            x=x,
            y=y,
            kind=kind,
            group_by=group_by,
            title=title,
            output_path=output,
        )
    except (OSError, TypeError, json.JSONDecodeError, SimctlError) as e:
        typer.echo(f"Error rendering plot: {e}", err=True)
        raise typer.Exit(code=1) from None

    typer.echo(f"Plot written: {result.output_path}")
    if resolved_recipe is not None:
        typer.echo(f"  Recipe: {resolved_recipe.recipe.name}")
    typer.echo(f"  Kind: {result.kind}")
    typer.echo(f"  Points: {result.points_plotted}")
    if result.generated_summaries > 0:
        typer.echo(
            "  Auto-summarized:"
            f" {result.generated_summaries} completed runs during plot"
        )


def new_comparison(
    name: str = typer.Argument(help="Human-readable comparison name."),
    comparison_id: str = typer.Option(
        "",
        "--id",
        help=(
            "Stable comparison id under analysis/cross_run/. "
            "Defaults to a slugified name."
        ),
    ),
    sources: list[Path] | None = typer.Option(
        None,
        "--source",
        "-s",
        help="Run, survey, or path source to record in manifest.toml.",
    ),
) -> None:
    """Create a cross-run comparison workspace under analysis/cross_run/."""
    try:
        project_root = find_project_root(Path.cwd())
        result = create_comparison_workspace(
            project_root,
            name=name,
            comparison_id=comparison_id,
            sources=tuple(sources or []),
        )
    except (OSError, SimctlError) as e:
        typer.echo(f"Error creating comparison workspace: {e}", err=True)
        raise typer.Exit(code=1) from None

    typer.echo(f"Comparison workspace created: {result.comparison_dir}")
    typer.echo(f"  ID: {result.comparison_id}")
    typer.echo(f"  Manifest: {result.manifest_path}")
    typer.echo(f"  README: {result.readme_path}")
    typer.echo(f"  Sources: {result.source_count}")


def new_story(
    name: str = typer.Argument(help="Human-readable story name or stable id."),
    story_id: str = typer.Option(
        "",
        "--id",
        help="Stable story id under analysis/stories/. Defaults to a slugified name.",
    ),
    title: str = typer.Option(
        "",
        "--title",
        help="Optional display title. Defaults to the story name.",
    ),
    sources: list[Path] | None = typer.Option(
        None,
        "--source",
        "-s",
        help="Run, survey, comparison, or path source to record in story.toml.",
    ),
) -> None:
    """Create a story acceptance audit workspace."""
    try:
        cwd = Path.cwd()
        project_root = find_project_root(cwd)
        resolved_sources = tuple(
            source if source.is_absolute() else (cwd / source)
            for source in (sources or [])
        )
        result = create_story_workspace(
            project_root,
            story_id or name,
            title=title or name,
            sources=resolved_sources,
        )
    except (OSError, SimctlError) as e:
        typer.echo(f"Error creating story workspace: {e}", err=True)
        raise typer.Exit(code=1) from None

    typer.echo(f"Story workspace created: {result.story_dir}")
    typer.echo(f"  ID: {result.story_id}")
    typer.echo(f"  Story: {result.story_path}")
    typer.echo(f"  Sources: {result.source_count}")


def audit_story(
    story_dir: Path = typer.Argument(
        None,
        help="Story workspace directory (defaults to cwd).",
    ),
) -> None:
    """Audit a story workspace against indexed analysis artifacts."""
    if story_dir is None:
        story_dir = Path.cwd()
    elif not story_dir.is_absolute():
        story_dir = Path.cwd() / story_dir

    try:
        result = audit_story_workspace(story_dir)
    except (OSError, SimctlError) as e:
        typer.echo(f"Error auditing story: {e}", err=True)
        raise typer.Exit(code=1) from None

    typer.echo(f"Audit: {result.audit_md_path}")
    typer.echo(f"  JSON: {result.audit_json_path}")
    typer.echo(f"  Story: {result.story_id}")
    typer.echo(f"  Status: {result.overall_status}")
    if result.warnings:
        typer.echo(f"  Warnings: {len(result.warnings)}")


def export(
    target: str = typer.Argument(
        None,
        help="Run directory, run_id, or survey directory (defaults to cwd).",
    ),
    paper_id: str = typer.Option(
        ...,
        "--paper",
        help="Paper/manuscript identifier used under exports/papers/<paper-id>/.",
    ),
    name: str = typer.Option(
        "",
        "--name",
        help=(
            "Optional export slot name. Defaults to a target-derived timestamped name."
        ),
    ),
    mode: str = typer.Option(
        "copy",
        "--mode",
        help="Export mode: copy or symlink.",
    ),
    include_figures: bool = typer.Option(
        True,
        "--include-figures/--no-figures",
        help="Include run-level figure artifacts referenced by analysis outputs.",
    ),
    include_plots: bool = typer.Option(
        True,
        "--include-plots/--no-plots",
        help=(
            "Include survey summary plots under summary/plots/ when exporting a survey."
        ),
    ),
    paper_status: str = typer.Option(
        "",
        "--paper-status",
        help=(
            "Override paper-facing status for exported runs: accepted, "
            "placeholder, retry_planned, excluded, or superseded."
        ),
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help=(
            "Replace an existing export directory when --name resolves to the "
            "same slot."
        ),
    ),
) -> None:
    """Create a paper-facing export bundle under exports/papers/."""
    target_path = _resolve_export_target(target, search_dir=Path.cwd())

    try:
        result = execute_action(
            "export_publication",
            target_path=target_path,
            paper_id=paper_id,
            export_name=name,
            mode=mode,
            include_figures=include_figures,
            include_plots=include_plots,
            paper_status=paper_status,
            force=force,
        )
    except (OSError, TypeError, json.JSONDecodeError, SimctlError) as e:
        typer.echo(f"Error exporting publication bundle: {e}", err=True)
        raise typer.Exit(code=1) from None

    if result.status is not ActionStatus.SUCCESS:
        typer.echo(f"Error exporting publication bundle: {result.message}", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"Export written: {result.data.get('export_dir', '')}")
    typer.echo(f"  Paper: {result.data.get('paper_id', '')}")
    typer.echo(f"  Target kind: {result.data.get('target_kind', '')}")
    typer.echo(f"  Source: {result.data.get('target_path', '')}")
    typer.echo(f"  Manifest: {result.data.get('manifest_path', '')}")
    typer.echo(f"  README: {result.data.get('readme_path', '')}")
    typer.echo(f"  Files: {result.data.get('file_count', 0)}")
    run_ids = result.data.get("source_run_ids", [])
    if run_ids:
        typer.echo(f"  Run IDs: {', '.join(run_ids)}")
    for warning in result.data.get("warnings", []):
        typer.echo(f"Warning: {warning}", err=True)
