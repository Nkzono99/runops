"""External plugin recommendation inventory for runops projects."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from runops.core.codex_plugin import (
    CODEX_PLUGIN_CHECK_RESULT_SCHEMA_PATH,
    CODEX_PLUGIN_INVENTORY_SCHEMA_PATH,
    CODEX_PLUGIN_INVENTORY_SCHEMA_VERSION,
    CodexPluginRecommendation,
    codex_plugin_from_mapping,
    codex_plugin_management_policy,
    unique_codex_plugins,
)
from runops.core.project import ProjectConfig, find_project_root, load_project
from runops.core.site import SiteProfile, load_site_profile

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

PluginIssueSeverity = Literal["error", "warning"]
_SITE_FILE = "site.toml"
_KNOWN_VISIBILITIES = frozenset({"public", "private-or-gated"})
_PLUGIN_CONFLICT_FIELDS = (
    "display_name",
    "reason",
    "install_hint",
    "activation_hint",
    "visibility",
)
_INVALID_CAPABILITIES_MESSAGE = (
    "Codex plugin capabilities must be a string or a TOML array of non-empty strings."
)


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


def adapter_lookup_names(
    simulator_names: Sequence[str],
    simulator_configs: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    """Return adapter registry keys for simulator names and optional configs."""
    return [
        adapter_name
        for _simulator_name, adapter_name in adapter_lookup_entries(
            simulator_names,
            simulator_configs,
        )
    ]


def adapter_lookup_entries(
    simulator_names: Sequence[str],
    simulator_configs: dict[str, dict[str, Any]] | None = None,
) -> list[tuple[str, str]]:
    """Return unique ``(simulator_name, adapter_name)`` lookup entries."""
    configs = simulator_configs or {}
    seen: set[str] = set()
    entries: list[tuple[str, str]] = []
    for simulator_name in simulator_names:
        config = configs.get(simulator_name, {})
        adapter_name = simulator_name
        if isinstance(config, dict):
            configured = config.get("adapter")
            if isinstance(configured, str) and configured:
                adapter_name = configured
        if adapter_name in seen:
            continue
        seen.add(adapter_name)
        entries.append((simulator_name, adapter_name))
    return entries


def _collect_adapter_codex_plugins_raw(
    simulator_names: Sequence[str],
    *,
    simulator_configs: dict[str, dict[str, Any]] | None = None,
) -> list[CodexPluginRecommendation]:
    """Return Codex plugins recommended by selected adapters before de-duping."""
    recommendations, _issues = _collect_adapter_codex_plugins_with_issues(
        simulator_names,
        simulator_configs=simulator_configs,
    )
    return recommendations


def _collect_adapter_codex_plugins_with_issues(
    simulator_names: Sequence[str],
    *,
    simulator_configs: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[CodexPluginRecommendation], list[CodexPluginIssue]]:
    """Return adapter plugin recommendations and collection warnings."""
    import runops.adapters  # noqa: F401
    from runops.adapters.registry import get_global_registry

    registry = get_global_registry()
    plugins: list[CodexPluginRecommendation] = []
    issues: list[CodexPluginIssue] = []
    for simulator_name, adapter_name in adapter_lookup_entries(
        simulator_names,
        simulator_configs,
    ):
        try:
            adapter_cls = registry.get(adapter_name)
        except KeyError:
            issues.append(
                CodexPluginIssue(
                    severity="warning",
                    plugin_name=adapter_name,
                    field="adapter",
                    message=(
                        f"Adapter '{adapter_name}' is not registered; "
                        "adapter-declared Codex plugin recommendations for simulator "
                        f"'{simulator_name}' could not be collected."
                    ),
                    source=f"simulator:{simulator_name}",
                )
            )
            continue
        source = f"simulator:{simulator_name}"
        plugins.extend(
            recommendation.with_additional_source(source)
            for recommendation in adapter_cls.codex_plugins()
        )
    return plugins, issues


def _collect_codex_plugin_metadata_issues(
    plugin_name: str,
    plugin_data: dict[str, Any],
    *,
    source: str,
) -> list[CodexPluginIssue]:
    """Return warnings for malformed optional plugin metadata fields."""
    if _valid_capabilities_value(plugin_data.get("capabilities")):
        return []
    return [
        CodexPluginIssue(
            severity="warning",
            plugin_name=plugin_name,
            field="capabilities",
            message=_INVALID_CAPABILITIES_MESSAGE,
            source=source,
        )
    ]


def _valid_capabilities_value(value: Any) -> bool:
    """Return whether a raw ``capabilities`` metadata value is valid."""
    if value is None or value == "":
        return True
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple)):
        return all(isinstance(item, str) and item.strip() for item in value)
    return False


def _collect_simulator_config_codex_plugins(
    simulator_names: Sequence[str],
    simulator_configs: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[CodexPluginRecommendation], list[CodexPluginIssue]]:
    """Return Codex plugin recommendations declared in simulator config."""
    configs = simulator_configs or {}
    recommendations: list[CodexPluginRecommendation] = []
    issues: list[CodexPluginIssue] = []
    for simulator_name in simulator_names:
        config = configs.get(simulator_name, {})
        if not isinstance(config, dict):
            continue
        plugins_raw = config.get("codex_plugins", {})
        if plugins_raw in ({}, None):
            continue
        source = f"simulator:{simulator_name}"
        if not isinstance(plugins_raw, dict):
            issues.append(
                CodexPluginIssue(
                    severity="warning",
                    plugin_name=simulator_name,
                    field="codex_plugins",
                    message=(
                        "Simulator-level Codex plugin recommendations must be "
                        "declared as a TOML table."
                    ),
                    source=source,
                )
            )
            continue
        for plugin_name, plugin_data in plugins_raw.items():
            if not isinstance(plugin_data, dict):
                issues.append(
                    CodexPluginIssue(
                        severity="warning",
                        plugin_name=str(plugin_name),
                        field="codex_plugins",
                        message=(
                            "Simulator-level Codex plugin recommendation metadata "
                            "must be a TOML table."
                        ),
                        source=source,
                    )
                )
                continue
            issues.extend(
                _collect_codex_plugin_metadata_issues(
                    str(plugin_name),
                    plugin_data,
                    source=source,
                )
            )
            recommendations.append(
                codex_plugin_from_mapping(
                    str(plugin_name),
                    plugin_data,
                    source=source,
                )
            )
    return recommendations, issues


def _collect_project_config_codex_plugins(
    project: ProjectConfig,
) -> tuple[list[CodexPluginRecommendation], list[CodexPluginIssue]]:
    """Return project-wide Codex plugin recommendations from ``runops.toml``."""
    project_section = project.raw.get("project", {})
    if not isinstance(project_section, dict):
        return [], []

    plugins_raw = project_section.get("codex_plugins", {})
    if plugins_raw in ({}, None):
        return [], []

    source = f"project:{project.name}"
    if not isinstance(plugins_raw, dict):
        return [], [
            CodexPluginIssue(
                severity="warning",
                plugin_name=project.name,
                field="codex_plugins",
                message=(
                    "Project-level Codex plugin recommendations must be "
                    "declared as a TOML table."
                ),
                source=source,
            )
        ]

    recommendations: list[CodexPluginRecommendation] = []
    issues: list[CodexPluginIssue] = []
    for plugin_name, plugin_data in plugins_raw.items():
        if not isinstance(plugin_data, dict):
            issues.append(
                CodexPluginIssue(
                    severity="warning",
                    plugin_name=str(plugin_name),
                    field="codex_plugins",
                    message=(
                        "Project-level Codex plugin recommendation metadata "
                        "must be a TOML table."
                    ),
                    source=source,
                )
            )
            continue
        issues.extend(
            _collect_codex_plugin_metadata_issues(
                str(plugin_name),
                plugin_data,
                source=source,
            )
        )
        recommendations.append(
            codex_plugin_from_mapping(
                str(plugin_name),
                plugin_data,
                source=source,
            )
        )
    return recommendations, issues


def _collect_site_config_codex_plugin_issues(
    project_root: Path,
    *,
    site_name: str,
) -> list[CodexPluginIssue]:
    """Return site-level Codex plugin collection warnings from ``site.toml``."""
    site_file = project_root / _SITE_FILE
    if not site_file.is_file():
        return []

    with open(site_file, "rb") as f:
        raw = tomllib.load(f)
    site = raw.get("site", {})
    if not isinstance(site, dict):
        return []

    plugins_raw = site.get("codex_plugins", {})
    if plugins_raw in ({}, None):
        return []

    source = f"site:{site.get('name') or site_name or site_file.stem}"
    if not isinstance(plugins_raw, dict):
        return [
            CodexPluginIssue(
                severity="warning",
                plugin_name=str(site.get("name") or site_name or "site"),
                field="codex_plugins",
                message=(
                    "Site-level Codex plugin recommendations must be declared "
                    "as a TOML table."
                ),
                source=source,
            )
        ]

    issues: list[CodexPluginIssue] = []
    for plugin_name, plugin_data in plugins_raw.items():
        if isinstance(plugin_data, dict):
            issues.extend(
                _collect_codex_plugin_metadata_issues(
                    str(plugin_name),
                    plugin_data,
                    source=source,
                )
            )
            continue
        issues.append(
            CodexPluginIssue(
                severity="warning",
                plugin_name=str(plugin_name),
                field="codex_plugins",
                message=(
                    "Site-level Codex plugin recommendation metadata must be "
                    "a TOML table."
                ),
                source=source,
            )
        )
    return issues


def collect_adapter_codex_plugins(
    simulator_names: Sequence[str],
    *,
    simulator_configs: dict[str, dict[str, Any]] | None = None,
) -> list[CodexPluginRecommendation]:
    """Return unique Codex plugins recommended by selected adapters."""
    return unique_codex_plugins(
        _collect_adapter_codex_plugins_raw(
            simulator_names,
            simulator_configs=simulator_configs,
        )
    )


def _collect_codex_plugin_recommendations_raw(
    simulator_names: Sequence[str],
    *,
    simulator_configs: dict[str, dict[str, Any]] | None = None,
    project_plugins: Sequence[CodexPluginRecommendation] | None = None,
    site_profile: SiteProfile | None = None,
    extra_plugins: Sequence[CodexPluginRecommendation] | None = None,
) -> list[CodexPluginRecommendation]:
    """Collect Codex plugin recommendations before de-duping."""
    recommendations, _issues = _collect_codex_plugin_recommendations_with_issues(
        simulator_names,
        simulator_configs=simulator_configs,
        project_plugins=project_plugins,
        site_profile=site_profile,
        extra_plugins=extra_plugins,
    )
    return recommendations


def _collect_codex_plugin_recommendations_with_issues(
    simulator_names: Sequence[str],
    *,
    simulator_configs: dict[str, dict[str, Any]] | None = None,
    project_plugins: Sequence[CodexPluginRecommendation] | None = None,
    site_profile: SiteProfile | None = None,
    extra_plugins: Sequence[CodexPluginRecommendation] | None = None,
) -> tuple[list[CodexPluginRecommendation], list[CodexPluginIssue]]:
    """Collect raw Codex plugin recommendations and collection warnings."""
    recommendations: list[CodexPluginRecommendation] = []
    adapter_recommendations, issues = _collect_adapter_codex_plugins_with_issues(
        simulator_names,
        simulator_configs=simulator_configs,
    )
    config_recommendations, config_issues = _collect_simulator_config_codex_plugins(
        simulator_names,
        simulator_configs=simulator_configs,
    )
    recommendations.extend(adapter_recommendations)
    recommendations.extend(config_recommendations)
    issues.extend(config_issues)
    if project_plugins:
        recommendations.extend(project_plugins)
    if site_profile is not None:
        recommendations.extend(site_profile.codex_plugins)
    if extra_plugins:
        recommendations.extend(extra_plugins)
    return recommendations, issues


def collect_codex_plugin_recommendations(
    simulator_names: Sequence[str],
    *,
    simulator_configs: dict[str, dict[str, Any]] | None = None,
    project_plugins: Sequence[CodexPluginRecommendation] | None = None,
    site_profile: SiteProfile | None = None,
    extra_plugins: Sequence[CodexPluginRecommendation] | None = None,
) -> list[CodexPluginRecommendation]:
    """Collect unique Codex plugin recommendations."""
    recommendations = _collect_codex_plugin_recommendations_raw(
        simulator_names,
        simulator_configs=simulator_configs,
        project_plugins=project_plugins,
        site_profile=site_profile,
        extra_plugins=extra_plugins,
    )
    return unique_codex_plugins(recommendations)


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


def build_project_codex_plugin_inventory(
    project: ProjectConfig,
) -> CodexPluginInventory:
    """Build a Codex plugin inventory for an already-loaded project."""
    site_profile = load_site_profile(project.root_dir)
    simulator_names = tuple(project.simulators.keys())
    project_recommendations, project_issues = _collect_project_config_codex_plugins(
        project
    )
    site_issues = _collect_site_config_codex_plugin_issues(
        project.root_dir,
        site_name=site_profile.name,
    )
    raw_recommendations, collection_issues = (
        _collect_codex_plugin_recommendations_with_issues(
            simulator_names,
            simulator_configs=project.simulators,
            project_plugins=project_recommendations,
            site_profile=site_profile,
        )
    )
    recommendations = unique_codex_plugins(raw_recommendations)
    return CodexPluginInventory(
        project_name=project.name,
        project_dir=project.root_dir,
        simulator_names=simulator_names,
        site_name=site_profile.name,
        recommendations=tuple(recommendations),
        collection_issues=tuple(
            collection_issues
            + project_issues
            + site_issues
            + detect_codex_plugin_conflicts(raw_recommendations)
        ),
    )


def load_project_codex_plugin_inventory(path: Path) -> CodexPluginInventory:
    """Find a project and return its Codex plugin recommendation inventory."""
    project_dir = find_project_root(path)
    project = load_project(project_dir)
    return build_project_codex_plugin_inventory(project)


def check_project_codex_plugins(path: Path) -> CodexPluginCheckResult:
    """Find a project and validate its advisory plugin recommendation metadata."""
    return check_codex_plugin_inventory(load_project_codex_plugin_inventory(path))
