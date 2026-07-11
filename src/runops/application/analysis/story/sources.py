"""Story source discovery and artifact normalization."""

from __future__ import annotations

import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from runops.application.analysis.artifacts import read_artifacts_index
from runops.core.discovery import discover_runs
from runops.core.exceptions import SimctlError

from .models import ArtifactRecord, SourceKind, StorySource

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

_SUMMARY_FIELDS = frozenset(
    {
        "kind",
        "path",
        "title",
        "description",
        "status",
        "source_scope",
        "source_index",
        "run_id",
        "quantity",
    }
)


@dataclass(frozen=True)
class SourceCollection:
    """Artifacts and warnings collected from one Story source."""

    artifacts: tuple[ArtifactRecord, ...]
    warnings: tuple[str, ...]


def artifact_record(payload: Mapping[str, object]) -> ArtifactRecord:
    """Normalize an external artifact mapping for typed matching."""
    return ArtifactRecord(
        kind=_text(payload.get("kind")),
        path=_text(payload.get("path")),
        title=_text(payload.get("title")),
        description=_text(payload.get("description")),
        status=_text(payload.get("status"), default="draft"),
        source_scope=_text(payload.get("source_scope")),
        source_index=_text(payload.get("source_index")),
        run_id=_text(payload.get("run_id")),
        quantity=_text(payload.get("quantity")),
        name=_text(payload.get("name")),
        artifact_id=_text(payload.get("id")),
        tags=_string_list(payload.get("tags", [])),
        present_fields=frozenset(_SUMMARY_FIELDS & payload.keys()),
    )


def source_from_path(project_root: Path, source_path: Path) -> StorySource:
    """Resolve a user-provided source relative to the project root."""
    resolved = (
        source_path.resolve()
        if source_path.is_absolute()
        else (project_root / source_path).resolve()
    )
    kind: SourceKind = detect_source_kind(resolved) if resolved.exists() else "path"
    return StorySource(
        kind=kind,
        path=display_path(resolved, base=project_root),
    )


def collect_source_artifacts(
    project_root: Path,
    source: StorySource,
) -> SourceCollection:
    """Collect normalized artifacts from one declared source."""
    source_path = resolve_source_path(project_root, source.path)
    if not source_path.exists():
        return SourceCollection(
            artifacts=(),
            warnings=(f"Story source not found: {source.path}",),
        )

    detected_kind = detect_source_kind(source_path)
    if source.kind != detected_kind:
        raise SimctlError(
            "story source kind mismatch for "
            f"{source.path}: declared {source.kind!r}, "
            f"detected {detected_kind!r}"
        )

    artifacts: list[ArtifactRecord] = []
    warnings: list[str] = []
    if detected_kind == "run":
        artifacts.extend(_read_run_artifacts(source_path, project_root=project_root))
        if not artifacts:
            warnings.append(f"No artifact index found for source: {source.path}")
        return SourceCollection(tuple(artifacts), tuple(warnings))

    if detected_kind == "comparison":
        artifacts.extend(
            _read_comparison_artifacts(source_path, project_root=project_root)
        )
        if not artifacts:
            warnings.append(f"No artifact index found for source: {source.path}")
        return SourceCollection(tuple(artifacts), tuple(warnings))

    summary_index = source_path / "summary" / "artifacts.toml"
    if summary_index.is_file():
        artifacts.extend(
            _read_index_artifacts(
                summary_index,
                project_root=project_root,
                source_scope=display_path(source_path, base=project_root),
                base_dir=summary_index.parent,
            )
        )

    root_index = source_path / "artifacts.toml"
    if detected_kind == "path" and root_index.is_file():
        artifacts.extend(
            _read_index_artifacts(
                root_index,
                project_root=project_root,
                source_scope=display_path(source_path, base=project_root),
                base_dir=root_index.parent,
            )
        )

    run_dirs = discover_runs(source_path) if detected_kind == "survey" else []
    if run_dirs:
        for run_dir in run_dirs:
            artifacts.extend(_read_run_artifacts(run_dir, project_root=project_root))
        return SourceCollection(tuple(artifacts), tuple(warnings))

    if not summary_index.is_file() and not root_index.is_file():
        warnings.append(f"No artifact index found for source: {source.path}")
    return SourceCollection(tuple(artifacts), tuple(warnings))


