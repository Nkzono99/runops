"""runops.toml configuration helpers for external knowledge sources."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from tomlkit import aot, array, nl, parse, table

from runops.core.exceptions import KnowledgeSourceError
from runops.core.models import knowledge_source as knowledge_models

logger = logging.getLogger(__name__)

_PROJECT_FILE = "runops.toml"
_DEFAULT_MOUNT_DIR = knowledge_models.DEFAULT_MOUNT_DIR
_DEFAULT_DERIVED_DIR = knowledge_models.DEFAULT_DERIVED_DIR
_SOURCE_TYPES = frozenset({"git", "path"})
_SOURCE_KINDS = frozenset({"profiles", "project", "insights"})

KnowledgeConfig = knowledge_models.KnowledgeConfig
KnowledgeSource = knowledge_models.KnowledgeSource


def _normalize_source_type(value: Any) -> str:
    source_type = str(value or "git")
    if source_type not in _SOURCE_TYPES:
        logger.warning("Unknown knowledge source type '%s'; using 'git'", value)
        return "git"
    return source_type


def _normalize_source_kind(value: Any) -> str:
    kind = str(value or "profiles")
    if kind not in _SOURCE_KINDS:
        logger.warning(
            "Unknown knowledge source kind '%s'; using 'profiles'",
            value,
        )
        return "profiles"
    return kind


def _default_mount(name: str, mount_dir: str, *, source_type: str, kind: str) -> str:
    if source_type == "git" or kind == "profiles":
        return f"{mount_dir}/{name}"
    return ""


def load_knowledge_config(project_root: Path) -> KnowledgeConfig | None:
    """Load knowledge configuration from runops.toml."""
    project_file = project_root / _PROJECT_FILE
    if not project_file.is_file():
        return None

    with open(project_file, "rb") as f:
        raw = tomllib.load(f)

    knowledge_raw = raw.get("knowledge")
    if not isinstance(knowledge_raw, dict):
        return None

    sources: list[KnowledgeSource] = []
    mount_dir = str(knowledge_raw.get("mount_dir", _DEFAULT_MOUNT_DIR))
    for src in knowledge_raw.get("sources", []):
        if not isinstance(src, dict):
            continue
        name = src.get("name", "")
        if not name:
            continue
        source_type = _normalize_source_type(src.get("type", "git"))
        kind = _normalize_source_kind(src.get("kind", "profiles"))
        url = str(src.get("url") or src.get("path") or "")
        ref = src.get("ref", "main")
        default_mount = _default_mount(
            name,
            mount_dir,
            source_type=source_type,
            kind=kind,
        )
        mount = str(src.get("mount", default_mount))
        profiles = list(src.get("profiles", [])) if kind == "profiles" else []
        sources.append(
            KnowledgeSource(
                name=name,
                source_type=source_type,
                kind=kind,
                url=url,
                ref=ref,
                mount=mount,
                profiles=profiles,
            )
        )

    return KnowledgeConfig(
        enabled=knowledge_raw.get("enabled", True),
        mount_dir=mount_dir,
        derived_dir=knowledge_raw.get("derived_dir", _DEFAULT_DERIVED_DIR),
        auto_sync_on_setup=knowledge_raw.get("auto_sync_on_setup", True),
        generate_claude_imports=knowledge_raw.get("generate_claude_imports", True),
        sources=sources,
    )


def _load_project_toml_document(project_root: Path) -> Any:
    """Read runops.toml as a mutable TOML document."""
    project_file = project_root / _PROJECT_FILE
    try:
        content = project_file.read_text(encoding="utf-8")
    except OSError as exc:
        msg = f"Failed to read {project_file}: {exc}"
        raise KnowledgeSourceError(msg) from exc
    return parse(content)


def _write_project_toml(project_root: Path, document_obj: Any) -> None:
    """Write runops.toml while preserving comments and layout."""
    project_file = project_root / _PROJECT_FILE
    try:
        project_file.write_text(document_obj.as_string(), encoding="utf-8")
    except OSError as exc:
        msg = f"Failed to write {project_file}: {exc}"
        raise KnowledgeSourceError(msg) from exc


def _ensure_knowledge_table(document_obj: Any) -> Any:
    knowledge = document_obj.get("knowledge")
    if knowledge is None:
        if document_obj:
            document_obj.add(nl())
        knowledge = table()
        document_obj["knowledge"] = knowledge

    knowledge.setdefault("enabled", True)
    knowledge.setdefault("mount_dir", _DEFAULT_MOUNT_DIR)
    knowledge.setdefault("derived_dir", _DEFAULT_DERIVED_DIR)
    knowledge.setdefault("auto_sync_on_setup", True)
    knowledge.setdefault("generate_claude_imports", True)

    sources = knowledge.get("sources")
    if sources is None:
        knowledge["sources"] = aot()
    return knowledge


def _ensure_sources_list(knowledge: Any) -> Any:
    sources = knowledge.get("sources")
    if sources is None:
        sources = aot()
        knowledge["sources"] = sources
    return sources


def _find_source_entry(sources: Any, name: str) -> Any | None:
    for entry in sources:
        if str(entry.get("name", "")) == name:
            return entry
    return None


def _sync_source_entry(entry: Any, source: KnowledgeSource) -> None:
    entry["name"] = source.name
    entry["type"] = source.source_type
    entry["kind"] = source.kind

    if source.source_type == "git":
        entry["url"] = source.url
        if source.ref and source.ref != "main":
            entry["ref"] = source.ref
        elif "ref" in entry:
            del entry["ref"]
        if "path" in entry:
            del entry["path"]
    else:
        entry["path"] = source.url
        if "url" in entry:
            del entry["url"]
        if "ref" in entry:
            del entry["ref"]

    if source.mount:
        entry["mount"] = source.mount
    elif "mount" in entry:
        del entry["mount"]

    if source.kind == "profiles" and source.profiles:
        profiles_array = array()
        profiles_array.extend(source.profiles)
        entry["profiles"] = profiles_array
    elif "profiles" in entry:
        del entry["profiles"]


def save_knowledge_source(project_root: Path, source: KnowledgeSource) -> None:
    """Add or update a knowledge source in runops.toml."""
    document_obj = _load_project_toml_document(project_root)
    knowledge = _ensure_knowledge_table(document_obj)
    sources = _ensure_sources_list(knowledge)
    entry = _find_source_entry(sources, source.name)
    if entry is None:
        entry = table()
        sources.append(entry)
    _sync_source_entry(entry, source)
    _write_project_toml(project_root, document_obj)


def remove_knowledge_source(project_root: Path, name: str) -> bool:
    """Remove a knowledge source from runops.toml by name."""
    document_obj = _load_project_toml_document(project_root)
    knowledge = document_obj.get("knowledge")
    if knowledge is None:
        return False

    sources = knowledge.get("sources")
    if sources is None:
        return False

    new_sources = aot()
    removed = False
    for entry in sources:
        if str(entry.get("name", "")) == name:
            removed = True
            continue
        new_sources.append(entry)

    if not removed:
        return False

    knowledge["sources"] = new_sources
    _write_project_toml(project_root, document_obj)
    return True


def set_knowledge_source_profiles(
    project_root: Path,
    name: str,
    *,
    enable: list[str] | None = None,
    disable: list[str] | None = None,
) -> KnowledgeSource:
    """Enable or disable profiles for a configured profiles source."""
    config = load_knowledge_config(project_root)
    if config is None:
        msg = "No [knowledge] section in runops.toml."
        raise KnowledgeSourceError(msg)

    source = next((src for src in config.sources if src.name == name), None)
    if source is None:
        msg = f"Knowledge source not found: {name}"
        raise KnowledgeSourceError(msg)
    if source.kind != "profiles":
        msg = f"Knowledge source '{name}' does not support profiles"
        raise KnowledgeSourceError(msg)

    enabled_profiles = list(source.profiles)
    for profile_name in enable or []:
        if profile_name not in enabled_profiles:
            enabled_profiles.append(profile_name)
    if disable:
        disabled = set(disable)
        enabled_profiles = [
            profile_name
            for profile_name in enabled_profiles
            if profile_name not in disabled
        ]

    updated = KnowledgeSource(
        name=source.name,
        source_type=source.source_type,
        kind=source.kind,
        url=source.url,
        ref=source.ref,
        mount=source.mount,
        profiles=enabled_profiles,
    )
    save_knowledge_source(project_root, updated)
    return updated
