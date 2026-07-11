"""Declarative metadata for the EMSES adapter."""

from __future__ import annotations

from typing import Any

from runops.core.codex_plugin import CodexPluginRecommendation


def default_config() -> dict[str, Any]:
    """Return default simulators.toml entry for EMSES."""
    return {
        "adapter": "emses",
        "resolver_mode": "package",
        "executable": "mpiemses3D",
    }


def required_outputs() -> dict[str, str]:
    """Return EMSES outputs required for analysis readiness."""
    return {"hdf5_fields": "EMSES HDF5 field output files"}


def interactive_config() -> dict[str, Any]:
    """Interactively prompt for EMSES configuration."""
    import typer

    typer.echo("\n  Configuring 'emses' simulator (EMSES PIC):")

    resolver_mode = typer.prompt(
        "    Resolver mode (package / local_executable / local_source)",
        default="package",
    )
    executable = typer.prompt(
        "    Executable path or name",
        default="mpiemses3D",
    )

    config: dict[str, Any] = {
        "adapter": "emses",
        "resolver_mode": resolver_mode,
        "executable": executable,
    }

    if resolver_mode == "local_source":
        config["source_repo"] = typer.prompt(
            "    EMSES source repository path", default=""
        )
        config["build_command"] = typer.prompt("    Build command", default="make -j")

    return config


def case_template() -> dict[str, str]:
    """Return template files for a new EMSES case."""
    from runops.templates import load_static

    return {
        "case.toml": load_static("adapters/emses/case.toml"),
        "plasma.toml": load_static("adapters/emses/plasma.toml"),
        "summarize.py": load_static("adapters/emses/summarize.py"),
    }


def pip_packages() -> list[str]:
    """Return pip packages for EMSES (simulator + analysis tools)."""
    return [
        "MPIEMSES3D @ git+https://github.com/CS12-Laboratory/MPIEMSES3D.git",
        "emout",
        "h5py",
        "matplotlib",
        "numpy",
    ]


def doc_repos() -> list[tuple[str, str]]:
    """Return documentation repos for EMSES."""
    return [
        (
            "https://github.com/CS12-Laboratory/MPIEMSES3D.git",
            "MPIEMSES3D",
        ),
        (
            "https://github.com/Nkzono99/emout.git",
            "emout",
        ),
    ]


def knowledge_sources() -> dict[str, list[str]]:
    """Return knowledge-relevant file patterns for EMSES repos."""
    return {
        "MPIEMSES3D": [
            "README.md",
            "docs/**/*.md",
            "schemas/*.json",
            "examples/**/*.toml",
            "cookbook/COOKBOOK.md",
            "cookbook/index.toml",
            "cookbook/**/*.toml",
            "cookbook/**/*.md",
        ],
        "emout": [
            "README.md",
            "docs/agent-user-guide.md",
        ],
    }


def codex_plugins() -> list[CodexPluginRecommendation]:
    """Return Codex plugins recommended for EMSES projects."""
    return [
        CodexPluginRecommendation(
            name="mpiemses3d-context",
            display_name="MPIEMSES3D Context",
            reason=(
                "MPIEMSES3D input review, parameter design, run diagnosis, "
                "output analysis, and simulator learning guides."
            ),
            install_hint=(
                "pip install mpiemses3d-tools\nmpiemses-codex-plugin install"
            ),
            activation_hint=(
                "Open Codex /plugins, install `MPIEMSES3D Context`, then "
                "start a new Codex thread."
            ),
            visibility="private-or-gated",
            source="simulator:emses",
            capabilities=(
                "input-review",
                "parameter-design",
                "run-diagnose",
                "output-analysis",
                "method-summary",
                "simulator-guide",
                "cookbook",
                "issue-report",
            ),
        ),
        CodexPluginRecommendation(
            name="emout-context",
            display_name="emout Context",
            reason=(
                "EMSES output loading, visualization script generation, "
                "unit conversion, remote_figure workflows, and emout "
                "troubleshooting."
            ),
            install_hint=(
                "codex plugin marketplace add Nkzono99/emout "
                "--ref main "
                "--sparse .agents/plugins "
                "--sparse plugins/emout-context\n"
                "codex plugin add emout-context@emout"
            ),
            activation_hint=(
                "Restart Codex or start a new Codex thread after installing."
            ),
            visibility="public",
            source="simulator:emses",
            capabilities=(
                "output-analysis",
                "visualization-script",
                "visualization-workflow",
                "script-review",
                "output-diagnose",
                "issue-report",
                "feedback-report",
            ),
        ),
    ]


