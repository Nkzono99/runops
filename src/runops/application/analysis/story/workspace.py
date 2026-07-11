"""Story acceptance audit workspace helpers."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import tomli_w

from runops.application.analysis.artifacts import read_artifacts_index
from runops.core.discovery import discover_runs
from runops.core.exceptions import ProjectNotFoundError, SimctlError
from runops.core.project import find_project_root

from .models import SourceKind, StorySource, StorySpec, StoryStep
from .schema import read_story_spec, story_spec_payload, validate_story_id

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

_STORIES_ROOT = Path("analysis") / "stories"
_DEFAULT_MATURITY = ("main", "accepted", "draft")


@dataclass(frozen=True)
class StoryWorkspaceResult:
    """Created story acceptance audit workspace."""

    story_id: str
    title: str
    story_dir: Path
    story_path: Path
    source_count: int


@dataclass(frozen=True)
class StoryAuditResult:
    """Generated story acceptance audit outputs."""

    story_id: str
    title: str
    story_dir: Path
    audit_json_path: Path
    audit_md_path: Path
    overall_status: str
    steps: list[dict[str, Any]]
    warnings: list[str]


def slugify_story_id(value: str) -> str:
    """Return a filesystem-safe story id."""
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


def create_story_workspace(
    project_root: Path,
    name: str,
    *,
    story_id: str = "",
    title: str = "",
    sources: tuple[Path, ...] = (),
) -> StoryWorkspaceResult:
    """Create ``analysis/stories/<story_id>/`` with a starter story spec.

    Args:
        project_root: runops project root.
        name: Human-readable story name.
        story_id: Optional stable story id. Defaults to a slug or stable hash.
        title: Optional human-readable story title.
        sources: Optional run, survey, or path sources to record.

    Returns:
        Created workspace metadata.

    Raises:
        SimctlError: If the story id is invalid or the destination exists.
    """
    root = project_root.resolve()
    normalized_name = name.strip()
    if not normalized_name:
        raise SimctlError("story name must be non-empty")
    generated_id = slugify_story_id(normalized_name)
    if not generated_id:
        digest = hashlib.sha256(normalized_name.encode("utf-8")).hexdigest()[:10]
        generated_id = f"story-{digest}"
    resolved_id = validate_story_id(story_id or generated_id)
    story_title = title.strip() or normalized_name
    story_dir = root / _STORIES_ROOT / resolved_id
    if story_dir.exists():
        raise SimctlError(f"story workspace already exists: {story_dir}")

    story_dir.mkdir(parents=True)
    story_path = story_dir / "story.toml"
    source_records = [_source_record(root, source) for source in sources]
    spec = StorySpec(
        schema_version=1,
        id=resolved_id,
        title=story_title,
        status="draft",
        sources=tuple(
            StorySource(
                kind=cast(SourceKind, record["kind"]),
                path=record["path"],
            )
            for record in source_records
        ),
        steps=(
            StoryStep(
                id="first-step",
                title="First story step",
                required_artifacts=("figure:replace_with_artifact_name",),
                acceptable_status=_DEFAULT_MATURITY,
            ),
        ),
    )
    with open(story_path, "wb") as f:
        tomli_w.dump(story_spec_payload(spec), f)

    return StoryWorkspaceResult(
        story_id=resolved_id,
        title=story_title,
        story_dir=story_dir,
        story_path=story_path,
        source_count=len(sources),
    )


def audit_story_workspace(story_dir: Path) -> StoryAuditResult:
    """Audit a story workspace and write ``audit.json`` and ``audit.md``.

    Args:
        story_dir: Directory containing ``story.toml``.

    Returns:
        Generated audit metadata and per-step results.

    Raises:
        SimctlError: If the story spec is missing or invalid.
    """
    story_root = story_dir.resolve()
    story_path = story_root / "story.toml"
    if not story_path.is_file():
        raise SimctlError(f"story.toml not found: {story_path}")

    project_root = _find_project_root_for_story(story_root)
    spec = read_story_spec(story_path, default_id=story_root.name)
    steps = [_legacy_step(step) for step in spec.steps]
    source_records = [
        {"kind": source.kind, "path": source.path} for source in spec.sources
    ]

    artifacts: list[dict[str, Any]] = []
    warnings: list[str] = []
    for source in source_records:
        source_artifacts, source_warnings = _collect_source_artifacts(
            project_root,
            source,
        )
        artifacts.extend(source_artifacts)
        warnings.extend(source_warnings)

    source_blocked = any(
        warning.startswith("Story source not found:") for warning in warnings
    )
    step_results = [
        _audit_step(step, artifacts, source_blocked=source_blocked) for step in steps
    ]
    overall_status = _overall_status(step_results, warnings)
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    audit_payload: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": generated_at,
        "story": {
            "id": spec.id,
            "title": spec.title,
            "status": spec.status,
            "path": _display_path(story_path, base=project_root),
        },
        "sources": source_records,
        "overall_status": overall_status,
        "warnings": warnings,
        "steps": step_results,
    }

    audit_json_path = story_root / "audit.json"
    audit_md_path = story_root / "audit.md"
    audit_json_path.write_text(
        json.dumps(audit_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    audit_md_path.write_text(
        _render_audit_markdown(
            title=spec.title,
            overall_status=overall_status,
            generated_at=generated_at,
            steps=step_results,
            warnings=warnings,
        ),
        encoding="utf-8",
    )

    return StoryAuditResult(
        story_id=spec.id,
        title=spec.title,
        story_dir=story_root,
        audit_json_path=audit_json_path,
        audit_md_path=audit_md_path,
        overall_status=overall_status,
        steps=step_results,
        warnings=warnings,
    )


def _legacy_step(step: StoryStep) -> dict[str, Any]:
    return {
        "id": step.id,
        "title": step.title,
        "required_artifacts": list(step.required_artifacts),
        "acceptable_status": list(step.acceptable_status),
        "claim_ceiling": step.claim_ceiling,
        "notes": step.notes,
    }


def _source_record(project_root: Path, source_path: Path) -> dict[str, str]:
    resolved = (
        source_path.resolve()
        if source_path.is_absolute()
        else (project_root / source_path).resolve()
    )
    path = _display_path(resolved, base=project_root)
    kind = _detect_source_kind(resolved) if resolved.exists() else "path"
    return {"kind": kind, "path": path}


def _collect_source_artifacts(
    project_root: Path,
    source: dict[str, str],
) -> tuple[list[dict[str, Any]], list[str]]:
    source_path = _resolve_source_path(project_root, source["path"])
    if not source_path.exists():
        return [], [f"Story source not found: {source['path']}"]

    detected_kind = _detect_source_kind(source_path)
    if source["kind"] != detected_kind:
        raise SimctlError(
            "story source kind mismatch for "
            f"{source['path']}: declared {source['kind']!r}, "
            f"detected {detected_kind!r}"
        )

    artifacts: list[dict[str, Any]] = []
    warnings: list[str] = []
    if detected_kind == "run":
        artifacts.extend(_read_run_artifacts(source_path, project_root=project_root))
        if not artifacts:
            warnings.append(f"No artifact index found for source: {source['path']}")
        return artifacts, warnings

    if detected_kind == "comparison":
        artifacts.extend(
            _read_comparison_artifacts(source_path, project_root=project_root)
        )
        if not artifacts:
            warnings.append(f"No artifact index found for source: {source['path']}")
        return artifacts, warnings

    summary_index = source_path / "summary" / "artifacts.toml"
    if summary_index.is_file():
        artifacts.extend(
            _read_index_artifacts(
                summary_index,
                project_root=project_root,
                source_scope=_display_path(source_path, base=project_root),
                base_dir=summary_index.parent,
            )
        )

    root_index = source_path / "artifacts.toml"
    if detected_kind == "path" and root_index.is_file():
        artifacts.extend(
            _read_index_artifacts(
                root_index,
                project_root=project_root,
                source_scope=_display_path(source_path, base=project_root),
                base_dir=root_index.parent,
            )
        )

    run_dirs = discover_runs(source_path) if detected_kind == "survey" else []
    if run_dirs:
        for run_dir in run_dirs:
            artifacts.extend(_read_run_artifacts(run_dir, project_root=project_root))
        return artifacts, warnings

    if not summary_index.is_file() and not root_index.is_file():
        warnings.append(f"No artifact index found for source: {source['path']}")
    return artifacts, warnings


def _detect_source_kind(source_path: Path) -> str:
    """Return the structured source kind represented by ``source_path``."""
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


def _read_comparison_artifacts(
    comparison_dir: Path,
    *,
    project_root: Path,
) -> list[dict[str, Any]]:
    """Read lightweight artifact entries from a comparison manifest."""
    manifest_path = comparison_dir / "manifest.toml"
    manifest = _read_toml_mapping(manifest_path)
    raw_artifacts = manifest.get("artifacts", {})
    if not isinstance(raw_artifacts, dict):
        raise SimctlError(f"comparison artifacts must be a table: {manifest_path}")

    kind_by_group = {"figures": "figure", "data": "data", "scripts": "script"}
    source_scope = _display_path(comparison_dir, base=project_root)
    rows: list[dict[str, Any]] = []
    for group, kind in kind_by_group.items():
        values = raw_artifacts.get(group, [])
        if not isinstance(values, list):
            raise SimctlError(
                f"comparison artifacts.{group} must be an array: {manifest_path}"
            )
        for index, value in enumerate(values, start=1):
            if isinstance(value, str) and value.strip():
                artifact_path = value.strip()
                row: dict[str, Any] = {
                    "kind": kind,
                    "path": _display_path(
                        comparison_dir / artifact_path,
                        base=project_root,
                    ),
                    "title": Path(artifact_path).stem,
                    "status": "draft",
                }
            elif isinstance(value, dict):
                row = dict(value)
                artifact_path = row.get("path", "")
                if not isinstance(artifact_path, str) or not artifact_path.strip():
                    raise SimctlError(
                        f"comparison artifacts.{group}[{index}] is missing path"
                    )
                row.setdefault("kind", kind)
                row.setdefault("title", Path(artifact_path).stem)
                row.setdefault("status", "draft")
                row["path"] = _display_path(
                    comparison_dir / artifact_path,
                    base=project_root,
                )
            else:
                raise SimctlError(
                    f"comparison artifacts.{group}[{index}] must be a path or table"
                )
            row["source_scope"] = source_scope
            row["source_index"] = _display_path(
                manifest_path,
                base=project_root,
            )
            rows.append(row)
    return rows


def _read_toml_mapping(path: Path) -> dict[str, Any]:
    """Read one TOML mapping and translate parser errors to ``SimctlError``."""
    try:
        with open(path, "rb") as f:
            payload = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise SimctlError(f"Failed to read TOML {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SimctlError(f"TOML root must be a table: {path}")
    return payload


def _read_run_artifacts(run_dir: Path, *, project_root: Path) -> list[dict[str, Any]]:
    index_path = run_dir / "analysis" / "artifacts.toml"
    if not index_path.is_file():
        return []
    return _read_index_artifacts(
        index_path,
        project_root=project_root,
        source_scope=_display_path(run_dir, base=project_root),
        base_dir=index_path.parent,
    )


def _read_index_artifacts(
    index_path: Path,
    *,
    project_root: Path,
    source_scope: str,
    base_dir: Path,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for artifact in read_artifacts_index(index_path):
        path = str(artifact.get("path", "")).strip()
        display_path = path
        if path:
            display_path = _display_path(base_dir / path, base=project_root)
        row = dict(artifact)
        row["path"] = display_path
        row["source_scope"] = source_scope
        row["source_index"] = _display_path(index_path, base=project_root)
        rows.append(row)
    return rows


def _audit_step(
    step: dict[str, Any],
    artifacts: list[dict[str, Any]],
    *,
    source_blocked: bool = False,
) -> dict[str, Any]:
    matched: list[dict[str, Any]] = []
    weak: list[dict[str, Any]] = []
    missing: list[str] = list(step["required_artifacts"]) if source_blocked else []
    acceptable = set(step["acceptable_status"])

    if source_blocked:
        return {
            "id": step["id"],
            "title": step["title"],
            "status": "blocked",
            "required_artifacts": list(step["required_artifacts"]),
            "acceptable_status": list(step["acceptable_status"]),
            "matched_artifacts": matched,
            "weak_artifacts": weak,
            "missing_artifacts": missing,
            "claim_ceiling": step["claim_ceiling"],
            "notes": step["notes"],
        }

    for selector in step["required_artifacts"]:
        selector_matches = [
            artifact for artifact in artifacts if _artifact_matches(selector, artifact)
        ]
        accepted = [
            artifact
            for artifact in selector_matches
            if str(artifact.get("status", "draft") or "draft") in acceptable
        ]
        if accepted:
            matched.extend(
                _artifact_summary(artifact, selector) for artifact in accepted
            )
            continue
        if selector_matches:
            weak.extend(
                _artifact_summary(artifact, selector) for artifact in selector_matches
            )
            continue
        missing.append(selector)

    if missing:
        status = "partial" if matched or weak else "missing"
    elif weak:
        status = "partial"
    else:
        status = "covered"

    return {
        "id": step["id"],
        "title": step["title"],
        "status": status,
        "required_artifacts": list(step["required_artifacts"]),
        "acceptable_status": list(step["acceptable_status"]),
        "matched_artifacts": matched,
        "weak_artifacts": weak,
        "missing_artifacts": missing,
        "claim_ceiling": step["claim_ceiling"],
        "notes": step["notes"],
    }


def _artifact_matches(selector: str, artifact: dict[str, Any]) -> bool:
    kind, name = _parse_selector(selector)
    artifact_kind = _normalize_token(str(artifact.get("kind", "")))
    if kind and _normalize_token(kind) != artifact_kind:
        return False

    target = _normalize_token(name)
    candidates = {
        _normalize_token(str(artifact.get("name", ""))),
        _normalize_token(str(artifact.get("id", ""))),
        _normalize_token(str(artifact.get("title", ""))),
        _normalize_token(str(artifact.get("quantity", ""))),
        _normalize_token(Path(str(artifact.get("path", ""))).stem),
    }
    for tag in _string_list(artifact.get("tags", [])):
        candidates.add(_normalize_token(tag))
    candidates.discard("")
    return target in candidates


def _parse_selector(selector: str) -> tuple[str, str]:
    text = selector.strip()
    if ":" not in text:
        return "", text
    kind, name = text.split(":", 1)
    return kind.strip(), name.strip()


def _artifact_summary(artifact: dict[str, Any], selector: str) -> dict[str, Any]:
    keys = (
        "kind",
        "path",
        "title",
        "description",
        "status",
        "source_scope",
        "source_index",
        "run_id",
        "quantity",
    )
    summary = {key: artifact[key] for key in keys if key in artifact}
    summary["selector"] = selector
    return summary


def _overall_status(step_results: list[dict[str, Any]], warnings: list[str]) -> str:
    if warnings and not step_results:
        return "blocked"
    statuses = {str(step["status"]) for step in step_results}
    if statuses == {"covered"}:
        return "partial" if warnings else "covered"
    if statuses == {"missing"}:
        return "missing"
    if "blocked" in statuses:
        return "blocked"
    return "partial"


def _render_audit_markdown(
    *,
    title: str,
    overall_status: str,
    generated_at: str,
    steps: list[dict[str, Any]],
    warnings: list[str],
) -> str:
    lines = [
        f"# Story Acceptance Audit: {title}",
        "",
        f"- Overall status: `{overall_status}`",
        f"- Generated at: `{generated_at}`",
    ]
    if warnings:
        lines.extend(["", "## Warnings"])
        lines.extend(f"- {warning}" for warning in warnings)

    lines.extend(["", "## Steps"])
    for step in steps:
        lines.extend(
            [
                "",
                f"### {step['title']}",
                "",
                f"- Step id: `{step['id']}`",
                f"- Status: `{step['status']}`",
            ]
        )
        if step["claim_ceiling"]:
            lines.append(f"- Claim ceiling: {step['claim_ceiling']}")
        if step["matched_artifacts"]:
            lines.append("- Covered evidence:")
            for artifact in step["matched_artifacts"]:
                lines.append(
                    "  - "
                    f"`{artifact.get('selector', '')}` -> "
                    f"`{artifact.get('path', '')}` "
                    f"({artifact.get('status', 'draft')})"
                )
        if step["weak_artifacts"]:
            lines.append("- Weak evidence:")
            for artifact in step["weak_artifacts"]:
                lines.append(
                    "  - "
                    f"`{artifact.get('selector', '')}` -> "
                    f"`{artifact.get('path', '')}` "
                    f"({artifact.get('status', 'draft')})"
                )
        if step["missing_artifacts"]:
            lines.append("- Missing evidence:")
            lines.extend(f"  - `{selector}`" for selector in step["missing_artifacts"])
    return "\n".join(lines) + "\n"


def _find_project_root_for_story(story_dir: Path) -> Path:
    try:
        return find_project_root(story_dir)
    except ProjectNotFoundError as e:
        raise SimctlError(str(e)) from e


def _resolve_source_path(project_root: Path, path: str) -> Path:
    source = Path(path)
    if source.is_absolute():
        return source
    return project_root / source


def _display_path(path: Path, *, base: Path) -> str:
    resolved_base = base.resolve()
    try:
        return path.resolve().relative_to(resolved_base).as_posix()
    except ValueError:
        return path.as_posix()


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    return []


def _normalize_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
