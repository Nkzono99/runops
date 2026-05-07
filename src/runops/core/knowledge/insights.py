"""Markdown insight I/O for the local knowledge layer."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runops.core.event_log import emit_artifact_event
from runops.core.models import knowledge as knowledge_records

from .paths import INSIGHTS_DIR, RUNOPS_DIR

Insight = knowledge_records.Insight

INSIGHT_TYPES = frozenset(
    {
        "constraint",
        "result",
        "analysis",
        "dependency",
    }
)


def parse_insight(path: Path) -> Insight | None:
    """Parse an insight markdown file with YAML-like frontmatter."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None

    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None

    end_idx = -1
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end_idx = index
            break
    if end_idx < 0:
        return None

    meta: dict[str, Any] = {}
    for line in lines[1:end_idx]:
        if ":" not in line:
            continue
        key, _, raw_value = line.partition(":")
        key = key.strip()
        stripped = raw_value.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            meta[key] = [
                value.strip().strip("\"'")
                for value in stripped[1:-1].split(",")
                if value.strip()
            ]
        else:
            meta[key] = stripped

    content = "\n".join(lines[end_idx + 1 :]).strip()
    tags = meta.get("tags", [])
    if isinstance(tags, str):
        tags = [tags]

    return Insight(
        name=path.stem,
        type=meta.get("type", "result"),
        simulator=meta.get("simulator", ""),
        tags=tags,
        source_project=meta.get("source_project", ""),
        created=meta.get("created", ""),
        content=content,
    )


def write_insight(insights_dir: Path, insight: Insight) -> Path:
    """Write an insight to a markdown file."""
    tags_str = ", ".join(insight.tags) if insight.tags else ""
    created = insight.created or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    frontmatter = [
        "---",
        f"type: {insight.type}",
        f"simulator: {insight.simulator}",
    ]
    if tags_str:
        frontmatter.append(f"tags: [{tags_str}]")
    if insight.source_project:
        frontmatter.append(f"source_project: {insight.source_project}")
    frontmatter.append(f"created: {created}")
    frontmatter.append("---")

    text = "\n".join(frontmatter) + "\n\n" + insight.content + "\n"
    filepath = insights_dir / f"{insight.name}.md"
    existed_before = filepath.exists()
    filepath.write_text(text, encoding="utf-8")
    emit_artifact_event(
        filepath,
        operation="update" if existed_before else "create",
        artifact_kind="insight",
        summary=f"{'Update' if existed_before else 'Create'} insight {filepath.name}",
    )
    return filepath


def list_insights(
    project_root: Path,
    *,
    simulator: str = "",
    insight_type: str = "",
    tag: str = "",
) -> list[Insight]:
    """List insights, optionally filtered."""
    insights_dir = project_root / RUNOPS_DIR / INSIGHTS_DIR
    if not insights_dir.is_dir():
        return []

    results: list[Insight] = []
    for md_file in sorted(insights_dir.glob("*.md")):
        insight = parse_insight(md_file)
        if insight is None:
            continue
        if simulator and insight.simulator != simulator:
            continue
        if insight_type and insight.type != insight_type:
            continue
        if tag and tag not in insight.tags:
            continue
        results.append(insight)
    return results
