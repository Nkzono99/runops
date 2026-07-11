"""Project-level Codex plugin inventory orchestration."""

from __future__ import annotations

from pathlib import Path

from runops.core.codex_plugin import unique_codex_plugins
from runops.core.project import ProjectConfig, find_project_root, load_project
from runops.core.site import load_site_profile

from .discovery import (
    _collect_codex_plugin_recommendations_with_issues,
    _collect_project_config_codex_plugins,
    _collect_site_config_codex_plugin_issues,
)
from .models import CodexPluginCheckResult, CodexPluginInventory
from .validation import check_codex_plugin_inventory, detect_codex_plugin_conflicts


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
