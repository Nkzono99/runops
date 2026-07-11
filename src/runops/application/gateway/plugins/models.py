"""Codex plugin inventory and diagnostic value objects."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from runops.core.codex_plugin import (
    CODEX_PLUGIN_CHECK_RESULT_SCHEMA_PATH,
    CODEX_PLUGIN_INVENTORY_SCHEMA_PATH,
    CODEX_PLUGIN_INVENTORY_SCHEMA_VERSION,
    CodexPluginRecommendation,
    codex_plugin_management_policy,
)

PluginIssueSeverity = Literal["error", "warning"]


@dataclass(frozen=True)
class CodexPluginInventory:
    """Codex plugin recommendations for a runops project."""

    project_name: str
    project_dir: Path
    simulator_names: tuple[str, ...]
    site_name: str
    recommendations: tuple[CodexPluginRecommendation, ...]
    collection_issues: tuple[CodexPluginIssue, ...] = ()

    def delegated_capabilities(self) -> dict[str, list[str]]:
        """Return capability labels mapped to recommending plugin names."""
        return delegated_codex_plugin_capabilities(self.recommendations)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return {
            "$schema": CODEX_PLUGIN_INVENTORY_SCHEMA_PATH,
            "schema_version": CODEX_PLUGIN_INVENTORY_SCHEMA_VERSION,
            "project": {
                "name": self.project_name,
                "root": str(self.project_dir),
            },
            "simulators": list(self.simulator_names),
            "site": self.site_name,
            "management": codex_plugin_management_policy(),
            "recommendations": [plugin.to_dict() for plugin in self.recommendations],
            "delegated_capabilities": self.delegated_capabilities(),
            "collection_issues": [issue.to_dict() for issue in self.collection_issues],
        }


@dataclass(frozen=True)
class CodexPluginIssue:
    """Validation issue for an advisory Codex plugin recommendation."""

    severity: PluginIssueSeverity
    plugin_name: str
    field: str
    message: str
    source: str = ""

    def to_dict(self) -> dict[str, str]:
        """Return a JSON-serializable representation."""
        return {
            "severity": self.severity,
            "plugin_name": self.plugin_name,
            "field": self.field,
            "message": self.message,
            "source": self.source,
        }


@dataclass(frozen=True)
class CodexPluginCheckResult:
    """Validation result for a project Codex plugin inventory."""

    inventory: CodexPluginInventory
    issues: tuple[CodexPluginIssue, ...]

    @property
    def ok(self) -> bool:
        """Return whether no error-level issues were found."""
        return not any(issue.severity == "error" for issue in self.issues)

    def ok_with_strict(self) -> bool:
        """Return whether no error or warning issues were found."""
        return not self.issues

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        errors = sum(1 for issue in self.issues if issue.severity == "error")
        warnings = sum(1 for issue in self.issues if issue.severity == "warning")
        return {
            "$schema": CODEX_PLUGIN_CHECK_RESULT_SCHEMA_PATH,
            "schema_version": CODEX_PLUGIN_INVENTORY_SCHEMA_VERSION,
            "ok": self.ok,
            "strict_ok": self.ok_with_strict(),
            "summary": {
                "recommendations": len(self.inventory.recommendations),
                "errors": errors,
                "warnings": warnings,
            },
            "inventory": self.inventory.to_dict(),
            "issues": [issue.to_dict() for issue in self.issues],
        }


def delegated_codex_plugin_capabilities(
    recommendations: Sequence[CodexPluginRecommendation],
) -> dict[str, list[str]]:
    """Return a stable capability-to-plugin index for recommendations."""
    index: dict[str, list[str]] = {}
    for recommendation in recommendations:
        for capability in recommendation.capabilities:
            capability_name = capability.strip()
            if not capability_name:
                continue
            plugin_names = index.setdefault(capability_name, [])
            if recommendation.name not in plugin_names:
                plugin_names.append(recommendation.name)
    return {capability: index[capability] for capability in sorted(index)}
