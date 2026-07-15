"""Cross-run comparison workspace scaffolding."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import tomli_w

from runops.core.discovery import discover_runs
from runops.core.exceptions import SimctlError
from runops.core.manifest import read_manifest

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

_COMPARISON_ROOT = Path("research") / "results"
_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")


@dataclass(frozen=True)
class ComparisonWorkspaceResult:
    """Created cross-run comparison workspace."""

    comparison_id: str
    name: str
    comparison_dir: Path
    manifest_path: Path
    readme_path: Path
    source_count: int


def slugify_comparison_id(value: str) -> str:
    """Return a filesystem-safe comparison id."""
    text = value.strip().lower()
    chars: list[str] = []
    last_dash = False
    for ch in text:
        if ch.isascii() and ch.isalnum():
            chars.append(ch)
            last_dash = False
            continue
        if (ch in {"-", "_", "."} or ch.isspace()) and not last_dash:
            chars.append("-")
            last_dash = True
    slug = "".join(chars).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug


def _validate_comparison_id(value: str) -> str:
    comparison_id = value.strip()
    if not comparison_id:
        raise SimctlError("comparison id must be non-empty")
    if not _ID_PATTERN.match(comparison_id):
        raise SimctlError(
            "comparison id must start with a lowercase letter or digit and contain "
            "only lowercase letters, digits, '.', '_' or '-'"
        )
    return comparison_id


def _relative_to_project(project_root: Path, path: Path) -> str:
    resolved_project = project_root.resolve()
    resolved_path = path.resolve()
    try:
        return str(resolved_path.relative_to(resolved_project)).replace("\\", "/")
    except ValueError:
        return str(resolved_path)


def _source_record(project_root: Path, source_path: Path) -> dict[str, Any]:
    resolved = source_path.resolve()
    if not resolved.exists():
        raise SimctlError(f"comparison source not found: {source_path}")

    record: dict[str, Any] = {
        "path": _relative_to_project(project_root, resolved),
    }
    if (resolved / "manifest.toml").is_file():
        manifest = read_manifest(resolved)
        record["kind"] = "run"
        record["run_id"] = str(manifest.run.get("id", resolved.name))
        return record

    run_dirs = discover_runs(resolved)
    if (resolved / "survey.toml").is_file() or run_dirs:
        record["kind"] = "survey"
        record["run_ids"] = [
            str(read_manifest(run_dir).run.get("id", run_dir.name))
            for run_dir in run_dirs
        ]
        return record

    record["kind"] = "path"
    return record


def _write_comparison_readme(
    path: Path,
    *,
    comparison_id: str,
    name: str,
) -> None:
    lines = [
        f"# {name}",
        "",
        f"- Comparison ID: `{comparison_id}`",
        "- Manifest: `manifest.toml`",
        "- Scripts: `artifacts/scripts/`",
        "- Data/tables: `artifacts/data/`",
        "- Figures: `artifacts/figures/`",
        "",
        "Keep comparison-specific scripts and generated cross-run artifacts here.",
        "Reusable project-wide scripts can still live under the project `scripts/`",
        "directory; reference them from `manifest.toml` when they produce outputs",
        "for this comparison.",
        "",
        "Update `manifest.toml` when adding source runs/surveys, scripts, key",
        "parameters, figures, or data products.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def create_comparison_workspace(
    project_root: Path,
    *,
    name: str,
    comparison_id: str = "",
    sources: tuple[Path, ...] = (),
) -> ComparisonWorkspaceResult:
    """Create one durable comparison under ``research/results/``.

    Args:
        project_root: runops project root.
        name: Human-readable comparison name.
        comparison_id: Optional stable id.  Defaults to a slugified ``name``.
        sources: Optional run, survey, or path sources to record in the manifest.

    Returns:
        Created workspace metadata.

    Raises:
        SimctlError: If the name/id is invalid, source paths are missing, or the
            destination already exists.
    """
    normalized_name = name.strip()
    if not normalized_name:
        raise SimctlError("comparison name must be non-empty")

    resolved_id = comparison_id.strip() or slugify_comparison_id(normalized_name)
    resolved_id = _validate_comparison_id(resolved_id)

    root = project_root.resolve()
    results_root = root / _COMPARISON_ROOT
    results_root.mkdir(parents=True, exist_ok=True)
    for existing_manifest in results_root.glob("R[0-9][0-9][0-9][0-9]-*/manifest.toml"):
        try:
            with open(existing_manifest, "rb") as stream:
                existing = tomllib.load(stream)
        except (OSError, tomllib.TOMLDecodeError):
            continue
        comparison = existing.get("comparison")
        if isinstance(comparison, dict) and comparison.get("id") == resolved_id:
            raise SimctlError(
                f"comparison workspace already exists: {existing_manifest.parent}"
            )

    numbers = []
    for child in results_root.glob("R[0-9][0-9][0-9][0-9]-*"):
        try:
            numbers.append(int(child.name[1:5]))
        except ValueError:
            continue
    result_id = f"R{max(numbers, default=0) + 1:04d}-{resolved_id}"
    comparison_dir = results_root / result_id

    source_records = [_source_record(root, source) for source in sources]
    comparison_dir.mkdir(parents=True)
    artifacts_dir = comparison_dir / "artifacts"
    artifacts_dir.mkdir()
    for artifact_kind in ("scripts", "data", "figures"):
        child_dir = artifacts_dir / artifact_kind
        child_dir.mkdir()

    manifest_path = comparison_dir / "manifest.toml"
    readme_path = comparison_dir / "README.md"
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    manifest: dict[str, Any] = {
        "comparison": {
            "schema_version": 1,
            "id": resolved_id,
            "name": normalized_name,
            "created_at": created_at,
            "status": "draft",
            "description": "",
        },
        "sources": source_records,
        "paths": {
            "scripts": "artifacts/scripts",
            "data": "artifacts/data",
            "figures": "artifacts/figures",
        },
        "artifacts": {
            "scripts": [],
            "data": [],
            "figures": [],
        },
    }
    with open(manifest_path, "wb") as f:
        tomli_w.dump(manifest, f)
    _write_comparison_readme(
        readme_path,
        comparison_id=resolved_id,
        name=normalized_name,
    )

    return ComparisonWorkspaceResult(
        comparison_id=resolved_id,
        name=normalized_name,
        comparison_dir=comparison_dir,
        manifest_path=manifest_path,
        readme_path=readme_path,
        source_count=len(source_records),
    )