def detect_source_kind(source_path: Path) -> SourceKind:
    """Return the structured source kind represented by a path."""
    manifest_path = source_path / "manifest.toml"
    if manifest_path.is_file():
        manifest = _read_toml_mapping(manifest_path)
        if isinstance(manifest.get("comparison"), dict):
            return "comparison"
        if isinstance(manifest.get("run"), dict):
            return "run"
    if (source_path / "survey.toml").is_file() or discover_runs(source_path):
        return "survey"
    return "path"


def resolve_source_path(project_root: Path, path: str) -> Path:
    """Resolve one stored source path from the project root."""
    source = Path(path)
    if source.is_absolute():
        return source
    return project_root / source


def display_path(path: Path, *, base: Path) -> str:
    """Render a project-relative path when possible."""
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _read_comparison_artifacts(
    comparison_dir: Path,
    *,
    project_root: Path,
) -> list[ArtifactRecord]:
    manifest_path = comparison_dir / "manifest.toml"
    manifest = _read_toml_mapping(manifest_path)
    raw_artifacts = manifest.get("artifacts", {})
    if not isinstance(raw_artifacts, dict):
        raise SimctlError(f"comparison artifacts must be a table: {manifest_path}")

    kind_by_group = {"figures": "figure", "data": "data", "scripts": "script"}
    source_scope = display_path(comparison_dir, base=project_root)
    rows: list[ArtifactRecord] = []
    for group, kind in kind_by_group.items():
        values = raw_artifacts.get(group, [])
        if not isinstance(values, list):
            raise SimctlError(
                f"comparison artifacts.{group} must be an array: {manifest_path}"
            )
        for index, value in enumerate(values, start=1):
            if isinstance(value, str) and value.strip():
                artifact_path = value.strip()
                row: dict[str, object] = {
                    "kind": kind,
                    "path": display_path(
                        comparison_dir / artifact_path,
                        base=project_root,
                    ),
                    "title": Path(artifact_path).stem,
                    "status": "draft",
                }
            elif isinstance(value, dict):
                row = dict(value)
                raw_path = row.get("path", "")
                if not isinstance(raw_path, str) or not raw_path.strip():
                    raise SimctlError(
                        f"comparison artifacts.{group}[{index}] is missing path"
                    )
                artifact_path = raw_path.strip()
                row.setdefault("kind", kind)
                row.setdefault("title", Path(artifact_path).stem)
                row.setdefault("status", "draft")
                row["path"] = display_path(
                    comparison_dir / artifact_path,
                    base=project_root,
                )
            else:
                raise SimctlError(
                    f"comparison artifacts.{group}[{index}] must be a path or table"
                )
            row["source_scope"] = source_scope
            row["source_index"] = display_path(manifest_path, base=project_root)
            rows.append(artifact_record(row))
    return rows


def _read_toml_mapping(path: Path) -> dict[str, Any]:
    try:
        with open(path, "rb") as stream:
            payload = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise SimctlError(f"Failed to read TOML {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SimctlError(f"TOML root must be a table: {path}")
    return payload


def _read_run_artifacts(
    run_dir: Path,
    *,
    project_root: Path,
) -> list[ArtifactRecord]:
    index_path = run_dir / "analysis" / "artifacts.toml"
    if not index_path.is_file():
        return []
    return _read_index_artifacts(
        index_path,
        project_root=project_root,
        source_scope=display_path(run_dir, base=project_root),
        base_dir=index_path.parent,
    )


def _read_index_artifacts(
    index_path: Path,
    *,
    project_root: Path,
    source_scope: str,
    base_dir: Path,
) -> list[ArtifactRecord]:
    rows: list[ArtifactRecord] = []
    for artifact in read_artifacts_index(index_path):
        path = str(artifact.get("path", "")).strip()
        display = display_path(base_dir / path, base=project_root) if path else path
        row: dict[str, object] = dict(artifact)
        row["path"] = display
        row["source_scope"] = source_scope
        row["source_index"] = display_path(index_path, base=project_root)
        rows.append(artifact_record(row))
    return rows


def _text(value: object, *, default: str = "") -> str:
    return str(value or default)


def _string_list(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,) if value else ()
    if isinstance(value, list):
        return tuple(str(item) for item in value if str(item))
    return ()
