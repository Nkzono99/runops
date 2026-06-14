"""Codex plugin recommendation metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

CODEX_PLUGIN_ACTIVATION_SCOPE = "user-local Codex environment"
CODEX_PLUGIN_INVENTORY_SCHEMA_VERSION = 1
CODEX_PLUGIN_INVENTORY_SCHEMA_PATH = "schemas/codex-plugin-inventory.json"
CODEX_PLUGIN_CHECK_RESULT_SCHEMA_PATH = "schemas/codex-plugin-check-result.json"
DEFAULT_CODEX_PLUGIN_ACTIVATION_HINT = (
    "Install from /plugins or restart Codex after CLI installation."
)


def codex_plugin_management_policy() -> dict[str, bool | str]:
    """Return runops' management boundary for external Codex plugins."""
    return {
        "runops_installs_plugins": False,
        "runops_enables_plugins": False,
        "runops_inspects_user_install_state": False,
        "activation_scope": CODEX_PLUGIN_ACTIVATION_SCOPE,
    }


@dataclass(frozen=True)
class CodexPluginRecommendation:
    """Recommendation for an external Codex plugin.

    The recommendation is advisory.  runops does not install Codex plugins as
    part of project bootstrap because plugin activation may require user-local
    Codex state, GitHub authentication, and a new Codex session.
    """

    name: str
    display_name: str
    reason: str
    install_hint: str
    activation_hint: str = DEFAULT_CODEX_PLUGIN_ACTIVATION_HINT
    visibility: str = "public"
    source: str = ""
    capabilities: tuple[str, ...] = ()

    def source_labels(self) -> tuple[str, ...]:
        """Return normalized source labels for this recommendation."""
        return _source_parts(self.source)

    def with_additional_source(self, source: str) -> CodexPluginRecommendation:
        """Return a copy with additional source labels merged in."""
        sources = _unique_non_empty_strings(
            (*self.source_labels(), *_source_parts(source))
        )
        return CodexPluginRecommendation(
            name=self.name,
            display_name=self.display_name,
            reason=self.reason,
            install_hint=self.install_hint,
            activation_hint=self.activation_hint,
            visibility=self.visibility,
            source=", ".join(sources),
            capabilities=self.capabilities,
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable recommendation payload."""
        return {
            "name": self.name,
            "display_name": self.display_name,
            "reason": self.reason,
            "install_hint": self.install_hint,
            "activation_hint": self.activation_hint,
            "visibility": self.visibility,
            "source": self.source,
            "sources": list(self.source_labels()),
            "capabilities": list(self.capabilities),
        }

    def to_site_mapping(self) -> dict[str, Any]:
        """Return TOML metadata suitable for ``[site.codex_plugins.<name>]``."""
        mapping: dict[str, Any] = {
            "display_name": self.display_name,
            "visibility": self.visibility,
            "reason": self.reason,
            "install_hint": self.install_hint,
            "activation_hint": self.activation_hint,
        }
        if self.capabilities:
            mapping["capabilities"] = list(self.capabilities)
        return mapping


def _capabilities_from_value(value: Any) -> tuple[str, ...]:
    """Return advisory capability labels from TOML metadata."""
    if value in (None, ""):
        return ()
    if isinstance(value, str):
        capability = value.strip()
        return (capability,) if capability else ()
    if isinstance(value, (list, tuple)):
        return tuple(
            item.strip() for item in value if isinstance(item, str) and item.strip()
        )
    return ()


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
        or DEFAULT_CODEX_PLUGIN_ACTIVATION_HINT
    )
    visibility = str(data.get("visibility") or "public")
    capabilities = _capabilities_from_value(data.get("capabilities"))
    return CodexPluginRecommendation(
        name=name,
        display_name=display_name,
        reason=reason,
        install_hint=install_hint,
        activation_hint=activation_hint,
        visibility=visibility,
        source=source,
        capabilities=capabilities,
    )


def _unique_non_empty_strings(values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    """Return non-empty strings without duplicates while preserving order."""
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
    return tuple(unique)


def _source_parts(source: str) -> tuple[str, ...]:
    """Return normalized comma-separated source labels."""
    return _unique_non_empty_strings(tuple(source.split(",")))


def _merge_codex_plugin_pair(
    first: CodexPluginRecommendation,
    later: CodexPluginRecommendation,
) -> CodexPluginRecommendation:
    """Merge additive metadata while preserving the first recommendation."""
    sources = _unique_non_empty_strings(
        (*_source_parts(first.source), *_source_parts(later.source))
    )
    capabilities = _unique_non_empty_strings((*first.capabilities, *later.capabilities))
    return CodexPluginRecommendation(
        name=first.name,
        display_name=first.display_name,
        reason=first.reason,
        install_hint=first.install_hint,
        activation_hint=first.activation_hint,
        visibility=first.visibility,
        source=", ".join(sources),
        capabilities=capabilities,
    )


def merge_codex_plugins(
    recommendations: list[CodexPluginRecommendation],
) -> list[CodexPluginRecommendation]:
    """Return recommendations merged by plugin name.

    Scalar metadata from the first recommendation wins.  Additive metadata
    such as ``source`` and ``capabilities`` is merged so project, simulator, and
    site layers can extend delegated roles without editing the original adapter.
    """
    indexes: dict[str, int] = {}
    merged: list[CodexPluginRecommendation] = []
    for recommendation in recommendations:
        existing_index = indexes.get(recommendation.name)
        if existing_index is None:
            indexes[recommendation.name] = len(merged)
            merged.append(recommendation)
            continue
        merged[existing_index] = _merge_codex_plugin_pair(
            merged[existing_index],
            recommendation,
        )
    return merged


def unique_codex_plugins(
    recommendations: list[CodexPluginRecommendation],
) -> list[CodexPluginRecommendation]:
    """Return recommendations de-duplicated by plugin name."""
    return merge_codex_plugins(recommendations)
