"""Codex plugin metadata validation and conflict detection."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from runops.core.codex_plugin import CodexPluginRecommendation

from .models import CodexPluginCheckResult, CodexPluginInventory, CodexPluginIssue

_KNOWN_VISIBILITIES = frozenset({"public", "private-or-gated"})
_PLUGIN_CONFLICT_FIELDS = (
    "display_name",
    "reason",
    "install_hint",
    "activation_hint",
    "visibility",
)


def _plugin_metadata(plugin: CodexPluginRecommendation) -> dict[str, Any]:
    """Return metadata fields that must agree for duplicate recommendations."""
    return {
        "display_name": plugin.display_name,
        "reason": plugin.reason,
        "install_hint": plugin.install_hint,
        "activation_hint": plugin.activation_hint,
        "visibility": plugin.visibility,
        "capabilities": plugin.capabilities,
    }


def detect_codex_plugin_conflicts(
    recommendations: Sequence[CodexPluginRecommendation],
) -> list[CodexPluginIssue]:
    """Return warnings for duplicate plugin names with conflicting metadata."""
    seen: dict[str, CodexPluginRecommendation] = {}
    issues: list[CodexPluginIssue] = []
    for recommendation in recommendations:
        existing = seen.get(recommendation.name)
        if existing is None:
            seen[recommendation.name] = recommendation
            continue

        existing_metadata = _plugin_metadata(existing)
        candidate_metadata = _plugin_metadata(recommendation)
        changed_fields = [
            field
            for field in _PLUGIN_CONFLICT_FIELDS
            if existing_metadata[field] != candidate_metadata[field]
        ]
        if not changed_fields:
            continue

        sources = [
            source for source in (existing.source, recommendation.source) if source
        ]
        issues.append(
            CodexPluginIssue(
                severity="warning",
                plugin_name=recommendation.name or "<unnamed>",
                field="duplicate",
                message=(
                    "Multiple sources recommend this Codex plugin with "
                    "different metadata. The first recommendation is used. "
                    f"Differing fields: {', '.join(changed_fields)}."
                ),
                source=", ".join(sources),
            )
        )
    return issues


def validate_codex_plugin_recommendation(
    plugin: CodexPluginRecommendation,
) -> list[CodexPluginIssue]:
    """Validate advisory metadata for one Codex plugin recommendation."""
    plugin_name = plugin.name or "<unnamed>"
    issues: list[CodexPluginIssue] = []
    required_fields = {
        "name": plugin.name,
        "display_name": plugin.display_name,
        "reason": plugin.reason,
        "install_hint": plugin.install_hint,
    }
    for field, value in required_fields.items():
        if not value.strip():
            issues.append(
                CodexPluginIssue(
                    severity="error",
                    plugin_name=plugin_name,
                    field=field,
                    message=(
                        "Codex plugin recommendations must include enough "
                        "metadata for users to decide and install manually."
                    ),
                    source=plugin.source,
                )
            )

    if plugin.visibility not in _KNOWN_VISIBILITIES:
        issues.append(
            CodexPluginIssue(
                severity="warning",
                plugin_name=plugin_name,
                field="visibility",
                message=(
                    "Unknown visibility; expected 'public' or 'private-or-gated'."
                ),
                source=plugin.source,
            )
        )
    if not plugin.activation_hint.strip():
        issues.append(
            CodexPluginIssue(
                severity="warning",
                plugin_name=plugin_name,
                field="activation_hint",
                message=(
                    "Activation hint is empty; users may not know how to enable it."
                ),
                source=plugin.source,
            )
        )
    if not plugin.source.strip():
        issues.append(
            CodexPluginIssue(
                severity="warning",
                plugin_name=plugin_name,
                field="source",
                message="Source is empty; generated diagnostics cannot show origin.",
                source=plugin.source,
            )
        )
    return issues


def check_codex_plugin_inventory(
    inventory: CodexPluginInventory,
) -> CodexPluginCheckResult:
    """Validate advisory plugin recommendation metadata for an inventory."""
    issues: list[CodexPluginIssue] = list(inventory.collection_issues)
    for plugin in inventory.recommendations:
        issues.extend(validate_codex_plugin_recommendation(plugin))
    return CodexPluginCheckResult(inventory=inventory, issues=tuple(issues))
