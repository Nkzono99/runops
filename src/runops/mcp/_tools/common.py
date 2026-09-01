"""Shared helpers for runops MCP tool implementations."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from time import perf_counter
from typing import Any

from runops.core.discovery import discover_runs, require_run_directory, resolve_run
from runops.core.exceptions import SimctlError
from runops.core.manifest import ManifestData
from runops.core.project import ProjectConfig, find_project_root
from runops.mcp.schemas import now_iso

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


def _tool_start() -> tuple[str, float]:
    return now_iso(), perf_counter()


def _path_from_arg(path: str | None) -> Path:
    return Path(path).expanduser().resolve() if path else Path.cwd().resolve()


def _resolve_project_root(project_root: str | None) -> Path:
    start = _path_from_arg(project_root)
    if (start / "runops.toml").exists():
        return start
    return find_project_root(start)


def _resolve_run_dir(run: str, project_root: Path) -> Path:
    candidate = Path(run).expanduser()
    if candidate.is_absolute() and (candidate / "manifest.toml").exists():
        return _require_project_run(candidate, project_root)
    relative = (project_root / candidate).resolve()
    if (relative / "manifest.toml").exists():
        return _require_project_run(relative, project_root)
    cwd_relative = (Path.cwd() / candidate).resolve()
    if (cwd_relative / "manifest.toml").exists():
        return _require_project_run(cwd_relative, project_root)
    return resolve_run(run, project_root / "runs")


def _require_project_run(candidate: Path, project_root: Path) -> Path:
    resolved = require_run_directory(candidate)
    try:
        resolved.relative_to((project_root / "runs").resolve())
    except ValueError as exc:
        raise SimctlError(
            f"Run path is outside the project runs/ namespace: {resolved}"
        ) from exc
    return resolved


def _run_summary(
    run_dir: Path,
    manifest: ManifestData,
    project_root: Path,
) -> dict[str, Any]:
    tags = manifest.classification.get("tags", [])
    if not isinstance(tags, list):
        tags = []
    return {
        "run_id": str(manifest.run.get("id", run_dir.name)),
        "display_name": str(manifest.run.get("display_name", "")),
        "status": str(manifest.run.get("status", "unknown")),
        "path": str(run_dir),
        "relative_path": _relative_or_absolute(run_dir, project_root),
        "origin_case": str(manifest.origin.get("case", "")),
        "origin_survey": str(manifest.origin.get("survey", "")),
        "job_id": str(manifest.job.get("job_id", "")),
        "tags": [str(tag) for tag in tags],
    }


def _relative_or_absolute(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _project_config_payload(project: ProjectConfig) -> dict[str, Any]:
    return {
        "name": project.name,
        "description": project.description,
        "root": str(project.root_dir),
        "simulators": sorted(project.simulators.keys()),
        "launchers": sorted(project.launchers.keys()),
        "knowledge_enabled": (
            project.knowledge.enabled if project.knowledge is not None else False
        ),
    }


def _find_latest_log(work_dir: Path, patterns: list[str]) -> Path | None:
    if not work_dir.is_dir():
        return None
    candidates: list[Path] = []
    for pattern in patterns:
        candidates.extend(path for path in work_dir.glob(pattern) if path.is_file())
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _tail_text(path: Path, lines: int) -> list[str]:
    content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return content[-lines:] if len(content) > lines else content


def _safe_limit(limit: int, *, default: int = 100, maximum: int = 1000) -> int:
    if limit <= 0:
        return default
    return min(limit, maximum)


def _load_json_object(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise SimctlError(f"Invalid JSON object at {path}")
    return data


def _load_toml_object(path: Path) -> dict[str, Any]:
    with open(path, "rb") as f:
        data = tomllib.load(f)
    if not isinstance(data, dict):
        raise SimctlError(f"Invalid TOML object at {path}")
    return data


def _slugify_token(value: str) -> str:
    text = value.strip().lower()
    chars: list[str] = []
    last_dash = False
    for ch in text:
        if ch.isalnum():
            chars.append(ch)
            last_dash = False
            continue
        if (ch in {"-", "_", ".", "/"} or ch.isspace()) and not last_dash:
            chars.append("-")
            last_dash = True
    return "".join(chars).strip("-")


def _clean_string(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text for item in value if (text := _clean_string(item))]


def _publication_manifest_row(
    project_root: Path,
    export_dir: Path,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    export_section = manifest.get("export", {})
    if not isinstance(export_section, dict):
        export_section = {}
    paper_section = manifest.get("paper", {})
    if not isinstance(paper_section, dict):
        paper_section = {}

    paper_id = str(
        manifest.get("paper_id") or paper_section.get("id") or export_dir.parent.name
    )
    export_name = str(
        manifest.get("export_name") or export_section.get("name") or export_dir.name
    )
    export_id = str(export_section.get("id") or f"{paper_id}/{export_name}")
    manifest_warnings = manifest.get("warnings", [])
    if not isinstance(manifest_warnings, list):
        manifest_warnings = []

    return {
        "id": export_id,
        "paper_id": paper_id,
        "export_name": export_name,
        "target_kind": str(manifest.get("target_kind", "")),
        "source_run_ids": _normalize_string_list(manifest.get("source_run_ids", [])),
        "created_at": str(
            manifest.get("created_at") or export_section.get("created_at") or ""
        ),
        "manifest_path": _relative_or_absolute(
            export_dir / "manifest.json", project_root
        ),
        "manifest_abspath": str(export_dir / "manifest.json"),
        "readme_path": _relative_or_absolute(export_dir / "README.md", project_root),
        "readme_abspath": str(export_dir / "README.md"),
        "warning_count": len(manifest_warnings),
        "valid": True,
    }


def _broken_publication_export_row(
    project_root: Path,
    export_dir: Path,
    message: str,
) -> dict[str, Any]:
    paper_id = export_dir.parent.name
    export_name = export_dir.name
    return {
        "id": f"{paper_id}/{export_name}",
        "paper_id": paper_id,
        "export_name": export_name,
        "target_kind": "",
        "source_run_ids": [],
        "created_at": "",
        "manifest_path": _relative_or_absolute(
            export_dir / "manifest.json", project_root
        ),
        "manifest_abspath": str(export_dir / "manifest.json"),
        "readme_path": _relative_or_absolute(export_dir / "README.md", project_root),
        "readme_abspath": str(export_dir / "README.md"),
        "warning_count": 1,
        "valid": False,
        "error": message,
    }


def _resolve_publication_export_dir(
    project_root: Path,
    *,
    export: str | None,
    paper_id: str | None,
    name: str | None,
) -> Path:
    if export:
        candidate = Path(export).expanduser()
        if candidate.is_absolute() and candidate.is_dir():
            return candidate.resolve()
        relative = (project_root / candidate).resolve()
        if relative.is_dir():
            return relative
        parts = export.replace("\\", "/").strip("/").split("/")
        if len(parts) == 2:
            return (
                project_root
                / "exports"
                / "papers"
                / _slugify_token(parts[0])
                / _slugify_token(parts[1])
            ).resolve()

    if paper_id and name:
        return (
            project_root
            / "exports"
            / "papers"
            / _slugify_token(paper_id)
            / _slugify_token(name)
        ).resolve()

    raise SimctlError("Specify export or paper_id + name.")


def _resolve_run_or_survey_target(target: str, project_root: Path) -> tuple[str, Path]:
    candidate = Path(target).expanduser()
    candidates: list[Path] = []
    if candidate.is_absolute():
        candidates.append(candidate.resolve())
    else:
        candidates.append((project_root / candidate).resolve())
        candidates.append((Path.cwd() / candidate).resolve())

    for path in candidates:
        if (path / "manifest.toml").is_file():
            return "run", path
        if path.is_dir() and discover_runs(path):
            return "survey", path

    run_dir = resolve_run(target, project_root / "runs")
    return "run", run_dir


def _resolve_survey_dir(survey: str, project_root: Path) -> Path:
    kind, path = _resolve_run_or_survey_target(survey, project_root)
    if kind != "survey":
        raise SimctlError(f"Target is not a survey directory: {survey}")
    return path


def _artifact_payload(
    project_root: Path,
    base_dir: Path,
    artifact: dict[str, Any],
) -> dict[str, Any]:
    payload = dict(artifact)
    rel_path = str(artifact.get("path", "")).strip()
    payload["relative_path"] = rel_path
    if rel_path:
        artifact_path = (base_dir / rel_path).resolve()
        payload["absolute_path"] = str(artifact_path)
        payload["project_relative_path"] = _relative_or_absolute(
            artifact_path,
            project_root,
        )
    else:
        payload["absolute_path"] = ""
        payload["project_relative_path"] = ""
    return payload


def _flatten_mapping(data: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in data.items():
        flat_key = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            flat.update(_flatten_mapping(value, flat_key))
            continue
        flat[flat_key] = value
    return flat


def _survey_plot_columns_from_aggregate(aggregate: dict[str, Any]) -> list[str]:
    columns: set[str] = set()
    runs = aggregate.get("runs", [])
    if isinstance(runs, list):
        for item in runs:
            if not isinstance(item, dict):
                continue
            row = {
                "run_id": item.get("run_id", ""),
                "display_name": item.get("display_name", ""),
                "status": item.get("status", ""),
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
                if key in item:
                    row[key] = item[key]
            flat_metadata = item.get("flat_metadata", {})
            if isinstance(flat_metadata, dict):
                row.update(flat_metadata)
            flat_summary = item.get("flat_summary", {})
            if isinstance(flat_summary, dict):
                row.update(flat_summary)
            columns.update(row)

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
