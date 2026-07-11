"""Declarative metadata for the BEACH adapter."""

from __future__ import annotations

from typing import Any

from runops.core.codex_plugin import CodexPluginRecommendation


def default_config() -> dict[str, Any]:
    """Return default simulators.toml entry for BEACH."""
    return {
        "adapter": "beach",
        "resolver_mode": "package",
        "executable": "beach",
    }


def required_outputs() -> dict[str, str]:
    """Return BEACH outputs required for analysis readiness."""
    return {"summary": "BEACH summary.txt completion summary"}


def interactive_config() -> dict[str, Any]:
    """Interactively prompt for BEACH configuration."""
    import typer

    typer.echo("\n  Configuring 'beach' simulator (BEACH BEM):")

    resolver_mode = typer.prompt(
        "    Resolver mode (package / local_executable / local_source)",
        default="package",
    )
    executable = typer.prompt(
        "    Executable path or name",
        default="beach",
    )

    default_modules = ["intel/2023.2", "intelmpi/2023.2"]
    config: dict[str, Any] = {
        "adapter": "beach",
        "resolver_mode": resolver_mode,
        "executable": executable,
        "modules": default_modules,
    }

    if resolver_mode == "local_source":
        config["source_repo"] = typer.prompt(
            "    BEACH source repository path", default=""
        )
        config["build_command"] = typer.prompt(
            "    Build command", default="make build"
        )

    if typer.confirm("    Customize module list?", default=False):
        modules_str = typer.prompt(
            "    Modules (comma-separated)",
            default=", ".join(default_modules),
        )
        config["modules"] = [m.strip() for m in modules_str.split(",") if m.strip()]

    return config


def case_template() -> dict[str, str]:
    """Return template files for a new BEACH case."""
    from runops.templates import load_static

    return {
        "case.toml": load_static("adapters/beach/case.toml"),
        "beach.toml": load_static("adapters/beach/beach.toml"),
        "summarize.py": load_static("adapters/beach/summarize.py"),
    }


def pip_packages() -> list[str]:
    """Return pip packages for BEACH (simulator + analysis tools)."""
    return [
        "beach-bem",
        "matplotlib",
        "numpy",
        "pandas",
    ]


def doc_repos() -> list[tuple[str, str]]:
    """Return documentation repos for BEACH."""
    return [
        (
            "https://github.com/Nkzono99/beach.git",
            "beach",
        ),
    ]


def knowledge_sources() -> dict[str, list[str]]:
    """Return knowledge-relevant file patterns for BEACH repos."""
    return {
        "beach": [
            "README.md",
            "docs/**/*.md",
            "schemas/*.json",
            "examples/**/*.toml",
            "cookbook/COOKBOOK.md",
            "cookbook/index.toml",
            "cookbook/**/*.toml",
            "cookbook/**/*.md",
        ],
    }


def codex_plugins() -> list[CodexPluginRecommendation]:
    """Return Codex plugins recommended for BEACH projects."""
    return [
        CodexPluginRecommendation(
            name="beach-context",
            display_name="BEACH Context",
            reason=(
                "BEACH configuration review, run diagnosis, case design, "
                "output analysis, simulator learning, method summaries, "
                "and issue report drafting."
            ),
            install_hint=(
                "codex plugin marketplace add Nkzono99/BEACH "
                "--ref main "
                "--sparse .agents/plugins "
                "--sparse plugins/beach-context"
            ),
            activation_hint=(
                "Open Codex /plugins, install `BEACH Context`, then "
                "restart Codex or start a new Codex thread."
            ),
            visibility="public",
            source="simulator:beach",
            capabilities=(
                "config-review",
                "case-design",
                "run-diagnose",
                "output-analysis",
                "method-summary",
                "simulator-guide",
                "cookbook",
                "issue-report",
            ),
        )
    ]


def parameter_schema() -> dict[str, dict[str, Any]]:
    """Return BEACH parameter schema."""
    return {
        "sim.dt": {
            "type": "float",
            "unit": "s",
            "description": "Time step",
            "range": [0.0, None],
            "default": 1.0e-6,
            "constraints": ["timestep_stability"],
            "interdependencies": [
                "environment.electron_density",
            ],
        },
        "sim.max_step": {
            "type": "int",
            "unit": "",
            "description": "Maximum simulation steps",
            "range": [1, None],
            "default": 1000,
        },
        "sim.batch_count": {
            "type": "int",
            "unit": "",
            "description": "Number of batches",
            "range": [1, None],
            "default": 100,
        },
        "sim.field_solver": {
            "type": "str",
            "description": "Field solver type (fmm, direct, etc.)",
            "default": "fmm",
        },
        "environment.electron_density": {
            "type": "float",
            "unit": "m^-3",
            "description": "Background electron number density",
            "range": [0.0, None],
            "default": 1.0e12,
            "constraints": ["charge_neutrality"],
            "interdependencies": [
                "environment.ion_density",
            ],
        },
        "environment.electron_temperature": {
            "type": "float",
            "unit": "eV",
            "description": "Electron temperature",
            "range": [0.0, None],
            "default": 1.0,
        },
        "environment.ion_density": {
            "type": "float",
            "unit": "m^-3",
            "description": "Background ion number density",
            "range": [0.0, None],
            "default": 1.0e12,
            "constraints": ["charge_neutrality"],
            "interdependencies": [
                "environment.electron_density",
            ],
        },
        "environment.ion_temperature": {
            "type": "float",
            "unit": "eV",
            "description": "Ion temperature",
            "range": [0.0, None],
            "default": 1.0,
        },
        "mesh.obj_path": {
            "type": "str",
            "description": "Path to OBJ mesh file",
            "constraints": ["mesh_file_exists"],
        },
    }


def default_plot_recipes() -> dict[str, dict[str, Any]]:
    """Return default survey plot recipes for BEACH studies."""
    return {
        "charge-history-vs-dt": {
            "description": (
                "Check charge-history coverage as the BEACH timestep changes."
            ),
            "x": ["param.sim.dt", "sim_dt"],
            "y": ["output_counts.charge_history"],
            "kind": "line",
            "group_by": ["param.sim.field_solver", "sim_field_solver"],
            "title": "BEACH charge-history coverage vs dt",
        },
        "potential-history-vs-steps": {
            "description": (
                "Compare potential-history output availability against max_step."
            ),
            "x": ["param.sim.max_step", "sim_max_step"],
            "y": ["output_counts.potential_history"],
            "kind": "line",
            "group_by": ["param.sim.field_solver", "sim_field_solver"],
            "title": "BEACH potential-history coverage vs max_step",
        },
    }


def agent_guide() -> str:
    """Return AI agent guide for BEACH."""
    from runops.templates import load_static

    return load_static("adapters/beach/agent_guide.md")
