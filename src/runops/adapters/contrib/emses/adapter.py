"""EMSES (Electromagnetic Particle-in-Cell) simulator adapter.

Handles EMSES TOML configuration (plasma.toml), HDF5/ASCII output
detection, and MPI-based execution via srun.

EMSES now uses TOML configuration (format_version 2 with structured
``[[species]]``, ``[[ptcond.objects]]``, etc.).  Legacy Fortran
namelist (plasma.inp) is no longer required.
"""

from __future__ import annotations

import logging
import shutil
import sys
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

try:
    import tomli_w
except ImportError:
    tomli_w = None  # type: ignore[assignment]

from runops.adapters._provenance import (
    collect_executable_provenance as _collect_executable_provenance,
)
from runops.adapters._runtime import (
    ExecutableRuntimeDefaults as _ExecutableRuntimeDefaults,
)
from runops.adapters._runtime import (
    resolve_executable_runtime as _resolve_executable_runtime,
)
from runops.adapters._utils.toml_utils import apply_dotted_overrides
from runops.adapters.base import SimulatorAdapter
from runops.adapters.contrib._paths import relative_to_run
from runops.adapters.contrib.emses import diagnostics as _diagnostics
from runops.adapters.contrib.emses import metadata as _metadata
from runops.adapters.contrib.emses.constants import (
    INPUT_DIR,
    LATEST_OUTPUT_DIR,
    WORK_DIR,
)
from runops.adapters.contrib.emses.validation import (
    resolve_config as resolve_emses_config,
)
from runops.adapters.contrib.emses.validation import (
    validate_params as validate_emses_params,
)
from runops.core.codex_plugin import CodexPluginRecommendation
from runops.core.validation import ValidationIssue

logger = logging.getLogger(__name__)

_RUNTIME_DEFAULTS = _ExecutableRuntimeDefaults(
    executable="mpiemses3D",
    build_command="",
    discover_venv=True,
    require_executable=False,
)


