"""Path resolution helpers for external knowledge sources."""

from __future__ import annotations

from pathlib import Path

from runops.core.exceptions import KnowledgeSourceError
from runops.core.models.knowledge_source import KnowledgeSource


def resolve_path_source(project_root: Path, raw_path: str) -> Path:
    resolved = Path(raw_path).expanduser()
    if not resolved.is_absolute():
        resolved = (project_root / resolved).resolve()
    return resolved


def mount_path(project_root: Path, source: KnowledgeSource) -> Path | None:
    if not source.mount:
        return None
    mount = Path(source.mount)
    if mount.is_absolute():
        msg = (
            f"Knowledge source '{source.name}' mount path must be relative: "
            f"{source.mount}"
        )
        raise KnowledgeSourceError(msg)

    resolved_root = project_root.resolve()
    candidate = project_root / mount
    resolved_parent = candidate.parent.resolve()
    try:
        resolved_parent.relative_to(resolved_root)
    except ValueError as exc:
        msg = (
            f"Knowledge source '{source.name}' mount path escapes project root: "
            f"{source.mount}"
        )
        raise KnowledgeSourceError(msg) from exc

    return resolved_parent / candidate.name


def source_root(project_root: Path, source: KnowledgeSource) -> Path:
    if source.source_type == "path" and source.kind != "profiles":
        return resolve_path_source(project_root, source.url)

    resolved_mount = mount_path(project_root, source)
    if resolved_mount is None:
        msg = f"Knowledge source '{source.name}' requires a mount path"
        raise KnowledgeSourceError(msg)
    return resolved_mount


def insight_source_dir(project_root: Path, source: KnowledgeSource) -> Path | None:
    root = source_root(project_root, source)
    if source.kind == "project":
        return root / ".runops" / "insights"
    if source.kind == "insights":
        return root / "insights"
    return None


def fact_source_file(project_root: Path, source: KnowledgeSource) -> Path | None:
    root = source_root(project_root, source)
    candidates: list[Path] = []
    if source.kind == "project":
        candidates.append(root / ".runops" / "facts.toml")
    elif source.kind == "insights":
        candidates.extend(
            [
                root / "facts.toml",
                root / ".runops" / "facts.toml",
            ]
        )

    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def repo_name_from_url(url: str) -> str:
    """Extract repository name from a git URL."""
    stem = url.rsplit("/", 1)[-1].rsplit(":", 1)[-1]
    if stem.endswith(".git"):
        stem = stem[:-4]
    return stem


def safe_namespace(value: str) -> str:
    """Return a filesystem-safe namespace token for imported knowledge."""
    normalized = [ch.lower() if ch.isalnum() else "_" for ch in value.strip()]
    token = "".join(normalized).strip("_")
    while "__" in token:
        token = token.replace("__", "_")
    return token or "source"


def namespaced_insight_filename(source: KnowledgeSource, insight_name: str) -> str:
    """Build the destination filename for an imported insight."""
    namespace = safe_namespace(source.name)
    return f"{namespace}__{insight_name}.md"
