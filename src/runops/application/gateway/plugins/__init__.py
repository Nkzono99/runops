"""External plugin recommendation inventory for runops projects."""

from .discovery import (
    adapter_lookup_entries,
    adapter_lookup_names,
    collect_adapter_codex_plugins,
    collect_codex_plugin_recommendations,
)
from .inventory import (
    build_project_codex_plugin_inventory,
    check_project_codex_plugins,
    load_project_codex_plugin_inventory,
)
from .models import (
    CodexPluginCheckResult,
    CodexPluginInventory,
    CodexPluginIssue,
    delegated_codex_plugin_capabilities,
)
from .validation import (
    check_codex_plugin_inventory,
    detect_codex_plugin_conflicts,
    validate_codex_plugin_recommendation,
)

__all__ = [
    "CodexPluginCheckResult",
    "CodexPluginInventory",
    "CodexPluginIssue",
    "adapter_lookup_entries",
    "adapter_lookup_names",
    "build_project_codex_plugin_inventory",
    "check_codex_plugin_inventory",
    "check_project_codex_plugins",
    "collect_adapter_codex_plugins",
    "collect_codex_plugin_recommendations",
    "delegated_codex_plugin_capabilities",
    "detect_codex_plugin_conflicts",
    "load_project_codex_plugin_inventory",
    "validate_codex_plugin_recommendation",
]
