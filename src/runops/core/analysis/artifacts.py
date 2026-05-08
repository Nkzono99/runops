"""Analysis artifact index helpers."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from os.path import relpath
from pathlib import Path
from typing import Any

import tomli_w

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

FIGURE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".pdf"}

_OPTIONAL_METADATA_FIELDS = (
    "caption",
    "quantity",
    "plane",
    "frame",
    "step",
    "unit",
    "normalization",
    "color_range",
)


def collect_run_artifacts(
    run_dir: Path,
    summary: dict[str, Any],
    *,
    run_id: str = "",
    display_name: str = "",
    script_path: Path | None = None,
    project_root: Path | None = None,
) -> list[dict[str, Any]]:
    """Collect run-local analysis artifacts from a summary and figure directory.

    Args:
        run_dir: Run directory containing ``analysis/``.
        summary: ``analysis/summary.json`` payload.
        run_id: Optional run identifier to attach to each artifact.
        display_name: Optional human-readable run display name.
        script_path: Optional project ``summarize.py`` path.
        project_root: Optional project root for script path display.

    Returns:
        Normalized artifact dictionaries.
    """
    artifacts: list[dict[str, Any]] = []
    seen_paths: set[str] = set()

    raw_figures = summary.get("figures", [])
    if isinstance(raw_figures, list):
        for item in raw_figures:
            artifact = _artifact_from_summary_figure(
                item,
                run_id=run_id,
                display_name=display_name,
                script_path=script_path,
                project_root=project_root,
            )
            if artifact is None:
                continue
            seen_paths.add(str(artifact["path"]))
            artifacts.append(artifact)

    auto_fig_dir = run_dir / "analysis" / "figures"
    if auto_fig_dir.is_dir():
        for path in sorted(auto_fig_dir.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in FIGURE_EXTENSIONS:
                continue
            rel_path = path.relative_to(run_dir / "analysis").as_posix()
            if rel_path in seen_paths:
                continue
            seen_paths.add(rel_path)
            artifacts.append(
                _clean_artifact(
                    {
                        "kind": "figure",
                        "path": rel_path,
                        "title": _title_from_path(rel_path),
                        "description": "",
                        "status": "draft",
                        "script": _display_path(script_path, base=project_root),
                        "data": [],
                        "run_id": run_id,
                        "display_name": display_name,
                    }
                )
            )

    return artifacts


def figures_from_artifacts(artifacts: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Return figure rows compatible with the legacy figures index."""
    figures: list[dict[str, str]] = []
    for artifact in artifacts:
        if str(artifact.get("kind", "")) != "figure":
            continue
        path = str(artifact.get("path", "")).strip()
        if not path:
            continue
        caption = str(
            artifact.get("caption")
            or artifact.get("description")
            or artifact.get("title")
            or ""
        )
        figures.append({"path": path, "caption": caption})
    return figures


def read_artifacts_index(index_path: Path) -> list[dict[str, Any]]:
    """Read ``artifacts.toml`` and return its artifact rows."""
    with open(index_path, "rb") as f:
        raw = tomllib.load(f)
    artifacts = raw.get("artifacts", [])
    if not isinstance(artifacts, list):
        return []
    return [item for item in artifacts if isinstance(item, dict)]


def write_artifacts_index(
    index_path: Path,
    *,
    scope: str,
    generated_by: str,
    artifacts: list[dict[str, Any]],
) -> None:
    """Write an ``artifacts.toml`` index."""
    index_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "schema_version": 1,
        "scope": scope,
        "generated_by": generated_by,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "artifacts": [_clean_artifact(artifact) for artifact in artifacts],
    }
    with open(index_path, "wb") as f:
        tomli_w.dump(payload, f)


def build_survey_artifacts(
    *,
    summary_dir: Path,
    run_artifacts: list[dict[str, Any]],
    include_summary_outputs: bool = True,
) -> list[dict[str, Any]]:
    """Build survey-level artifact rows relative to ``summary_dir``."""
    artifacts: list[dict[str, Any]] = []
    if include_summary_outputs:
        artifacts.extend(
            [
                {
                    "kind": "table",
                    "path": "survey_summary.csv",
                    "title": "Survey summary CSV",
                    "description": "Flat table of collected run summaries.",
                    "status": "draft",
                },
                {
                    "kind": "data",
                    "path": "survey_summary.json",
                    "title": "Survey summary JSON",
                    "description": "Structured aggregate of collected run summaries.",
                    "status": "draft",
                },
                {
                    "kind": "data",
                    "path": "figures_index.json",
                    "title": "Legacy figure index",
                    "description": "Figure-only compatibility index.",
                    "status": "draft",
                },
                {
                    "kind": "report",
                    "path": "survey_summary.md",
                    "title": "Survey summary report",
                    "description": "Human-readable survey summary report.",
                    "status": "draft",
                },
            ]
        )

    artifacts.extend(_clean_artifact(artifact) for artifact in run_artifacts)
    return artifacts


def artifact_path_relative_to_summary(
    survey_dir: Path,
    summary_dir: Path,
    artifact_path: str,
) -> str:
    """Convert a survey-relative artifact path to a summary-relative path."""
    absolute = survey_dir / artifact_path
    return relpath(absolute, summary_dir).replace("\\", "/")


def _artifact_from_summary_figure(
    item: Any,
    *,
    run_id: str,
    display_name: str,
    script_path: Path | None,
    project_root: Path | None,
) -> dict[str, Any] | None:
    rel_path = ""
    metadata: dict[str, Any] = {}
    if isinstance(item, dict):
        rel_path = str(item.get("path", "")).strip()
        metadata = dict(item)
    elif isinstance(item, str):
        rel_path = item.strip()
    if not rel_path:
        return None

    caption = str(metadata.get("caption", "")).strip()
    description = str(metadata.get("description", "") or caption).strip()
    title = str(metadata.get("title", "") or caption or _title_from_path(rel_path))
    artifact: dict[str, Any] = {
        "kind": str(metadata.get("kind", "figure") or "figure"),
        "path": rel_path,
        "title": title,
        "description": description,
        "status": str(metadata.get("status", "draft") or "draft"),
        "script": str(
            metadata.get("script") or _display_path(script_path, base=project_root)
        ),
        "data": _coerce_string_list(metadata.get("data", [])),
        "run_id": run_id,
        "display_name": display_name,
    }
    for field in _OPTIONAL_METADATA_FIELDS:
        if field in metadata:
            artifact[field] = metadata[field]
    return _clean_artifact(artifact)


def _clean_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in artifact.items():
        if value in ("", None):
            continue
        if isinstance(value, list):
            cleaned[key] = [str(item) for item in value if str(item)]
            continue
        cleaned[key] = value
    return cleaned


def _coerce_string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    return []


def _display_path(path: Path | None, *, base: Path | None = None) -> str:
    if path is None:
        return ""
    if base is not None:
        try:
            return path.relative_to(base).as_posix()
        except ValueError:
            pass
    return path.as_posix()


def _title_from_path(path: str) -> str:
    return Path(path).stem.replace("_", " ").replace("-", " ")
