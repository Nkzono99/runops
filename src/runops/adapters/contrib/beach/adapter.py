"""BEACH (BEM + Accumulated CHarge) simulator adapter.

Handles BEACH-specific TOML configuration (beach.toml), CSV output
detection, and OpenMP/MPI hybrid execution.
"""

from __future__ import annotations

import logging
import re
import shutil
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
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
from runops.adapters.contrib.beach import diagnostics as _diagnostics
from runops.adapters.contrib.beach import metadata as _metadata
from runops.adapters.contrib.beach.constants import (
    INPUT_DIR,
    LATEST_OUTPUT_DIR,
    WORK_DIR,
)
from runops.adapters.contrib.beach.validation import (
    resolve_config as resolve_beach_config,
)
from runops.adapters.contrib.beach.validation import (
    validate_params as validate_beach_params,
)
from runops.core.codex_plugin import CodexPluginRecommendation
from runops.core.exceptions import SimctlError
from runops.core.manifest import read_manifest
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


@dataclass(frozen=True)
class _AttemptContext:
    """Current BEACH job attempt recorded by the run manifest."""

    job_id: str = ""
    submitted_at: float | None = None


@dataclass(frozen=True)
class _BeachStatusSnapshot:
    """Attempt-scoped status inputs shared by status and summary rendering."""

    status: str
    summary_file: Path | None
    progress: tuple[int, int, Path] | None


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
        return _metadata.default_config()

    @classmethod
    def required_outputs(cls) -> dict[str, str]:
        """Return BEACH outputs required for analysis readiness."""
        return _metadata.required_outputs()

    @classmethod
    def interactive_config(cls) -> dict[str, Any]:
        """Interactively prompt for BEACH configuration."""
        return _metadata.interactive_config()

    @classmethod
    def case_template(cls) -> dict[str, str]:
        """Return template files for a new BEACH case."""
        return _metadata.case_template()

    @classmethod
    def pip_packages(cls) -> list[str]:
        """Return pip packages for BEACH (simulator + analysis tools)."""
        return _metadata.pip_packages()

    @classmethod
    def doc_repos(cls) -> list[tuple[str, str]]:
        """Return documentation repos for BEACH."""
        return _metadata.doc_repos()

    @classmethod
    def knowledge_sources(cls) -> dict[str, list[str]]:
        """Return knowledge-relevant file patterns for BEACH repos."""
        return _metadata.knowledge_sources()

    @classmethod
    def codex_plugins(cls) -> list[CodexPluginRecommendation]:
        """Return Codex plugins recommended for BEACH projects."""
        return _metadata.codex_plugins()

    @classmethod
    def parameter_schema(cls) -> dict[str, dict[str, Any]]:
        """Return BEACH parameter schema."""
        return _metadata.parameter_schema()

    @classmethod
    def default_plot_recipes(cls) -> dict[str, dict[str, Any]]:
        """Return default survey plot recipes for BEACH studies."""
        return _metadata.default_plot_recipes()

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
        return _diagnostics.detect_outputs(self, run_dir)

    def probe_readiness(self, run_dir: Path) -> dict[str, Any]:
        """Return a bounded BEACH readiness observation."""
        snapshot = self._status_snapshot(run_dir)
        outputs: dict[str, Any] = {}
        if snapshot.summary_file is not None:
            outputs["summary"] = relative_to_run(snapshot.summary_file, run_dir)
        return {
            "simulator_status": snapshot.status,
            "outputs": outputs,
            "warnings": [],
        }

    def detect_status(self, run_dir: Path) -> str:
        """Infer BEACH simulation status from output files.

        Detection logic:

        1. Scope logs and summaries to the current manifest attempt when possible.
        2. If the current stderr contains an error marker -> ``"failed"``.
        3. If a current ``summary.txt`` is newer than current progress ->
           ``"completed"``.
        4. If current progress or partial outputs exist -> ``"running"``.
        5. Otherwise -> ``"unknown"``.

        Args:
            run_dir: The run directory.

        Returns:
            A status string.
        """
        return _diagnostics.detect_status(self, run_dir)

    def _status_snapshot(self, run_dir: Path) -> _BeachStatusSnapshot:
        """Collect one internally consistent current-attempt status snapshot."""
        work_dir = run_dir / WORK_DIR
        attempt = self._attempt_context(run_dir)

        summary_file = self._newest_summary_file(work_dir)
        summary_mtime = self._mtime(summary_file) if summary_file is not None else None
        if (
            summary_mtime is not None
            and attempt.submitted_at is not None
            and summary_mtime < attempt.submitted_at
        ):
            summary_file = None
            summary_mtime = None

        progress = self._latest_stdout_batch_progress(
            work_dir,
            job_id=attempt.job_id,
        )
        if self._has_error_log(work_dir, job_id=attempt.job_id):
            return _BeachStatusSnapshot("failed", None, progress)

        if progress is not None:
            _last_batch, _batch_count, log_file = progress
            log_mtime = self._mtime(log_file)
            if summary_mtime is None or (
                log_mtime is not None and log_mtime >= summary_mtime
            ):
                return _BeachStatusSnapshot("running", None, progress)

        # Check for summary.txt (written on normal completion)
        if summary_file is not None:
            return _BeachStatusSnapshot("completed", summary_file, progress)

        if progress is not None:
            return _BeachStatusSnapshot("running", None, progress)

        # Partial outputs indicate running
        for output_dir in self._output_dirs(work_dir):
            if (output_dir / "charges.csv").is_file():
                return _BeachStatusSnapshot("running", None, None)

        if work_dir.is_dir() and any(work_dir.iterdir()):
            return _BeachStatusSnapshot("running", None, None)

        return _BeachStatusSnapshot("unknown", None, None)

    def summarize(self, run_dir: Path) -> dict[str, Any]:
        """Extract key metrics from BEACH outputs.

        Parses ``summary.txt`` for simulation statistics and reads
        configuration parameters from the input ``beach.toml``.

        Args:
            run_dir: The run directory.

        Returns:
            Summary dictionary.
        """
        return _diagnostics.summarize(self, run_dir)

    @staticmethod
    def _output_dirs(work_dir: Path) -> tuple[Path, ...]:
        """Return BEACH output directory candidates in lookup order."""
        return _diagnostics._output_dirs(work_dir)

    @staticmethod
    def _mtime(path: Path) -> float | None:
        """Return file mtime, or ``None`` when it cannot be read."""
        return _diagnostics._mtime(path)

    def _newest_summary_file(self, work_dir: Path) -> Path | None:
        """Return the newest readable ``summary.txt`` across output candidates."""
        return _diagnostics._newest_summary_file(self, work_dir)

    def _latest_stdout_batch_progress(
        self,
        work_dir: Path,
        *,
        job_id: str = "",
    ) -> tuple[int, int, Path] | None:
        """Return progress from the selected attempt stdout log, if present."""
        return _diagnostics._latest_stdout_batch_progress(self, work_dir, job_id=job_id)

    def _stdout_logs(self, work_dir: Path, *, job_id: str = "") -> list[Path]:
        """Return stdout candidates, scoped to ``job_id`` when available."""
        return _diagnostics._stdout_logs(self, work_dir, job_id=job_id)

    def _has_error_log(self, work_dir: Path, *, job_id: str) -> bool:
        """Return whether the selected attempt stderr contains an error marker."""
        return _diagnostics._has_error_log(self, work_dir, job_id=job_id)

    def _existing_logs(self, work_dir: Path, names: tuple[str, ...]) -> list[Path]:
        """Return exact-name log candidates newest first."""
        return _diagnostics._existing_logs(self, work_dir, names)

    def _newest_logs(self, work_dir: Path, patterns: tuple[str, ...]) -> list[Path]:
        """Return at most the newest matching legacy log candidate."""
        return _diagnostics._newest_logs(self, work_dir, patterns)

    def _sort_logs(self, paths: Iterable[Path]) -> list[Path]:
        """Deduplicate and sort readable log paths by mtime then name."""
        return _diagnostics._sort_logs(self, paths)

    @staticmethod
    def _attempt_context(run_dir: Path) -> _AttemptContext:
        """Read current job attempt metadata without requiring a manifest."""
        try:
            job = read_manifest(run_dir).job
        except SimctlError:
            return _AttemptContext()
        job_id = str(job.get("job_id", "")).strip()
        submitted_at = BeachAdapter._parse_submitted_at(job.get("submitted_at"))
        return _AttemptContext(job_id=job_id, submitted_at=submitted_at)

    @staticmethod
    def _parse_submitted_at(value: Any) -> float | None:
        """Convert an ISO submission timestamp into epoch seconds."""
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            submitted_at = datetime.fromisoformat(value.strip())
        except ValueError:
            return None
        if submitted_at.tzinfo is None or submitted_at.utcoffset() is None:
            return None
        return submitted_at.timestamp()

    @staticmethod
    def _read_text_tail(path: Path) -> str:
        """Read the tail of a potentially large text log."""
        return _diagnostics._read_text_tail(path)

    @staticmethod
    def _parse_batch_progress(text: str) -> tuple[int, int] | None:
        """Parse the last ``batch N/M`` progress marker from text."""
        return _diagnostics._parse_batch_progress(text)

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
