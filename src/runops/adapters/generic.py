"""Generic simulator adapter providing reasonable defaults.

This adapter handles simulators that follow common conventions:
a single executable, a single input file, and standard output
locations within the ``work/`` directory.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

from runops.adapters.base import SimulatorAdapter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

INPUT_DIR = "input"
WORK_DIR = "work"
ANALYSIS_DIR = "analysis"
STATUS_DIR = "status"
SUBMIT_DIR = "submit"

EXIT_CODE_FILE = "exit_code"
STDOUT_FILE = "stdout.log"
STDERR_FILE = "stderr.log"

SUMMARY_FILE = "summary.json"

_RESOLVER_MODES = frozenset({"package", "local_source", "local_executable"})


class GenericAdapter(SimulatorAdapter):
    """Generic adapter that works for many simple simulators.

    Conventions:
    - Input files live in ``<run_dir>/input/``.
    - Execution happens in ``<run_dir>/work/``.
    - Success is determined by a zero exit code written to
      ``<run_dir>/work/exit_code``.

    Class Attributes:
        adapter_name: Registry key for this adapter.
    """

    adapter_name: str = "generic"

    # ------------------------------------------------------------------
    # SimulatorAdapter interface
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        """Return the canonical name of this adapter."""
        return self.adapter_name

    def render_inputs(
        self,
        case_data: dict[str, Any],
        run_dir: Path,
    ) -> list[str]:
        """Copy input files listed in *case_data* into the run directory.

        If ``case_data["params"]`` exists, it is serialised as a JSON file
        named ``params.json`` inside ``<run_dir>/input/``.

        If ``case_data["case"]["input_files"]`` is a list of source paths,
        each file is copied into ``<run_dir>/input/``.

        Args:
            case_data: Merged case/survey parameters.
            run_dir: Target run directory.

        Returns:
            List of relative paths (from *run_dir*) to generated input files.

        Raises:
            ValueError: If required case metadata is missing.
        """
        case_section = case_data.get("case", {})
        if not case_section:
            msg = "case_data must contain a 'case' section"
            raise ValueError(msg)

        input_dir = run_dir / INPUT_DIR
        input_dir.mkdir(parents=True, exist_ok=True)

        created: list[str] = []

        # Serialise parameters
        params = case_data.get("params")
        if params is not None:
            params_file = input_dir / "params.json"
            params_file.write_text(json.dumps(params, indent=2))
            created.append(params_file.relative_to(run_dir).as_posix())

        # Copy explicit input files
        source_files: list[str] = case_section.get("input_files", [])
        for src_str in source_files:
            src = Path(src_str)
            if not src.is_file():
                logger.warning("Input file not found, skipping: %s", src)
                continue
            dest = input_dir / src.name
            shutil.copy2(src, dest)
            created.append(dest.relative_to(run_dir).as_posix())

        return created

    def resolve_runtime(
        self,
        simulator_config: dict[str, Any],
        resolver_mode: str,
    ) -> dict[str, Any]:
        """Resolve the simulator runtime from *simulator_config*.

        Supports three resolver modes defined in SPEC section 16:

        * ``package`` -- looks up ``executable`` in ``$PATH``.
        * ``local_source`` -- uses ``source_repo`` and optionally runs
          ``build_command`` to produce ``executable``.
        * ``local_executable`` -- uses a fully-qualified ``executable``
          path directly.

        Args:
            simulator_config: Simulator section from ``simulators.toml``.
            resolver_mode: One of ``"package"``, ``"local_source"``,
                ``"local_executable"``.

        Returns:
            Runtime information dictionary with at least ``executable``
            and ``resolver_mode`` keys.

        Raises:
            ValueError: If *resolver_mode* is unsupported or required keys
                are missing.
        """
        if resolver_mode not in _RESOLVER_MODES:
            msg = (
                f"Unsupported resolver_mode '{resolver_mode}'. "
                f"Expected one of {sorted(_RESOLVER_MODES)}"
            )
            raise ValueError(msg)

        runtime: dict[str, Any] = {"resolver_mode": resolver_mode}

        if resolver_mode == "package":
            exe_name = simulator_config.get("executable", "")
            if not exe_name:
                msg = "simulator_config must specify 'executable' for package mode"
                raise ValueError(msg)
            resolved = shutil.which(exe_name)
            runtime["executable"] = resolved if resolved else exe_name
            runtime["source"] = "package"

        elif resolver_mode == "local_source":
            source_repo = simulator_config.get("source_repo", "")
            executable = simulator_config.get("executable", "")
            if not source_repo or not executable:
                msg = (
                    "simulator_config must specify 'source_repo' and "
                    "'executable' for local_source mode"
                )
                raise ValueError(msg)
            runtime["source_repo"] = source_repo
            runtime["executable"] = executable
            runtime["build_command"] = simulator_config.get("build_command", "")

        elif resolver_mode == "local_executable":
            executable = simulator_config.get("executable", "")
            if not executable:
                msg = (
                    "simulator_config must specify 'executable' "
                    "for local_executable mode"
                )
                raise ValueError(msg)
            runtime["executable"] = executable

        return runtime

    def build_program_command(
        self,
        runtime_info: dict[str, Any],
        run_dir: Path,
    ) -> list[str]:
        """Build ``[executable, ...]`` for the simulator.

        The generic adapter simply returns the executable path.  If an
        ``input/params.json`` file exists it is passed as the first
        positional argument.

        Args:
            runtime_info: Output from :meth:`resolve_runtime`.
            run_dir: The run directory.

        Returns:
            Command as a list of strings (no MPI launcher prefix).
        """
        executable: str = runtime_info.get("executable", "")
        if not executable:
            msg = "runtime_info must contain 'executable'"
            raise ValueError(msg)

        cmd = [executable]
        params_file = run_dir / INPUT_DIR / "params.json"
        if params_file.exists():
            cmd.append(str(params_file))
        return cmd

    def detect_outputs(self, run_dir: Path) -> dict[str, Any]:
        """Scan ``<run_dir>/work/`` for output files.

        Args:
            run_dir: The run directory.

        Returns:
            Mapping of descriptive label to relative path strings.
        """
        work_dir = run_dir / WORK_DIR
        if not work_dir.is_dir():
            logger.warning("work/ directory not found in %s", run_dir)
            return {}

        outputs: dict[str, Any] = {}
        stdout = work_dir / STDOUT_FILE
        stderr = work_dir / STDERR_FILE

        if stdout.exists():
            outputs["stdout"] = stdout.relative_to(run_dir).as_posix()
        if stderr.exists():
            outputs["stderr"] = stderr.relative_to(run_dir).as_posix()

        # Collect remaining files (excluding status markers)
        for path in sorted(work_dir.iterdir()):
            if path.name in {STDOUT_FILE, STDERR_FILE, EXIT_CODE_FILE}:
                continue
            if path.is_file():
                outputs[path.stem] = path.relative_to(run_dir).as_posix()
            elif path.is_dir():
                outputs[path.name] = path.relative_to(run_dir).as_posix()

        return outputs

    def detect_status(self, run_dir: Path) -> str:
        """Determine simulation status from ``work/exit_code`` and logs.

        The detection logic is:

        1. If ``work/exit_code`` exists and contains ``0``, return
           ``"completed"``.
        2. If ``work/exit_code`` exists with a non-zero value, return
           ``"failed"``.
        3. If ``work/`` contains output files but no exit code, return
           ``"running"``.
        4. Otherwise return ``"unknown"``.

        Args:
            run_dir: The run directory.

        Returns:
            A status string.
        """
        work_dir = run_dir / WORK_DIR
        exit_code_path = work_dir / EXIT_CODE_FILE

        if exit_code_path.exists():
            try:
                code = int(exit_code_path.read_text(encoding="utf-8").strip())
            except (ValueError, OSError):
                return "unknown"
            return "completed" if code == 0 else "failed"

        # No exit code yet -- check whether work/ has any content
        if work_dir.is_dir() and any(work_dir.iterdir()):
            return "running"

        return "unknown"

    def summarize(self, run_dir: Path) -> dict[str, Any]:
        """Produce a basic summary of the run.

        For the generic adapter this includes:
        - detected outputs (file listing)
        - detected status
        - exit code (if available)

        Args:
            run_dir: The run directory.

        Returns:
            Summary dictionary.
        """
        summary: dict[str, Any] = {}
        errors: list[str] = []

        try:
            summary["status"] = self.detect_status(run_dir)
        except Exception as exc:
            errors.append(f"detect_status: {exc}")
            summary["status"] = "unknown"

        try:
            summary["outputs"] = self.detect_outputs(run_dir)
        except Exception as exc:
            errors.append(f"detect_outputs: {exc}")
            summary["outputs"] = {}

        exit_code_path = run_dir / WORK_DIR / EXIT_CODE_FILE
        if exit_code_path.exists():
            try:
                summary["exit_code"] = int(
                    exit_code_path.read_text(encoding="utf-8").strip()
                )
            except (ValueError, OSError) as exc:
                errors.append(f"exit_code: {exc}")

        if errors:
            summary["errors"] = errors

        return summary

    def collect_provenance(
        self,
        runtime_info: dict[str, Any],
    ) -> dict[str, Any]:
        """Collect provenance information from *runtime_info*.

        Gathers:
        - resolver mode
        - executable path and SHA-256 hash (if the file exists)
        - source repository git commit (if ``local_source`` mode)

        Args:
            runtime_info: Output from :meth:`resolve_runtime`.

        Returns:
            Provenance dictionary.
        """
        provenance: dict[str, Any] = {
            "resolver_mode": runtime_info.get("resolver_mode", ""),
            "executable": runtime_info.get("executable", ""),
            "exe_hash": "",
            "git_commit": "",
            "git_dirty": False,
            "source_repo": runtime_info.get("source_repo", ""),
            "build_command": runtime_info.get("build_command", ""),
            "package_version": runtime_info.get("package_version", ""),
        }

        # Executable hash
        exe_path = Path(runtime_info.get("executable", ""))
        if exe_path.is_file():
            provenance["exe_hash"] = _compute_file_hash(exe_path)

        # Git provenance for local_source
        if runtime_info.get("resolver_mode") == "local_source":
            repo = runtime_info.get("source_repo", "")
            if repo:
                git_info = _collect_git_info(Path(repo))
                provenance["git_commit"] = git_info.get("commit", "")
                provenance["git_dirty"] = git_info.get("dirty", False)

        return provenance


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _compute_file_hash(path: Path) -> str:
    """Return ``sha256:<hex>`` hash of a file.

    Args:
        path: Path to the file.

    Returns:
        Hash string prefixed with ``sha256:``.
    """
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"


def _collect_git_info(repo_path: Path) -> dict[str, Any]:
    """Collect basic git info from a repository path.

    Args:
        repo_path: Path to the git repository root.

    Returns:
        Dictionary with ``commit``, ``dirty``, and ``branch`` keys.
        Returns empty values on failure rather than raising.
    """
    info: dict[str, Any] = {"commit": "", "dirty": False, "branch": ""}
    if not repo_path.is_dir():
        return info
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=repo_path,
            check=False,
        )
        if result.returncode == 0:
            info["commit"] = result.stdout.strip()

        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=repo_path,
            check=False,
        )
        if result.returncode == 0:
            info["dirty"] = bool(result.stdout.strip())

        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            cwd=repo_path,
            check=False,
        )
        if result.returncode == 0:
            info["branch"] = result.stdout.strip()
    except FileNotFoundError:
        logger.debug("git not found on PATH; skipping git provenance")

    return info
