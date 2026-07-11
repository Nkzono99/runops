"""Filesystem orchestration for Story acceptance workspaces."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import tomli_w

from runops.core.exceptions import ProjectNotFoundError, SimctlError
from runops.core.project import find_project_root

from .audit import audit_step, overall_status
from .models import StoryAudit, StorySpec, StoryStep
from .render import audit_payload, render_audit_markdown
from .schema import read_story_spec, story_spec_payload, validate_story_id
from .sources import collect_source_artifacts, display_path, source_from_path

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
    for char in text:
        if char.isascii() and char.isalnum():
            chars.append(char)
            last_dash = False
            continue
        if (char in {"-", "_", "."} or char.isspace()) and not last_dash:
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
    """Create ``analysis/stories/<story_id>/`` with a starter story spec."""
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

    spec = StorySpec(
        schema_version=1,
        id=resolved_id,
        title=story_title,
        status="draft",
        sources=tuple(source_from_path(root, source) for source in sources),
        steps=(
            StoryStep(
                id="first-step",
                title="First story step",
                required_artifacts=("figure:replace_with_artifact_name",),
                acceptable_status=_DEFAULT_MATURITY,
            ),
        ),
    )
    story_dir.mkdir(parents=True)
    story_path = story_dir / "story.toml"
    with open(story_path, "wb") as stream:
        tomli_w.dump(story_spec_payload(spec), stream)

    return StoryWorkspaceResult(
        story_id=resolved_id,
        title=story_title,
        story_dir=story_dir,
        story_path=story_path,
        source_count=len(sources),
    )


def audit_story_workspace(story_dir: Path) -> StoryAuditResult:
    """Audit a Story workspace and write ``audit.json`` and ``audit.md``."""
    story_root = story_dir.resolve()
    story_path = story_root / "story.toml"
    if not story_path.is_file():
        raise SimctlError(f"story.toml not found: {story_path}")

    project_root = _find_project_root_for_story(story_root)
    spec = read_story_spec(story_path, default_id=story_root.name)
    artifacts = []
    warnings: list[str] = []
    for source in spec.sources:
        collection = collect_source_artifacts(project_root, source)
        artifacts.extend(collection.artifacts)
        warnings.extend(collection.warnings)

    source_blocked = any(
        warning.startswith("Story source not found:") for warning in warnings
    )
    step_results = tuple(
        audit_step(step, artifacts, source_blocked=source_blocked)
        for step in spec.steps
    )
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    audit = StoryAudit(
        spec=spec,
        generated_at=generated_at,
        story_path=display_path(story_path, base=project_root),
        overall_status=overall_status(step_results, warnings),
        warnings=tuple(warnings),
        steps=step_results,
    )

    audit_json_path = story_root / "audit.json"
    audit_md_path = story_root / "audit.md"
    audit_json_path.write_text(
        json.dumps(audit_payload(audit), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    audit_md_path.write_text(render_audit_markdown(audit), encoding="utf-8")

    return StoryAuditResult(
        story_id=spec.id,
        title=spec.title,
        story_dir=story_root,
        audit_json_path=audit_json_path,
        audit_md_path=audit_md_path,
        overall_status=audit.overall_status,
        steps=[cast(dict[str, Any], step.to_dict()) for step in step_results],
        warnings=warnings,
    )


def _find_project_root_for_story(story_dir: Path) -> Path:
    try:
        return find_project_root(story_dir)
    except ProjectNotFoundError as exc:
        raise SimctlError(str(exc)) from exc
