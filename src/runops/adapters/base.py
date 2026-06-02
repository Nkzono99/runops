"""Abstract base class for simulator adapters.

Each simulator (e.g. lunar_pic) must implement this interface to handle
its specific input format, execution command, output detection, and
provenance collection.
"""

from __future__ import annotations

import shlex
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from runops.core.validation import ValidationIssue


class SimulatorAdapter(ABC):
    """Abstract base class for simulator-specific adapters.

    Adapters handle everything that varies between simulators:
    input file rendering, runtime resolution, command construction,
    output detection, status inference, summarization, and provenance.
    """

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        """Return the default simulators.toml entry for this adapter.

        Override in subclasses to provide simulator-specific defaults.

        Returns:
            Dictionary suitable for writing as a ``[simulators.<name>]``
            section in ``simulators.toml``.
        """
        return {
            "adapter": getattr(cls, "adapter_name", ""),
            "resolver_mode": "local_executable",
            "executable": "",
        }

    @classmethod
    def interactive_config(cls) -> dict[str, Any]:
        """Interactively prompt the user to build a simulator config.

        Uses typer.prompt() for each configurable field.
        Override in subclasses for simulator-specific prompts.

        Returns:
            Configuration dictionary for simulators.toml.
        """
        import typer

        defaults = cls.default_config()
        adapter_name = defaults.get("adapter", "")

        typer.echo(f"\n  Configuring '{adapter_name}' simulator:")

        resolver_mode = typer.prompt(
            "    Resolver mode (local_executable / local_source / package)",
            default=defaults.get("resolver_mode", "local_executable"),
        )
        executable = typer.prompt(
            "    Executable path or name",
            default=defaults.get("executable", ""),
        )

        config = {
            "adapter": adapter_name,
            "resolver_mode": resolver_mode,
            "executable": executable,
        }

        if resolver_mode == "local_source":
            source_repo = typer.prompt("    Source repository path", default="")
            build_command = typer.prompt("    Build command", default="make -j")
            config["source_repo"] = source_repo
            config["build_command"] = build_command

        # Carry over non-prompted defaults (e.g. modules)
        for key, value in defaults.items():
            if key not in config:
                config[key] = value

        return config

    @classmethod
    def case_template(cls) -> dict[str, str]:
        """Return template files for a new case.

        Override in subclasses to provide simulator-specific templates.

        Returns:
            Dict mapping filename to content string.
            Must include ``"case.toml"``.
        """
        from runops.templates import render

        name = getattr(cls, "adapter_name", "generic")
        return {
            "case.toml": render("adapters/generic/case.toml.j2", name=name),
            "summarize.py": render("adapters/generic/summarize.py"),
        }

    @classmethod
    def pip_packages(cls) -> list[str]:
        """Return pip packages to install for this simulator.

        Override in subclasses to list Python packages needed for
        analysis, post-processing, or utilities.

        Returns:
            List of pip package specifiers (e.g. ``["emout", "h5py"]``).
        """
        return []

    @classmethod
    def doc_repos(cls) -> list[tuple[str, str]]:
        """Return optional documentation/reference repositories.

        Override in subclasses to list Git repositories that contain parameter
        references, usage examples, or documentation that AI agents and users
        can consult when the project opts into local refs mirrors.

        Returns:
            List of ``(clone_url, dest_dir_name)`` tuples.
            ``dest_dir_name`` is the directory name under the project's
            optional ``refs/`` mirror directory.
        """
        return []

    @classmethod
    def knowledge_sources(cls) -> dict[str, list[str]]:
        """Return glob patterns for knowledge-relevant files per doc repo.

        Override in subclasses to specify which files in each reference
        repository should be indexed into the ``.runops/knowledge/`` directory
        when that repository exists under the optional ``refs/`` mirror.

        Returns:
            Dictionary mapping ``dest_dir_name`` (from :meth:`doc_repos`)
            to a list of glob patterns relative to the repo root.
        """
        return {}

    @classmethod
    def parameter_schema(cls) -> dict[str, dict[str, Any]]:
        """Return machine-readable parameter metadata.

        Override in subclasses to provide parameter definitions including
        type, unit, valid range, constraints, derivation formulas, and
        interdependencies.

        Returns:
            Dict mapping dot-notation parameter paths to metadata dicts.
            Each metadata dict may contain keys: ``type``, ``unit``,
            ``description``, ``range`` (``[min, max]``, ``None`` =
            unbounded), ``default``, ``constraints`` (list of
            constraint names), ``derived_from`` (formula string),
            ``interdependencies`` (list of related parameter paths).
        """
        return {}

    @classmethod
    def default_plot_recipes(cls) -> dict[str, dict[str, Any]]:
        """Return adapter-aware survey plot recipes.

        Each recipe may define ``description``, ``x``, ``y``, ``kind``,
        ``group_by``, and ``title``. ``x`` / ``y`` / ``group_by`` may be
        either a string or a list of fallback column names.
        """
        return {}

    def validate_params(
        self,
        case_data: dict[str, Any],
    ) -> list[ValidationIssue]:
        """Validate parameters against physics constraints.

        Called before run creation to catch configuration errors early.
        Override in subclasses to implement simulator-specific checks.

        Args:
            case_data: Case data dict with ``"case"`` and ``"params"``
                sections (same structure as :meth:`render_inputs`).

        Returns:
            List of :class:`ValidationIssue` instances.
            Empty list means no issues found.
        """
        return []

    @classmethod
    def required_outputs(cls) -> dict[str, str]:
        """Return output categories required before a run is analysis-ready.

        Keys must match the top-level labels returned by
        :meth:`detect_outputs`; values are short human-readable descriptions.
        Adapters that cannot define simulator-specific requirements should
        return an empty mapping.
        """
        return {}

    @classmethod
    def agent_guide(cls) -> str:
        """Return AI agent guide for this simulator as markdown.

        Override in subclasses to provide simulator-specific knowledge
        including input/output formats, key parameters, typical
        workflows, and documentation references.

        Returns:
            Markdown string for inclusion in CLAUDE.md / AGENTS.md.
        """
        name = getattr(cls, "adapter_name", cls.__name__)
        return f"### {name}\n\nNo detailed guide available.\n"

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the canonical name of this adapter."""
        ...

    @abstractmethod
    def render_inputs(self, case_data: dict[str, Any], run_dir: Path) -> list[str]:
        """Generate simulator input files in the run directory.

        Args:
            case_data: Merged case/survey parameters.
            run_dir: Target run directory.

        Returns:
            List of relative paths to generated input files.
        """
        ...

    @abstractmethod
    def resolve_runtime(
        self, simulator_config: dict[str, Any], resolver_mode: str
    ) -> dict[str, Any]:
        """Resolve the simulator runtime (executable, build, etc.).

        Args:
            simulator_config: Simulator section from simulators.toml.
            resolver_mode: One of "package", "local_source", "local_executable".

        Returns:
            Runtime information dictionary including executable path.
        """
        ...

    @abstractmethod
    def build_program_command(
        self, runtime_info: dict[str, Any], run_dir: Path
    ) -> list[str]:
        """Build the simulator execution command (without MPI launcher prefix).

        Args:
            runtime_info: Output from resolve_runtime.
            run_dir: The run directory.

        Returns:
            Command as a list of strings.
        """
        ...

    def build_version_capture_commands(
        self,
        runtime_info: dict[str, Any],
        program_cmd: list[str],
        run_dir: Path,
    ) -> list[str]:
        """Return shell commands that record simulator version metadata.

        The default implementation probes ``--version`` and ``-V`` on the
        resolved executable and writes the output to ``SIMULATOR_VERSION.txt``
        in the run's ``work/`` directory. Failures are swallowed so the main
        simulation is not blocked by missing version flags.
        """
        executable = str(runtime_info.get("executable", "")).strip()
        if not executable and program_cmd:
            executable = str(program_cmd[0]).strip()
        if not executable:
            return []

        quoted = shlex.quote(executable)
        output_path = shlex.quote(str(run_dir / "work" / "SIMULATOR_VERSION.txt"))
        display = shlex.quote(f"executable: {executable}")
        return [
            (
                "( "
                f"printf '%s\\n' {display}; "
                "date -Iseconds; "
                f"{quoted} --version || {quoted} -V || "
                "printf '%s\\n' 'version probe unsupported'"
                f" ) > {output_path} 2>&1 || true"
            )
        ]

    @abstractmethod
    def detect_outputs(self, run_dir: Path) -> dict[str, Any]:
        """Detect output files produced by the simulation.

        Args:
            run_dir: The run directory.

        Returns:
            Dictionary describing detected outputs.
        """
        ...

    @abstractmethod
    def detect_status(self, run_dir: Path) -> str:
        """Infer simulation completion status from output files.

        Args:
            run_dir: The run directory.

        Returns:
            A status string (e.g. "completed", "failed").
        """
        ...

    @abstractmethod
    def summarize(self, run_dir: Path) -> dict[str, Any]:
        """Extract key metrics from simulation outputs.

        Args:
            run_dir: The run directory.

        Returns:
            Summary dictionary for analysis/summary.json.
        """
        ...

    @abstractmethod
    def collect_provenance(self, runtime_info: dict[str, Any]) -> dict[str, Any]:
        """Collect code provenance for manifest recording.

        Args:
            runtime_info: Output from resolve_runtime.

        Returns:
            Provenance dictionary (git commit, exe hash, etc.).
        """
        ...
