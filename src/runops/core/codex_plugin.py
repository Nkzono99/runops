"""Codex plugin recommendation metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CodexPluginRecommendation:
    """Recommendation for an external Codex plugin.

    The recommendation is advisory.  ``runo init`` may offer to run safe
    ``codex plugin ...`` install commands, but final activation can still
    require user-local Codex state, GitHub authentication, and a new Codex
    session.
    """

    name: str
    display_name: str
    reason: str
    install_hint: str
    activation_hint: str = (
        "Install from /plugins or restart Codex after CLI installation."
    )
    visibility: str = "public"
    source: str = ""


def codex_plugin_from_mapping(
    name: str,
    data: dict[str, Any],
    *,
    source: str = "",
) -> CodexPluginRecommendation:
    """Build a plugin recommendation from TOML/dict metadata."""
    display_name = str(data.get("display_name") or data.get("displayName") or name)
    reason = str(data.get("reason") or "")
    install_hint = str(data.get("install_hint") or data.get("install") or "")
    activation_hint = str(
        data.get("activation_hint")
        or data.get("activation")
        or "Install from /plugins or restart Codex after CLI installation."
    )
    visibility = str(data.get("visibility") or "public")
    return CodexPluginRecommendation(
        name=name,
        display_name=display_name,
        reason=reason,
        install_hint=install_hint,
        activation_hint=activation_hint,
        visibility=visibility,
        source=source,
    )


def unique_codex_plugins(
    recommendations: list[CodexPluginRecommendation],
) -> list[CodexPluginRecommendation]:
    """Return recommendations de-duplicated by plugin name."""
    seen: set[str] = set()
    unique: list[CodexPluginRecommendation] = []
    for recommendation in recommendations:
        if recommendation.name in seen:
            continue
        seen.add(recommendation.name)
        unique.append(recommendation)
    return unique
