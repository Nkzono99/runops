"""Codex plugin recommendation discovery and collection."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from runops.core.codex_plugin import (
    CodexPluginRecommendation,
    codex_plugin_from_mapping,
    unique_codex_plugins,
)
from runops.core.project import ProjectConfig
from runops.core.site import SiteProfile

from .models import CodexPluginIssue

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

_SITE_FILE = "site.toml"
_INVALID_CAPABILITIES_MESSAGE = (
    "Codex plugin capabilities must be a string or a TOML array of non-empty strings."
)


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
