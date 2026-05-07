"""BEACH (BEM + Accumulated CHarge) simulator adapter.

Handles BEACH-specific TOML configuration (beach.toml), CSV output
detection, and OpenMP/MPI hybrid execution.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
import subprocess
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

from runops.adapters._utils import find_venv
from runops.adapters._utils.toml_utils import apply_dotted_overrides
from runops.adapters.base import SimulatorAdapter
from runops.adapters.contrib._paths import relative_to_run
from runops.core.validation import ValidationIssue

logger = logging.getLogger(__name__)

INPUT_DIR = "input"
WORK_DIR = "work"
LATEST_OUTPUT_DIR = f"{WORK_DIR}/latest"

# Known BEACH output files (label -> filename)
_OUTPUT_FILES = {
    "summary": "summary.txt",
    "charges": "charges.csv",
    "mesh_triangles": "mesh_triangles.csv",
    "mesh_sources": "mesh_sources.csv",
    "charge_history": "charge_history.csv",
    "potential_history": "potential_history.csv",
    "mesh_potential": "mesh_potential.csv",
    "rng_state": "rng_state.txt",
    "performance_profile": "performance_profile.csv",
}


class BeachAdapter(SimulatorAdapter):
    """Adapter for the BEACH BEM surface-charging simulator.

    BEACH uses TOML configuration files (``beach.toml``) and produces
    CSV output files (``charges.csv``, ``summary.txt``, etc.).

    Class Attributes:
        adapter_name: Registry key for this adapter.
    """

    adapter_name: str = "beach"

    # ------------------------------------------------------------------
    # SimulatorAdapter interface
    # ------------------------------------------------------------------

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        """Return default simulators.toml entry for BEACH."""
        return {
            "adapter": "beach",
            "resolver_mode": "package",
            "executable": "beach",
        }

    @classmethod
    def required_outputs(cls) -> dict[str, str]:
        """Return BEACH outputs required for analysis readiness."""
        return {"summary": "BEACH summary.txt completion summary"}

    @classmethod
    def interactive_config(cls) -> dict[str, Any]:
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

    @classmethod
    def case_template(cls) -> dict[str, str]:
        """Return template files for a new BEACH case."""
        from runops.templates import load_static

        return {
            "case.toml": load_static("adapters/beach/case.toml"),
            "beach.toml": load_static("adapters/beach/beach.toml"),
            "summarize.py": load_static("adapters/beach/summarize.py"),
        }

    @classmethod
    def pip_packages(cls) -> list[str]:
        """Return pip packages for BEACH (simulator + analysis tools)."""
        return [
            "beach-bem",
            "matplotlib",
            "numpy",
            "pandas",
        ]

    @classmethod
    def doc_repos(cls) -> list[tuple[str, str]]:
        """Return documentation repos for BEACH."""
        return [
            (
                "https://github.com/Nkzono99/beach.git",
                "beach",
            ),
        ]

    @classmethod
    def knowledge_sources(cls) -> dict[str, list[str]]:
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

    @classmethod
    def parameter_schema(cls) -> dict[str, dict[str, Any]]:
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

    @classmethod
    def default_plot_recipes(cls) -> dict[str, dict[str, Any]]:
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

    def validate_params(
        self,
        case_data: dict[str, Any],
    ) -> list[ValidationIssue]:
        """Validate BEACH parameters against physics constraints.

        Checks: positive physical quantities, timestep stability,
        and charge neutrality.
        """
        issues: list[ValidationIssue] = []
        config = self._resolve_config(case_data)
        if not config:
            return issues

        sim = config.get("sim", {})
        env = config.get("environment", {})

        dt = sim.get("dt")
        max_step = sim.get("max_step")
        e_density = env.get("electron_density")
        e_temp = env.get("electron_temperature")
        i_density = env.get("ion_density")
        i_temp = env.get("ion_temperature")

        # Positive required checks
        positives = [
            ("sim.dt", dt),
            ("sim.max_step", max_step),
            ("environment.electron_density", e_density),
            ("environment.electron_temperature", e_temp),
            ("environment.ion_density", i_density),
            ("environment.ion_temperature", i_temp),
        ]
        for param_name, value in positives:
            if value is not None and float(value) <= 0:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        message=f"{param_name} must be positive, got {value}.",
                        parameter=param_name,
                        constraint_name="positive_required",
                    )
                )

        # Timestep stability: dt * omega_pe should be reasonable
        # omega_pe = sqrt(n_e * e^2 / (m_e * eps0))
        if dt is not None and e_density is not None and float(e_density) > 0:
            import math

            e_charge = 1.602176634e-19
            m_electron = 9.10938370e-31
            eps0 = 8.854187817e-12
            omega_pe = math.sqrt(float(e_density) * e_charge**2 / (m_electron * eps0))
            dt_omega = float(dt) * omega_pe
            if dt_omega > 0.5:
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        message=(
                            f"dt * omega_pe = {dt_omega:.3f} > 0.5. "
                            f"Time step may be too large for plasma "
                            f"timescale. Consider dt < "
                            f"{0.5 / omega_pe:.2e} s."
                        ),
                        parameter="sim.dt",
                        constraint_name="timestep_stability",
                        details={
                            "dt": float(dt),
                            "omega_pe": omega_pe,
                            "dt_omega_pe": dt_omega,
                            "recommended_max_dt": 0.5 / omega_pe,
                        },
                    )
                )

        # Charge neutrality
        if e_density is not None and i_density is not None and float(e_density) > 0:
            ratio = float(i_density) / float(e_density)
            if abs(ratio - 1.0) > 0.1:
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        message=(
                            f"Charge neutrality: ion/electron density "
                            f"ratio = {ratio:.3f}. Significant imbalance "
                            f"may be intentional but verify."
                        ),
                        parameter="environment.ion_density",
                        constraint_name="charge_neutrality",
                        details={
                            "electron_density": float(e_density),
                            "ion_density": float(i_density),
                            "ratio": ratio,
                        },
                    )
                )

        return issues

    @staticmethod
    def _resolve_config(case_data: dict[str, Any]) -> dict[str, Any]:
        """Load template config and apply param overrides."""
        case_section = case_data.get("case", {})
        params = case_data.get("params", {})
        config: dict[str, Any] = {}

        case_dir_str = case_section.get("case_dir", "")
        if case_dir_str:
            case_dir = Path(case_dir_str)
            for name in ("beach.toml", "beach_template.toml"):
                # Look in input/ subdirectory first, then case root for compat
                for candidate in (case_dir / "input" / name, case_dir / name):
                    if candidate.is_file():
                        with open(candidate, "rb") as f:
                            config = tomllib.load(f)
                        break
                if config:
                    break

        if params and config:
            config = apply_dotted_overrides(config, params)

        return config

    @classmethod
    def agent_guide(cls) -> str:
        """Return AI agent guide for BEACH."""
        from runops.templates import load_static

        return load_static("adapters/beach/agent_guide.md")

    @property
    def name(self) -> str:
        """Return the canonical name of this adapter."""
        return self.adapter_name

    def render_inputs(
        self,
        case_data: dict[str, Any],
        run_dir: Path,
    ) -> list[str]:
        """Generate BEACH input files in the run directory.

        Reads a ``beach.toml`` template from the case directory, applies
        parameter overrides via dot-notation, and writes the result to
        ``<run_dir>/input/beach.toml``.

        Args:
            case_data: Merged case/survey parameters.
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

        # Find template configuration
        case_dir_str = case_section.get("case_dir", "")
        template_config: dict[str, Any] = {}

        if case_dir_str:
            case_dir = Path(case_dir_str)
            for candidate_name in ("beach.toml", "beach_template.toml"):
                # Look in input/ subdirectory first, then case root for compat
                for candidate in (
                    case_dir / "input" / candidate_name,
                    case_dir / candidate_name,
                ):
                    if candidate.is_file():
                        with open(candidate, "rb") as f:
                            template_config = tomllib.load(f)
                        break
                if template_config:
                    break

        # Also check input_files list
        input_files: list[str] = case_section.get("input_files", [])
        for src_str in input_files:
            src = Path(src_str)
            if src.suffix == ".toml" and src.is_file():
                if not template_config:
                    with open(src, "rb") as f:
                        template_config = tomllib.load(f)
                elif src.name not in ("beach.toml", "beach_template.toml"):
                    dest = input_dir / src.name
                    shutil.copy2(src, dest)
                    created.append(relative_to_run(dest, run_dir))

        # Apply parameter overrides
        if params and template_config:
            template_config = apply_dotted_overrides(template_config, params)

        # Set output directory relative to the run root.
        if "output" not in template_config:
            template_config["output"] = {}
        template_config["output"]["dir"] = LATEST_OUTPUT_DIR

        # Write beach.toml
        if template_config:
            if tomli_w is None:
                msg = "tomli_w is required to write TOML files"
                raise RuntimeError(msg)
            beach_toml = input_dir / "beach.toml"
            with open(beach_toml, "wb") as f:
                tomli_w.dump(template_config, f)
            created.append(relative_to_run(beach_toml, run_dir))

        # Copy OBJ mesh files if referenced
        obj_path_str = template_config.get("mesh", {}).get("obj_path", "")
        if obj_path_str:
            obj_path = Path(obj_path_str)
            if obj_path.is_file():
                dest = input_dir / obj_path.name
                shutil.copy2(obj_path, dest)
                created.append(relative_to_run(dest, run_dir))

        return created

    def resolve_runtime(
        self,
        simulator_config: dict[str, Any],
        resolver_mode: str,
    ) -> dict[str, Any]:
        """Resolve the BEACH runtime (beach executable).

        Args:
            simulator_config: Simulator section from ``simulators.toml``.
            resolver_mode: One of ``"package"``, ``"local_source"``,
                ``"local_executable"``.

        Returns:
            Runtime info dict.

        Raises:
            ValueError: If required keys are missing or mode is invalid.
        """
        runtime: dict[str, Any] = {"resolver_mode": resolver_mode}
        executable = simulator_config.get("executable", "beach")

        venv_path = simulator_config.get("venv_path", "")
        if not venv_path:
            found = find_venv(Path.cwd())
            if found:
                venv_path = str(found)
        if venv_path:
            runtime["venv_path"] = venv_path

        if resolver_mode == "package":
            resolved = shutil.which(executable)
            runtime["executable"] = resolved if resolved else executable
            runtime["source"] = "package"

        elif resolver_mode == "local_source":
            source_repo = simulator_config.get("source_repo", "")
            if not source_repo:
                msg = "source_repo required for local_source mode"
                raise ValueError(msg)
            runtime["source_repo"] = source_repo
            runtime["executable"] = executable
            runtime["build_command"] = simulator_config.get(
                "build_command", "make build"
            )

        elif resolver_mode == "local_executable":
            exe_path = simulator_config.get("executable", "")
            if not exe_path:
                msg = "executable path required for local_executable mode"
                raise ValueError(msg)
            runtime["executable"] = exe_path

        else:
            msg = f"Unsupported resolver_mode: {resolver_mode}"
            raise ValueError(msg)

        return runtime

    def build_program_command(
        self,
        runtime_info: dict[str, Any],
        run_dir: Path,
    ) -> list[str]:
        """Build the BEACH execution command.

        Args:
            runtime_info: Output from :meth:`resolve_runtime`.
            run_dir: The run directory.

        Returns:
            Command as a list of strings.
        """
        executable = runtime_info.get("executable", "beach")
        beach_toml = f"{INPUT_DIR}/beach.toml"
        return [executable, beach_toml]

    def detect_outputs(self, run_dir: Path) -> dict[str, Any]:
        """Detect BEACH output files.

        Scans ``work/outputs/`` for known BEACH output files.

        Args:
            run_dir: The run directory.

        Returns:
            Dictionary of detected output labels to relative paths.
        """
        outputs: dict[str, Any] = {}
        work_dir = run_dir / WORK_DIR

        # Search candidate output directories
        for output_dir in (
            work_dir / "latest",
            work_dir / "outputs" / "latest",
            work_dir / "outputs",
            work_dir,
        ):
            if not output_dir.is_dir():
                continue
            for label, filename in _OUTPUT_FILES.items():
                f = output_dir / filename
                if f.is_file():
                    outputs[label] = relative_to_run(f, run_dir)
            if outputs:
                break

        # Log files
        logs: list[str] = []
        for pattern in ("stdout.*.log", "stderr.*.log", "*.out", "*.err"):
            for f in sorted(work_dir.glob(pattern)):
                logs.append(relative_to_run(f, run_dir))
        if logs:
            outputs["logs"] = logs

        return outputs

    def detect_status(self, run_dir: Path) -> str:
        """Infer BEACH simulation status from output files.

        Detection logic:

        1. If ``summary.txt`` exists -> ``"completed"``.
        2. If error logs contain error keywords -> ``"failed"``.
        3. If ``charges.csv`` exists (partial output) -> ``"running"``.
        4. Otherwise -> ``"unknown"``.

        Args:
            run_dir: The run directory.

        Returns:
            A status string.
        """
        work_dir = run_dir / WORK_DIR

        # Check for summary.txt (written on normal completion)
        for output_dir in (
            work_dir / "latest",
            work_dir / "outputs" / "latest",
            work_dir / "outputs",
            work_dir,
        ):
            if (output_dir / "summary.txt").is_file():
                return "completed"

        # Check for errors in logs
        for pattern in ("stderr.*.log", "*.err"):
            for log in work_dir.glob(pattern):
                try:
                    content = log.read_text(errors="replace")
                    if content.strip() and any(
                        kw in content.lower()
                        for kw in ("error", "fatal", "killed", "oom")
                    ):
                        return "failed"
                except OSError:
                    pass

        # Partial outputs indicate running
        for output_dir in (
            work_dir / "latest",
            work_dir / "outputs" / "latest",
            work_dir / "outputs",
            work_dir,
        ):
            if (output_dir / "charges.csv").is_file():
                return "running"

        if work_dir.is_dir() and any(work_dir.iterdir()):
            return "running"

        return "unknown"

    def summarize(self, run_dir: Path) -> dict[str, Any]:
        """Extract key metrics from BEACH outputs.

        Parses ``summary.txt`` for simulation statistics and reads
        configuration parameters from the input ``beach.toml``.

        Args:
            run_dir: The run directory.

        Returns:
            Summary dictionary.
        """
        summary: dict[str, Any] = {}
        work_dir = run_dir / WORK_DIR

        summary["status"] = self.detect_status(run_dir)

        # Parse summary.txt
        for output_dir in (
            work_dir / "latest",
            work_dir / "outputs" / "latest",
            work_dir / "outputs",
            work_dir,
        ):
            summary_file = output_dir / "summary.txt"
            if summary_file.is_file():
                try:
                    for line in summary_file.read_text(encoding="utf-8").split("\n"):
                        line = line.strip()
                        if "=" not in line:
                            continue
                        key, value = line.split("=", 1)
                        key, value = key.strip(), value.strip()
                        try:
                            summary[key] = int(value)
                        except ValueError:
                            try:
                                summary[key] = float(value)
                            except ValueError:
                                summary[key] = value
                except OSError:
                    pass
                break

        # Output counts
        outputs = self.detect_outputs(run_dir)
        summary["output_counts"] = {
            k: len(v) if isinstance(v, list) else 1 for k, v in outputs.items()
        }

        # Config parameters
        beach_toml = run_dir / INPUT_DIR / "beach.toml"
        if beach_toml.is_file():
            try:
                with open(beach_toml, "rb") as f:
                    config = tomllib.load(f)
                sim = config.get("sim", {})
                for key in ("dt", "batch_count", "max_step", "field_solver"):
                    if key in sim:
                        summary[f"sim_{key}"] = sim[key]
            except (tomllib.TOMLDecodeError, OSError):
                pass

        return summary

    def collect_provenance(
        self,
        runtime_info: dict[str, Any],
    ) -> dict[str, Any]:
        """Collect BEACH provenance information.

        Args:
            runtime_info: Output from :meth:`resolve_runtime`.

        Returns:
            Provenance dict with executable hash and git info.
        """
        provenance: dict[str, Any] = {
            "resolver_mode": runtime_info.get("resolver_mode", ""),
            "executable": runtime_info.get("executable", ""),
            "exe_hash": "",
            "git_commit": "",
            "git_dirty": False,
            "source_repo": runtime_info.get("source_repo", ""),
            "build_command": runtime_info.get("build_command", ""),
            "package_version": "",
        }

        # Executable hash
        exe_path = Path(runtime_info.get("executable", ""))
        if exe_path.is_file():
            h = hashlib.sha256()
            with exe_path.open("rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    h.update(chunk)
            provenance["exe_hash"] = f"sha256:{h.hexdigest()}"

        # Git provenance for local_source
        if runtime_info.get("resolver_mode") == "local_source":
            repo = runtime_info.get("source_repo", "")
            if repo and Path(repo).is_dir():
                try:
                    result = subprocess.run(
                        ["git", "rev-parse", "HEAD"],
                        capture_output=True,
                        text=True,
                        cwd=repo,
                        check=False,
                    )
                    if result.returncode == 0:
                        provenance["git_commit"] = result.stdout.strip()
                    result = subprocess.run(
                        ["git", "status", "--porcelain"],
                        capture_output=True,
                        text=True,
                        cwd=repo,
                        check=False,
                    )
                    if result.returncode == 0:
                        provenance["git_dirty"] = bool(result.stdout.strip())
                except FileNotFoundError:
                    logger.debug("git not found; skipping git provenance")

        return provenance

    # ------------------------------------------------------------------
    # BEACH-specific helpers (used by CLI / jobgen integration)
    # ------------------------------------------------------------------

    def get_setup_commands(self, run_dir: Path) -> list[str]:
        """Return setup commands for the BEACH job script."""
        beach_toml = run_dir / INPUT_DIR / "beach.toml"
        return [
            "date",
            f"beach-estimate-workload {beach_toml}"
            " --mpi-ranks $SLURM_NTASKS 2>/dev/null || true",
        ]

    def get_post_commands(self, run_dir: Path) -> list[str]:
        """Return post-execution commands for the BEACH job script."""
        output_dir = run_dir / WORK_DIR / "latest"
        return [
            "date",
            f"beach-inspect {output_dir}"
            f" --save-bar {output_dir}/charges_bar.png"
            f" --save-mesh {output_dir}/charges_mesh.png"
            " 2>/dev/null || true",
        ]

    def get_modules(self) -> list[str]:
        """Return default modules for BEACH."""
        return ["intel/2023.2", "intelmpi/2023.2"]

    def get_extra_env(self) -> dict[str, str]:
        """Return default environment variables for BEACH."""
        return {
            "OMP_NUM_THREADS": "${SLURM_DPC_CPUS:-1}",
            "OMP_PROC_BIND": "spread",
            "OMP_PLACES": "cores",
        }
