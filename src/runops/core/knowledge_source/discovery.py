"""Discovery helpers for configured external knowledge sources."""

from __future__ import annotations

from pathlib import Path

from runops.core.exceptions import KnowledgeSourceError
from runops.core.models.knowledge_source import ExternalKnowledgeMount

from .config import load_knowledge_config
from .paths import mount_path, source_root
from .validation import discover_profiles


def collect_external_knowledge(project_root: Path) -> list[ExternalKnowledgeMount]:
    """Return configured knowledge sources."""
    entries: list[ExternalKnowledgeMount] = []

    config = load_knowledge_config(project_root)
    if config is not None:
        for source in config.sources:
            try:
                source_path = source_root(project_root, source)
            except KnowledgeSourceError:
                try:
                    fallback_mount = mount_path(project_root, source)
                except KnowledgeSourceError:
                    fallback_mount = None
                source_path = fallback_mount or project_root
            available = source_path.is_dir()
            entries.append(
                ExternalKnowledgeMount(
                    name=source.name,
                    source_type=source.source_type,
                    kind=source.kind,
                    path=source_path,
                    display_path=source.mount or str(source_path),
                    exists=available,
                    profiles_enabled=(
                        list(source.profiles) if source.kind == "profiles" else []
                    ),
                    profiles_available=(
                        discover_profiles(source_path)
                        if available and source.kind == "profiles"
                        else []
                    ),
                )
            )

    return sorted(entries, key=lambda entry: entry.name.lower())
