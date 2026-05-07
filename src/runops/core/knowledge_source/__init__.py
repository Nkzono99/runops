"""Knowledge source management: external knowledge integration."""

from __future__ import annotations

from runops.core.exceptions import KnowledgeSourceError
from runops.core.models.knowledge_source import (
    ExternalKnowledgeMount,
    KnowledgeConfig,
    KnowledgeEntrypoints,
    KnowledgeSource,
)

from .config import (
    load_knowledge_config,
    remove_knowledge_source,
    save_knowledge_source,
    set_knowledge_source_profiles,
)
from .discovery import collect_external_knowledge
from .entrypoints import (
    ENTRYPOINTS_FILE,
    dedupe_strings,
    discover_repo_imports,
    load_entrypoints,
    normalize_import_list,
    parse_import_directives,
    profile_markdown_path,
    resolve_import_target,
    resolve_profile_imports,
)
from .imports import import_external_facts, import_external_insights
from .paths import (
    fact_source_file,
    insight_source_dir,
    mount_path,
    namespaced_insight_filename,
    repo_name_from_url,
    resolve_path_source,
    safe_namespace,
    source_root,
)
from .render import render_imports
from .sync import mirror_directory, remove_path, sync_all_sources, sync_source
from .validation import discover_profiles, validate_source_structure

# Private compatibility aliases for sibling modules and old internal tests.
_ENTRYPOINTS_FILE = ENTRYPOINTS_FILE
_dedupe_strings = dedupe_strings
_fact_source_file = fact_source_file
_insight_source_dir = insight_source_dir
_mirror_directory = mirror_directory
_mount_path = mount_path
_namespaced_insight_filename = namespaced_insight_filename
_normalize_import_list = normalize_import_list
_parse_import_directives = parse_import_directives
_profile_markdown_path = profile_markdown_path
_remove_path = remove_path
_repo_name_from_url = repo_name_from_url
_resolve_import_target = resolve_import_target
_resolve_path_source = resolve_path_source
_resolve_profile_imports = resolve_profile_imports
_safe_namespace = safe_namespace
_source_root = source_root

__all__ = [
    "ExternalKnowledgeMount",
    "KnowledgeConfig",
    "KnowledgeEntrypoints",
    "KnowledgeSource",
    "KnowledgeSourceError",
    "collect_external_knowledge",
    "discover_profiles",
    "discover_repo_imports",
    "import_external_facts",
    "import_external_insights",
    "load_entrypoints",
    "load_knowledge_config",
    "remove_knowledge_source",
    "render_imports",
    "save_knowledge_source",
    "set_knowledge_source_profiles",
    "sync_all_sources",
    "sync_source",
    "validate_source_structure",
]