class EmseAdapter(SimulatorAdapter):
    """Adapter for the EMSES electromagnetic PIC simulator.

    EMSES uses TOML configuration files (``plasma.toml``) and produces
    HDF5 field data and ASCII time-series diagnostics.

    Class Attributes:
        adapter_name: Registry key for this adapter.
    """

    adapter_name: str = "emses"

    # ------------------------------------------------------------------
    # SimulatorAdapter interface
    # ------------------------------------------------------------------

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        """Return default simulators.toml entry for EMSES."""
        return _metadata.default_config()

    @classmethod
    def required_outputs(cls) -> dict[str, str]:
        """Return EMSES outputs required for analysis readiness."""
        return _metadata.required_outputs()

    @classmethod
    def interactive_config(cls) -> dict[str, Any]:
        """Interactively prompt for EMSES configuration."""
        return _metadata.interactive_config()

    @classmethod
    def case_template(cls) -> dict[str, str]:
        """Return template files for a new EMSES case."""
        return _metadata.case_template()

    @classmethod
    def pip_packages(cls) -> list[str]:
        """Return pip packages for EMSES (simulator + analysis tools)."""
        return _metadata.pip_packages()

    @classmethod
    def doc_repos(cls) -> list[tuple[str, str]]:
        """Return documentation repos for EMSES."""
        return _metadata.doc_repos()

    @classmethod
    def knowledge_sources(cls) -> dict[str, list[str]]:
        """Return knowledge-relevant file patterns for EMSES repos."""
        return _metadata.knowledge_sources()

    @classmethod
    def codex_plugins(cls) -> list[CodexPluginRecommendation]:
        """Return Codex plugins recommended for EMSES projects."""
        return _metadata.codex_plugins()

    @classmethod
    def parameter_schema(cls) -> dict[str, dict[str, Any]]:
        """Return EMSES parameter schema."""
        return _metadata.parameter_schema()

    @classmethod
    def default_plot_recipes(cls) -> dict[str, dict[str, Any]]:
        """Return default survey plot recipes for EMSES studies."""
        return _metadata.default_plot_recipes()

    def validate_params(
        self,
        case_data: dict[str, Any],
    ) -> list[ValidationIssue]:
        """Validate EMSES parameters against physics constraints."""
        return validate_emses_params(case_data)

    @staticmethod
    def _resolve_config(case_data: dict[str, Any]) -> dict[str, Any]:
        """Load template config and apply param overrides."""
        return resolve_emses_config(case_data)

    @classmethod
    def agent_guide(cls) -> str:
        """Return AI agent guide for EMSES."""
        return _metadata.agent_guide()

    @property
    def name(self) -> str:
        """Return the canonical name of this adapter."""
        return self.adapter_name

    def render_inputs(
        self,
        case_data: dict[str, Any],
        run_dir: Path,
    ) -> list[str]:
        """Generate EMSES input files in the run directory.

        Reads ``plasma.toml`` from the case directory, applies parameter
        overrides via dot-notation, and writes to ``<run_dir>/input/plasma.toml``.

        Args:
            case_data: Merged case/survey parameters.  Expects a
                ``case`` section with ``case_dir`` pointing to the
                template directory, and an optional ``params`` section.
            run_dir: Target run directory.

        Returns:
            List of relative paths to generated input files.

        Raises:
            ValueError: If the case section is missing.
            RuntimeError: If ``tomli_w`` is not installed.
        """
        case_section = case_data.get("case", {})
        if not case_section:
            msg = "case_data must contain a 'case' section"
            raise ValueError(msg)

        params = case_data.get("params", {})
        input_dir = run_dir / INPUT_DIR
        input_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / WORK_DIR / "latest").mkdir(parents=True, exist_ok=True)

        created: list[str] = []

        # Locate template plasma.toml from case directory
        case_dir_str = case_section.get("case_dir", "")
        template_config: dict[str, Any] = {}

        if case_dir_str:
            case_dir = Path(case_dir_str)
            # Look in input/ subdirectory first, then case root for compat
            for candidate in (
                case_dir / "input" / "plasma.toml",
                case_dir / "plasma.toml",
            ):
                if candidate.is_file():
                    with open(candidate, "rb") as f:
                        template_config = tomllib.load(f)
                    break

        # Also check explicit input_files list
        input_files: list[str] = case_section.get("input_files", [])
        for src_str in input_files:
            src = Path(src_str)
            if src.suffix == ".toml" and src.is_file():
                if not template_config:
                    with open(src, "rb") as f:
                        template_config = tomllib.load(f)
                elif src.name != "plasma.toml":
                    dest = input_dir / src.name
                    shutil.copy2(src, dest)
                    created.append(relative_to_run(dest, run_dir))

        # Apply parameter overrides
        if params and template_config:
            template_config = apply_dotted_overrides(template_config, params)

        # Write plasma.toml
        if template_config:
            if tomli_w is None:
                msg = "tomli_w is required to write TOML files"
                raise RuntimeError(msg)
            plasma_toml = input_dir / "plasma.toml"
            with open(plasma_toml, "wb") as f:
                tomli_w.dump(template_config, f)
            created.append(relative_to_run(plasma_toml, run_dir))

        # Copy additional input files (e.g., mesh files)
        for src_str in input_files:
            src = Path(src_str)
            if not src.is_file():
                logger.warning("Input file not found, skipping: %s", src)
                continue
            if src.suffix == ".toml":
                continue  # Already handled
            dest = input_dir / src.name
            shutil.copy2(src, dest)
            created.append(relative_to_run(dest, run_dir))

        return created

    def resolve_runtime(
        self,
        simulator_config: dict[str, Any],
        resolver_mode: str,
    ) -> dict[str, Any]:
        """Resolve the EMSES runtime (mpiemses3D executable).

        Args:
            simulator_config: Simulator section from ``simulators.toml``.
            resolver_mode: One of ``"package"``, ``"local_source"``,
                ``"local_executable"``.

        Returns:
            Runtime info dict with at least ``executable`` and
            ``resolver_mode`` keys.

        Raises:
            ValueError: If required keys are missing or mode is invalid.
        """
        return _resolve_executable_runtime(
            simulator_config,
            resolver_mode,
            defaults=_RUNTIME_DEFAULTS,
            which=shutil.which,
            start_dir=Path.cwd(),
        )

    def build_program_command(
        self,
        runtime_info: dict[str, Any],
        run_dir: Path,
    ) -> list[str]:
        """Build the EMSES execution command.

        Returns a command that runs ``mpiemses3D`` with ``plasma.toml``.

        Args:
            runtime_info: Output from :meth:`resolve_runtime`.
            run_dir: The run directory.

        Returns:
            Command as a list of strings.
        """
        executable = runtime_info.get("executable", "mpiemses3D")
        plasma_toml = f"{INPUT_DIR}/plasma.toml"
        return [executable, plasma_toml, "-o", LATEST_OUTPUT_DIR]

    def detect_outputs(self, run_dir: Path) -> dict[str, Any]:
        """Detect EMSES output files in ``work/``.

        Scans for HDF5 field data, ASCII diagnostics, and snapshot files.

        Args:
            run_dir: The run directory.

        Returns:
            Dictionary of output categories to file lists.
        """
        return _diagnostics.detect_outputs(self, run_dir)

    def probe_readiness(self, run_dir: Path) -> dict[str, Any]:
        """Return a bounded EMSES readiness observation."""
        return _diagnostics.probe_readiness(self, run_dir)

    def detect_status(self, run_dir: Path) -> str:
        """Infer EMSES simulation status from output files.

        Detection logic:

        1. If stderr contains error keywords -> ``"failed"``.
        2. If energy file shows completion to *nstep* -> ``"completed"``.
        3. If output files exist -> ``"running"``.
        4. Otherwise -> ``"unknown"``.

        Args:
            run_dir: The run directory.

        Returns:
            A status string.
        """
        return _diagnostics.detect_status(self, run_dir)

    def summarize(self, run_dir: Path) -> dict[str, Any]:
        """Extract key metrics from EMSES outputs.

        Args:
            run_dir: The run directory.

        Returns:
            Summary dictionary with status, output counts, energy data,
            and simulation parameters.
        """
        return _diagnostics.summarize(self, run_dir)

    def collect_provenance(
        self,
        runtime_info: dict[str, Any],
    ) -> dict[str, Any]:
        """Collect EMSES provenance information.

        Args:
            runtime_info: Output from :meth:`resolve_runtime`.

        Returns:
            Provenance dictionary with executable hash and git info.
        """
        provenance_info = dict(runtime_info)
        provenance_info["package_version"] = ""
        return _collect_executable_provenance(provenance_info)

    # ------------------------------------------------------------------
    # EMSES-specific helpers (used by CLI / jobgen integration)
    # ------------------------------------------------------------------

    def get_setup_commands(self, run_dir: Path) -> list[str]:
        """Return setup commands for the EMSES job script."""
        input_dir = run_dir / INPUT_DIR
        return [
            f"cp {input_dir}/plasma.toml . 2>/dev/null || true",
            "rm -f *_0000.h5",
            "date",
        ]

    def get_post_commands(self) -> list[str]:
        """Return post-execution commands."""
        return ["date"]

    def get_modules(self) -> list[str]:
        """Return default module names for EMSES.

        Returns empty list — modules are now managed via sites/*.toml
        and simulators.toml, not hardcoded in the adapter.
        """
        return []

    def get_extra_env(self) -> dict[str, str]:
        """Return default environment variables for EMSES."""
        return {"EMSES_DEBUG": "no"}

    def setup_continuation(
        self,
        source_dir: Path,
        new_dir: Path,
        nstep_override: int | None = None,
    ) -> dict[str, Any]:
        """Set up EMSES continuation from snapshot.

        Links SNAPSHOT1 from source as SNAPSHOT0 in new run,
        and updates jobcon.jobnum for restart.

        Args:
            source_dir: Completed run directory.
            new_dir: New run directory.
            nstep_override: Override nstep if given.

        Returns:
            Info dict with continuation details.
        """
        info: dict[str, Any] = {}
        work_dir = new_dir / WORK_DIR
        work_dir.mkdir(parents=True, exist_ok=True)

        # Link SNAPSHOT1 -> SNAPSHOT0
        source_snapshot = source_dir / WORK_DIR / "SNAPSHOT1"
        if source_snapshot.is_dir():
            target_link = work_dir / "SNAPSHOT0"
            if not target_link.exists():
                target_link.symlink_to(source_snapshot.resolve())
                info["snapshot_link"] = f"SNAPSHOT0 -> {source_snapshot}"

        # Update plasma.toml for restart
        plasma_toml = new_dir / INPUT_DIR / "plasma.toml"
        if plasma_toml.is_file() and tomli_w is not None:
            with open(plasma_toml, "rb") as f:
                config = tomllib.load(f)

            # Set jobnum = [1, 1] for restart
            if "jobcon" not in config:
                config["jobcon"] = {}
            config["jobcon"]["jobnum"] = [1, 1]
            info["jobnum"] = [1, 1]

            if nstep_override is not None:
                config["jobcon"]["nstep"] = nstep_override
                info["nstep"] = nstep_override

            with open(plasma_toml, "wb") as f:
                tomli_w.dump(config, f)

        return info

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _load_input_config(run_dir: Path) -> dict[str, Any]:
        """Load the plasma.toml from the run's input directory."""
        plasma_toml = run_dir / INPUT_DIR / "plasma.toml"
        if plasma_toml.is_file():
            try:
                with open(plasma_toml, "rb") as f:
                    return tomllib.load(f)
            except (tomllib.TOMLDecodeError, OSError):
                pass
        return {}

    @staticmethod
    def _get_expected_nstep(run_dir: Path) -> int | None:
        """Read ``nstep`` from the run's plasma.toml."""
        plasma_toml = run_dir / INPUT_DIR / "plasma.toml"
        if plasma_toml.is_file():
            try:
                with open(plasma_toml, "rb") as f:
                    config = tomllib.load(f)
                return int(config.get("jobcon", {}).get("nstep", 0)) or None
            except (tomllib.TOMLDecodeError, ValueError, OSError):
                pass
        return None
