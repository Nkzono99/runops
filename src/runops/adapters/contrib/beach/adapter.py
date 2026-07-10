"""BEACH (BEM + Accumulated CHarge) simulator adapter.

Handles BEACH-specific TOML configuration (beach.toml), CSV output
detection, and OpenMP/MPI hybrid execution.
"""

from __future__ import annotations

import logging
import re
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
from runops.adapters.contrib.beach.constants import (
    INPUT_DIR,
    LATEST_OUTPUT_DIR,
    OUTPUT_FILES,
    WORK_DIR,
)
from runops.adapters.contrib.beach.validation import (
    resolve_config as resolve_beach_config,
)
from runops.adapters.contrib.beach.validation import (
    validate_params as validate_beach_params,
)
from runops.core.codex_plugin import CodexPluginRecommendation
from runops.core.validation import ValidationIssue

logger = logging.getLogger(__name__)

_BATCH_PROGRESS_RE = re.compile(r"\bbatch\s+(\d+)\s*/\s*(\d+)\b", re.IGNORECASE)
_STDOUT_TAIL_BYTES = 256 * 1024
_RUNTIME_DEFAULTS = _ExecutableRuntimeDefaults(
    executable="beach",
    build_command="make build",
    discover_venv=True,
    require_executable=False,
)


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
    def codex_plugins(cls) -> list[CodexPluginRecommendation]:
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
        """Validate BEACH parameters against physics constraints."""
        return validate_beach_params(case_data)

    @staticmethod
    def _resolve_config(case_data: dict[str, Any]) -> dict[str, Any]:
        """Load template config and apply param overrides."""
        return resolve_beach_config(case_data)

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
            for label, filename in OUTPUT_FILES.items():
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

        1. If newer stdout reports incomplete ``batch N/M`` progress ->
           ``"running"``.
        2. If ``summary.txt`` exists -> ``"completed"``.
        3. If error logs contain error keywords -> ``"failed"``.
        4. If partial outputs or logs exist -> ``"running"``.
        5. Otherwise -> ``"unknown"``.

        Args:
            run_dir: The run directory.

        Returns:
            A status string.
        """
        work_dir = run_dir / WORK_DIR

        summary_mtime = self._newest_summary_mtime(work_dir)
        progress = self._latest_stdout_batch_progress(work_dir)
        if progress is not None:
            last_batch, batch_count, log_file = progress
            log_mtime = self._mtime(log_file)
            if last_batch < batch_count and (
                summary_mtime is None
                or (log_mtime is not None and log_mtime >= summary_mtime)
            ):
                return "running"

        # Check for summary.txt (written on normal completion)
        if summary_mtime is not None:
            return "completed"

        if progress is not None:
            last_batch, batch_count, _log_file = progress
            return "completed" if last_batch >= batch_count else "running"

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
        for output_dir in self._output_dirs(work_dir):
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

        progress = self._latest_stdout_batch_progress(work_dir)
        if progress is not None:
            last_batch, batch_count, _log_file = progress
            summary["last_step"] = last_batch
            summary["nstep"] = batch_count

        return summary

    @staticmethod
    def _output_dirs(work_dir: Path) -> tuple[Path, ...]:
        """Return BEACH output directory candidates in lookup order."""
        return (
            work_dir / "latest",
            work_dir / "outputs" / "latest",
            work_dir / "outputs",
            work_dir,
        )

    @staticmethod
    def _mtime(path: Path) -> float | None:
        """Return file mtime, or ``None`` when it cannot be read."""
        try:
            return path.stat().st_mtime
        except OSError:
            return None

    def _newest_summary_mtime(self, work_dir: Path) -> float | None:
        """Return the newest ``summary.txt`` mtime across output candidates."""
        newest: float | None = None
        for output_dir in self._output_dirs(work_dir):
            summary_file = output_dir / "summary.txt"
            if not summary_file.is_file():
                continue
            mtime = self._mtime(summary_file)
            if mtime is not None and (newest is None or mtime > newest):
                newest = mtime
        return newest

    def _latest_stdout_batch_progress(
        self, work_dir: Path
    ) -> tuple[int, int, Path] | None:
        """Return latest parsed stdout ``batch current/total`` progress."""
        for log_file in self._stdout_logs(work_dir):
            progress = self._parse_batch_progress(self._read_text_tail(log_file))
            if progress is not None:
                last_batch, batch_count = progress
                return last_batch, batch_count, log_file
        return None

    def _stdout_logs(self, work_dir: Path) -> list[Path]:
        """Return stdout log candidates newest first."""
        candidates: list[tuple[float, str, Path]] = []
        seen: set[Path] = set()
        for pattern in ("stdout.*.log", "*.out"):
            for log_file in work_dir.glob(pattern):
                if log_file in seen or not log_file.is_file():
                    continue
                mtime = self._mtime(log_file)
                if mtime is None:
                    continue
                candidates.append((mtime, log_file.name, log_file))
                seen.add(log_file)
        candidates.sort(reverse=True)
        return [path for _mtime, _name, path in candidates]

    @staticmethod
    def _read_text_tail(path: Path) -> str:
        """Read the tail of a potentially large text log."""
        try:
            with path.open("rb") as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - _STDOUT_TAIL_BYTES))
                return f.read().decode("utf-8", errors="replace")
        except OSError:
            return ""

    @staticmethod
    def _parse_batch_progress(text: str) -> tuple[int, int] | None:
        """Parse the last ``batch N/M`` progress marker from text."""
        latest: tuple[int, int] | None = None
        for match in _BATCH_PROGRESS_RE.finditer(text):
            latest = (int(match.group(1)), int(match.group(2)))
        return latest

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
        provenance_info = dict(runtime_info)
        provenance_info["package_version"] = ""
        return _collect_executable_provenance(provenance_info)

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
