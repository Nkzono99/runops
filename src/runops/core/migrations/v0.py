"""v0 project-state migrations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from runops.core.analysis.artifacts import (
    build_survey_artifacts,
    collect_run_artifacts,
    read_artifacts_index,
    write_artifacts_index,
)
from runops.core.discovery import discover_runs
from runops.core.exceptions import SimctlError
from runops.core.manifest import read_manifest
from runops.core.migrations.models import Migration, MigrationContext, MigrationResult
from runops.templates import load_static


def registered_migrations() -> tuple[Migration, ...]:
    """Return v0 migrations in execution order."""
    return (
        Migration(
            version="v0",
            number="0001",
            title="Analysis artifact indexes",
            description=(
                "Create run-local and survey summary artifacts.toml indexes "
                "from existing analysis outputs."
            ),
            migration_type="compatible-generated",
            impact=("analysis-artifact",),
            human_gate=False,
            handler=apply_analysis_artifact_indexes,
        ),
        Migration(
            version="v0",
            number="0002",
            title="Research agenda scaffold",
            description=(
                "Backfill the research/ decision-ledger scaffold without "
                "overwriting existing files."
            ),
            migration_type="compatible-generated",
            impact=("research",),
            human_gate=False,
            handler=apply_research_agenda_scaffold,
        ),
        Migration(
            version="v0",
            number="0003",
            title="Remove legacy survey figure index",
            description=(
                "Delete summary/figures_index.json and remove its artifacts.toml "
                "entry after figures moved to artifacts.toml."
            ),
            migration_type="breaking-generated",
            impact=("analysis-artifact",),
            human_gate=False,
            handler=apply_remove_legacy_figure_index,
        ),
    )


def apply_analysis_artifact_indexes(context: MigrationContext) -> MigrationResult:
    """Create missing analysis artifact indexes for existing outputs."""
    project_root = context.project_root
    runs_dir = project_root / "runs"
    created: list[Path] = []
    updated: list[Path] = []
    planned: list[Path] = []
    skipped: list[str] = []
    warnings: list[str] = []

    for run_dir in discover_runs(runs_dir):
        summary_path = run_dir / "analysis" / "summary.json"
        if not summary_path.is_file():
            continue

        index_path = run_dir / "analysis" / "artifacts.toml"
        if index_path.exists() and not context.force:
            skipped.append(_display_path(index_path, project_root) + " exists")
            continue
        if context.dry_run:
            planned.append(index_path)
            continue

        existed = index_path.exists()
        try:
            run_summary = _read_json_object(summary_path)
            manifest = read_manifest(run_dir)
        except (OSError, json.JSONDecodeError, SimctlError, TypeError) as exc:
            warnings.append(f"{_display_path(summary_path, project_root)}: {exc}")
            continue

        artifacts = collect_run_artifacts(
            run_dir,
            run_summary,
            run_id=str(manifest.run.get("id", run_dir.name)),
            display_name=str(manifest.run.get("display_name", "")),
            project_root=project_root,
        )
        write_artifacts_index(
            index_path,
            scope="run",
            generated_by="runo migrate apply M0-0001",
            artifacts=artifacts,
        )
        if existed:
            updated.append(index_path)
        else:
            created.append(index_path)

    for summary_dir in _iter_summary_dirs(runs_dir):
        index_path = summary_dir / "artifacts.toml"
        if index_path.exists() and not context.force:
            skipped.append(_display_path(index_path, project_root) + " exists")
            continue

        artifacts = [
            artifact
            for artifact in build_survey_artifacts(
                summary_dir=summary_dir,
                run_artifacts=[],
            )
            if _artifact_exists(summary_dir, artifact)
        ]
        if not artifacts:
            continue
        if context.dry_run:
            planned.append(index_path)
            continue

        existed = index_path.exists()
        write_artifacts_index(
            index_path,
            scope="survey",
            generated_by="runo migrate apply M0-0001",
            artifacts=artifacts,
        )
        if existed:
            updated.append(index_path)
        else:
            created.append(index_path)

    status = _result_status(context, created, updated, planned)
    result_summary = _summary_for_artifact_indexes(created, updated, planned, skipped)
    return MigrationResult(
        migration_id="M0-0001",
        title="Analysis artifact indexes",
        status=status,
        summary=result_summary,
        created=tuple(_relative_paths(created, project_root)),
        updated=tuple(_relative_paths(updated, project_root)),
        planned=tuple(_relative_paths(planned, project_root)),
        skipped=tuple(skipped),
        warnings=tuple(warnings),
    )


def apply_research_agenda_scaffold(context: MigrationContext) -> MigrationResult:
    """Create missing research decision-layer scaffold files."""
    project_root = context.project_root
    targets = (
        _ScaffoldTarget(Path("research"), "dir"),
        _ScaffoldTarget(Path("research/proposals"), "dir"),
        _ScaffoldTarget(Path("research/reviews"), "dir"),
        _ScaffoldTarget(
            Path("research/README.md"), "file", "scaffold/research/README.md"
        ),
        _ScaffoldTarget(
            Path("research/agenda.md"), "file", "scaffold/research/agenda.md"
        ),
        _ScaffoldTarget(
            Path("research/proposals/.gitkeep"),
            "file",
            "scaffold/research/proposals/.gitkeep",
        ),
        _ScaffoldTarget(
            Path("research/reviews/.gitkeep"),
            "file",
            "scaffold/research/reviews/.gitkeep",
        ),
    )
    created: list[Path] = []
    planned: list[Path] = []
    skipped: list[str] = []

    for target in targets:
        path = project_root / target.relative_path
        if path.exists():
            skipped.append(target.relative_path.as_posix() + " exists")
            continue
        if context.dry_run:
            planned.append(path)
            continue
        if target.kind == "dir":
            path.mkdir(parents=True, exist_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            if target.template_path is None:
                path.touch()
            else:
                path.write_text(load_static(target.template_path), encoding="utf-8")
        created.append(path)

    status = _result_status(context, created, [], planned)
    summary = (
        "research/ scaffold is already present."
        if status == "skipped"
        else "Prepared research/ decision-ledger scaffold."
    )
    return MigrationResult(
        migration_id="M0-0002",
        title="Research agenda scaffold",
        status=status,
        summary=summary,
        created=tuple(_relative_paths(created, project_root)),
        planned=tuple(_relative_paths(planned, project_root)),
        skipped=tuple(skipped),
    )


def apply_remove_legacy_figure_index(context: MigrationContext) -> MigrationResult:
    """Remove legacy survey ``figures_index.json`` files and artifact entries."""
    project_root = context.project_root
    runs_dir = project_root / "runs"
    deleted: list[Path] = []
    updated: list[Path] = []
    planned: list[Path] = []
    skipped: list[str] = []
    warnings: list[str] = []

    for summary_dir in _iter_summary_dirs(runs_dir):
        legacy_path = summary_dir / "figures_index.json"
        artifacts_path = summary_dir / "artifacts.toml"

        if legacy_path.is_file():
            if context.dry_run:
                planned.append(legacy_path)
            else:
                try:
                    legacy_path.unlink()
                    deleted.append(legacy_path)
                except OSError as exc:
                    legacy_display = _display_path(legacy_path, project_root)
                    warnings.append(f"{legacy_display}: {exc}")
        else:
            skipped.append(_display_path(legacy_path, project_root) + " missing")

        if not artifacts_path.is_file():
            continue

        try:
            artifacts = read_artifacts_index(artifacts_path)
        except OSError as exc:
            warnings.append(f"{_display_path(artifacts_path, project_root)}: {exc}")
            continue

        filtered = [
            artifact
            for artifact in artifacts
            if str(artifact.get("path", "")).strip() != "figures_index.json"
        ]
        if len(filtered) == len(artifacts):
            continue
        if context.dry_run:
            planned.append(artifacts_path)
            continue

        write_artifacts_index(
            artifacts_path,
            scope="survey",
            generated_by="runo migrate apply M0-0003",
            artifacts=filtered,
        )
        updated.append(artifacts_path)

    status = _result_status(context, [], updated, planned, deleted=deleted)
    summary = _summary_for_legacy_figure_index(updated, deleted, planned, skipped)
    return MigrationResult(
        migration_id="M0-0003",
        title="Remove legacy survey figure index",
        status=status,
        summary=summary,
        updated=tuple(_relative_paths(updated, project_root)),
        deleted=tuple(_relative_paths(deleted, project_root)),
        planned=tuple(_relative_paths(planned, project_root)),
        skipped=tuple(skipped),
        warnings=tuple(warnings),
    )


class _ScaffoldTarget:
    def __init__(
        self,
        relative_path: Path,
        kind: str,
        template_path: str | None = None,
    ) -> None:
        self.relative_path = relative_path
        self.kind = kind
        self.template_path = template_path


def _read_json_object(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        msg = f"{path} must contain a JSON object"
        raise TypeError(msg)
    return payload


def _iter_summary_dirs(runs_dir: Path) -> list[Path]:
    if not runs_dir.is_dir():
        return []
    return sorted(
        path
        for path in runs_dir.rglob("summary")
        if path.is_dir() and any(child.is_file() for child in path.iterdir())
    )


def _artifact_exists(summary_dir: Path, artifact: dict[str, Any]) -> bool:
    rel_path = str(artifact.get("path", "")).strip()
    return bool(rel_path) and (summary_dir / rel_path).is_file()


def _relative_paths(paths: list[Path], project_root: Path) -> list[Path]:
    return [Path(_display_path(path, project_root)) for path in paths]


def _display_path(path: Path, project_root: Path) -> str:
    try:
        return path.relative_to(project_root).as_posix()
    except ValueError:
        return path.as_posix()


def _result_status(
    context: MigrationContext,
    created: list[Path],
    updated: list[Path],
    planned: list[Path],
    *,
    deleted: list[Path] | None = None,
) -> str:
    if context.dry_run and planned:
        return "planned"
    if created or updated or deleted:
        return "applied"
    return "skipped"


def _summary_for_artifact_indexes(
    created: list[Path],
    updated: list[Path],
    planned: list[Path],
    skipped: list[str],
) -> str:
    if planned:
        return f"Would create or update {len(planned)} artifact index file(s)."
    changed = len(created) + len(updated)
    if changed:
        return f"Created or updated {changed} artifact index file(s)."
    if skipped:
        return "Artifact indexes are already present."
    return "No existing analysis outputs needed artifact indexes."


def _summary_for_legacy_figure_index(
    updated: list[Path],
    deleted: list[Path],
    planned: list[Path],
    skipped: list[str],
) -> str:
    if planned:
        return f"Would remove or update {len(planned)} legacy figure index item(s)."
    changed = len(updated) + len(deleted)
    if changed:
        return f"Removed or updated {changed} legacy figure index item(s)."
    if skipped:
        return "No legacy figures_index.json files were present."
    return "No survey summary directories needed legacy figure index migration."
