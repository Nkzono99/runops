"""Project, adapter, launcher, and case reference resolution."""

from __future__ import annotations

from pathlib import Path

from runops.adapters import get as get_adapter
from runops.adapters.base import SimulatorAdapter
from runops.adapters.registry import AdapterImportError, load_from_config
from runops.core.case import CaseData
from runops.core.exceptions import ProjectConfigError
from runops.core.project import ProjectConfig, find_project_root, load_project
from runops.launchers.base import Launcher, load_launchers


def load_project_from_path(path: Path) -> ProjectConfig:
    """Locate the project root for a path and load its configuration."""
    root = find_project_root(path)
    return load_project(root)


def load_adapter_for_simulator(
    project: ProjectConfig,
    simulator_name: str,
) -> SimulatorAdapter:
    """Instantiate the adapter referenced by a simulator entry."""
    try:
        load_from_config(project.simulators)
    except AdapterImportError as exc:
        raise ProjectConfigError(str(exc)) from exc
    sim_config = project.simulators.get(simulator_name, {})
    adapter_name = sim_config.get("adapter", simulator_name)
    try:
        adapter_cls = get_adapter(adapter_name)
    except KeyError as exc:
        raise ProjectConfigError(str(exc)) from exc
    return adapter_cls()


def load_launcher_for_name(
    project: ProjectConfig,
    launcher_name: str,
) -> Launcher:
    """Instantiate a launcher from project configuration."""
    try:
        launchers = load_launchers(project.launchers)
    except Exception as exc:
        raise ProjectConfigError(f"Error loading launchers: {exc}") from exc

    if launcher_name not in launchers:
        available = sorted(launchers.keys())
        raise ProjectConfigError(
            f"Launcher profile '{launcher_name}' not found. Available: {available}"
        )
    return launchers[launcher_name]


def validate_case_references(project: ProjectConfig, case_data: CaseData) -> None:
    """Ensure a case refers to known simulator and launcher entries."""
    if case_data.simulator not in project.simulators:
        available = ", ".join(project.simulators) or "(none)"
        raise ProjectConfigError(
            f"simulator '{case_data.simulator}' in case.toml "
            f"not found in simulators.toml. Available: {available}"
        )
    if case_data.launcher not in project.launchers:
        available = ", ".join(project.launchers) or "(none)"
        raise ProjectConfigError(
            f"launcher '{case_data.launcher}' in case.toml "
            f"not found in launchers.toml. Available: {available}"
        )
