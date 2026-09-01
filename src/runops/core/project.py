"""Project loading and validation.

Handles reading runops.toml, simulators.toml, and launchers.toml,
and locating the project root by walking up directories.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from runops.core.exceptions import ProjectConfigError, ProjectNotFoundError
from runops.core.knowledge_source import KnowledgeConfig, load_knowledge_config
from runops.core.research import ResearchBudget, research_budget_from_raw

_PROJECT_FILE = "runops.toml"
_SIMULATORS_FILE = "simulators.toml"
_LAUNCHERS_FILE = "launchers.toml"


@dataclass(frozen=True)
class ExperimentPolicy:
    """Project-wide admission and work-in-progress limits for Experiments."""

    require_experiment: bool = False
    max_active_experiments: int = 5
    default_max_materialized_runs: int = 3
    max_unreviewed_completed_runs: int = 12


@dataclass(frozen=True)
class ProjectConfig:
    """Immutable representation of a runops project configuration.

    Attributes:
        name: Project name from runops.toml.
        description: Optional project description.
        root_dir: Absolute path to the project root directory.
        simulators: Simulator configurations from simulators.toml.
        launchers: Launcher configurations from launchers.toml.
        raw: The raw parsed runops.toml dictionary.
    """

    name: str
    description: str
    root_dir: Path
    simulators: dict[str, dict[str, Any]] = field(default_factory=dict)
    launchers: dict[str, dict[str, Any]] = field(default_factory=dict)
    knowledge: KnowledgeConfig | None = None
    research_budget: ResearchBudget = field(default_factory=ResearchBudget)
    experiment_policy: ExperimentPolicy = field(default_factory=ExperimentPolicy)
    raw: dict[str, Any] = field(default_factory=dict)


def _read_toml(path: Path) -> dict[str, Any]:
    """Read and parse a TOML file.

    Args:
        path: Path to the TOML file.

    Returns:
        Parsed TOML dictionary.

    Raises:
        ProjectConfigError: If the file cannot be read or parsed.
    """
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        raise ProjectConfigError(f"File not found: {path}") from None
    except tomllib.TOMLDecodeError as e:
        raise ProjectConfigError(f"Invalid TOML in {path}: {e}") from e


def load_project(project_dir: Path) -> ProjectConfig:
    """Load and validate a runops project from its root directory.

    Reads runops.toml (required), simulators.toml (optional),
    and launchers.toml (optional).

    Args:
        project_dir: Root directory of the runops project.

    Returns:
        Validated ProjectConfig instance.

    Raises:
        ProjectConfigError: If runops.toml is missing or invalid.
    """
    project_dir = project_dir.resolve()
    project_file = project_dir / _PROJECT_FILE

    if not project_file.exists():
        raise ProjectConfigError(f"{_PROJECT_FILE} not found in {project_dir}")

    raw = _read_toml(project_file)

    project_section = raw.get("project")
    if not isinstance(project_section, dict):
        raise ProjectConfigError(
            f"Missing or invalid [project] section in {project_file}"
        )

    name = project_section.get("name")
    if not isinstance(name, str) or not name:
        raise ProjectConfigError(f"Missing or empty 'project.name' in {project_file}")

    description = project_section.get("description", "")
    if not isinstance(description, str):
        description = str(description)

    # Load optional simulators.toml
    simulators: dict[str, dict[str, Any]] = {}
    simulators_file = project_dir / _SIMULATORS_FILE
    if simulators_file.exists():
        sim_raw = _read_toml(simulators_file)
        sim_section = sim_raw.get("simulators", {})
        if isinstance(sim_section, dict):
            simulators = sim_section

    # Load optional launchers.toml
    launchers: dict[str, dict[str, Any]] = {}
    launchers_file = project_dir / _LAUNCHERS_FILE
    if launchers_file.exists():
        launcher_raw = _read_toml(launchers_file)
        launcher_section = launcher_raw.get("launchers", {})
        if isinstance(launcher_section, dict):
            launchers = launcher_section

    # Load optional [knowledge] section
    knowledge: KnowledgeConfig | None = None
    if "knowledge" in raw:
        knowledge = load_knowledge_config(project_dir)

    return ProjectConfig(
        name=name,
        description=description,
        root_dir=project_dir,
        simulators=simulators,
        launchers=launchers,
        knowledge=knowledge,
        research_budget=research_budget_from_raw(raw),
        experiment_policy=_parse_experiment_policy(raw, project_file),
        raw=raw,
    )


def _parse_experiment_policy(raw: dict[str, Any], path: Path) -> ExperimentPolicy:
    """Parse optional ``[experiments.policy]`` without breaking legacy projects."""
    experiments = raw.get("experiments")
    if experiments is None:
        return ExperimentPolicy()
    if not isinstance(experiments, dict):
        raise ProjectConfigError(f"[experiments] must be a table in {path}")

    policy = experiments.get("policy")
    if policy is None:
        return ExperimentPolicy()
    if not isinstance(policy, dict):
        raise ProjectConfigError(f"[experiments.policy] must be a table in {path}")

    defaults = ExperimentPolicy()
    require_experiment = policy.get(
        "require_experiment",
        defaults.require_experiment,
    )
    if not isinstance(require_experiment, bool):
        raise ProjectConfigError(
            f"experiments.policy.require_experiment must be a boolean in {path}"
        )

    max_active_experiments = _parse_positive_policy_int(
        policy,
        "max_active_experiments",
        defaults.max_active_experiments,
        path,
    )
    default_max_materialized_runs = _parse_positive_policy_int(
        policy,
        "default_max_materialized_runs",
        defaults.default_max_materialized_runs,
        path,
    )
    max_unreviewed_completed_runs = _parse_non_negative_policy_int(
        policy,
        "max_unreviewed_completed_runs",
        defaults.max_unreviewed_completed_runs,
        path,
    )
    return ExperimentPolicy(
        require_experiment=require_experiment,
        max_active_experiments=max_active_experiments,
        default_max_materialized_runs=default_max_materialized_runs,
        max_unreviewed_completed_runs=max_unreviewed_completed_runs,
    )


def _parse_positive_policy_int(
    policy: dict[str, Any],
    key: str,
    default: int,
    path: Path,
) -> int:
    value = policy.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ProjectConfigError(
            f"experiments.policy.{key} must be a positive integer in {path}"
        )
    return value


def _parse_non_negative_policy_int(
    policy: dict[str, Any],
    key: str,
    default: int,
    path: Path,
) -> int:
    value = policy.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ProjectConfigError(
            f"experiments.policy.{key} must be a non-negative integer in {path}"
        )
    return value


def find_project_root(start: Path) -> Path:
    """Walk up from *start* to locate the nearest runops.toml.

    Args:
        start: Directory to begin searching from.

    Returns:
        Path to the project root directory (containing runops.toml).

    Raises:
        ProjectNotFoundError: If no runops.toml is found up to
            the filesystem root.
    """
    current = start.resolve()

    # If start is a file, begin from its parent
    if current.is_file():
        current = current.parent

    while True:
        if (current / _PROJECT_FILE).exists():
            return current
        parent = current.parent
        if parent == current:
            # Reached filesystem root
            break
        current = parent

    raise ProjectNotFoundError(
        f"No {_PROJECT_FILE} found in {start} or any parent directory"
    )