def parameter_schema() -> dict[str, dict[str, Any]]:
    """Return EMSES parameter schema."""
    return {
        "jobcon.nstep": {
            "type": "int",
            "unit": "",
            "description": "Total simulation time steps",
            "range": [1, None],
            "default": 10000,
            "constraints": [],
            "interdependencies": [],
        },
        "tmgrid.dt": {
            "type": "float",
            "unit": "1/omega_pe",
            "description": "Time step in normalized units",
            "range": [0.0, None],
            "default": 1.0,
            "constraints": ["cfl_condition"],
            "derived_from": "Must satisfy dt < dx / cv",
            "interdependencies": [
                "tmgrid.nx",
                "plasma.cv",
            ],
        },
        "tmgrid.nx": {
            "type": "int",
            "unit": "cells",
            "description": "Grid cells in X direction",
            "range": [1, None],
            "default": 64,
            "constraints": ["debye_resolution", "grid_divisibility"],
            "interdependencies": ["mpi.nodes"],
        },
        "tmgrid.ny": {
            "type": "int",
            "unit": "cells",
            "description": "Grid cells in Y direction",
            "range": [1, None],
            "default": 64,
            "constraints": ["debye_resolution", "grid_divisibility"],
            "interdependencies": ["mpi.nodes"],
        },
        "tmgrid.nz": {
            "type": "int",
            "unit": "cells",
            "description": "Grid cells in Z direction",
            "range": [1, None],
            "default": 64,
            "constraints": ["debye_resolution", "grid_divisibility"],
            "interdependencies": ["mpi.nodes"],
        },
        "plasma.cv": {
            "type": "float",
            "unit": "dx/dt_norm",
            "description": "Speed of light in normalized units",
            "range": [0.0, None],
            "default": 1.0,
            "constraints": ["cfl_condition"],
            "interdependencies": ["tmgrid.dt"],
        },
        "mpi.nodes": {
            "type": "list[int]",
            "unit": "",
            "description": (
                "Domain decomposition [nxdiv, nydiv, nzdiv]. Product must equal ntasks."
            ),
            "range": [1, None],
            "constraints": [
                "domain_decomp_consistency",
                "grid_divisibility",
            ],
            "interdependencies": [
                "tmgrid.nx",
                "tmgrid.ny",
                "tmgrid.nz",
            ],
        },
        "species.N.wp": {
            "type": "float",
            "unit": "omega_pe",
            "description": "Plasma frequency of species N",
            "range": [0.0, None],
            "derived_from": "sqrt(n * q^2 / (m * eps0))",
            "constraints": ["debye_resolution"],
            "interdependencies": ["species.N.qm", "tmgrid.nx"],
        },
        "species.N.qm": {
            "type": "float",
            "unit": "e/m_e",
            "description": "Charge-to-mass ratio of species N",
            "interdependencies": ["species.N.wp"],
        },
        "species.N.npin": {
            "type": "int",
            "unit": "",
            "description": "Number of macro-particles for species N",
            "range": [0, None],
        },
        "emfield.ex0": {
            "type": "float",
            "unit": "normalized",
            "description": "External electric field (X)",
            "default": 0.0,
        },
        "emfield.bx0": {
            "type": "float",
            "unit": "normalized",
            "description": "External magnetic field (X)",
            "default": 0.0,
        },
    }


def default_plot_recipes() -> dict[str, dict[str, Any]]:
    """Return default survey plot recipes for EMSES studies."""
    return {
        "completion-vs-dt": {
            "description": (
                "Check how far each run advanced as the EMSES timestep changes."
            ),
            "x": ["param.tmgrid.dt", "dt"],
            "y": ["last_step"],
            "kind": "line",
            "group_by": ["origin.case"],
            "title": "EMSES completion vs dt",
        },
        "progress-vs-target": {
            "description": (
                "Compare achieved steps against requested nstep across runs."
            ),
            "x": ["nstep"],
            "y": ["last_step"],
            "kind": "scatter",
            "group_by": ["origin.case"],
            "title": "EMSES progress vs target steps",
        },
        "field-output-vs-nx": {
            "description": (
                "Track how many HDF5 field outputs were produced at each x-grid size."
            ),
            "x": ["param.tmgrid.nx", "nx"],
            "y": ["output_counts.hdf5_fields"],
            "kind": "line",
            "group_by": ["origin.case"],
            "title": "EMSES field outputs vs nx",
        },
    }


def agent_guide() -> str:
    """Return AI agent guide for EMSES."""
    from runops.templates import load_static

    return load_static("adapters/emses/agent_guide.md")
