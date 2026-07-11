"""EMSES output, status, and summary diagnostics."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from runops.adapters.contrib._paths import relative_to_run
from runops.adapters.contrib.emses.constants import WORK_DIR


class _EmsesDiagnostics(Protocol):
    def _get_expected_nstep(self, run_dir: Path) -> int | None: ...

    def _load_input_config(self, run_dir: Path) -> dict[str, Any]: ...

    def detect_outputs(self, run_dir: Path) -> dict[str, Any]: ...

    def detect_status(self, run_dir: Path) -> str: ...


def detect_outputs(self: _EmsesDiagnostics, run_dir: Path) -> dict[str, Any]:
    """Detect EMSES output files in ``work/``.

    Scans for HDF5 field data, ASCII diagnostics, and snapshot files.

    Args:
        run_dir: The run directory.

    Returns:
        Dictionary of output categories to file lists.
    """
    work_dir = run_dir / WORK_DIR
    if not work_dir.is_dir():
        return {}

    outputs: dict[str, Any] = {}

    log_patterns = {"*.out", "*.err", "*.log"}
    for output_dir in (work_dir / "latest", work_dir):
        if not output_dir.is_dir():
            continue

        h5_files = sorted(output_dir.glob("*.h5"))
        if h5_files:
            outputs["hdf5_fields"] = [relative_to_run(f, run_dir) for f in h5_files]

        diag_files: list[str] = []
        for f in sorted(output_dir.iterdir()):
            if not f.is_file() or f.suffix == ".h5":
                continue
            if any(f.match(p) for p in log_patterns):
                continue
            diag_files.append(relative_to_run(f, run_dir))
        if diag_files:
            outputs["diagnostics"] = diag_files

        snapshot_dir = output_dir / "SNAPSHOT1"
        if snapshot_dir.is_dir():
            snap_files = sorted(snapshot_dir.glob("esdat*.h5"))
            if snap_files:
                outputs["snapshots"] = [relative_to_run(f, run_dir) for f in snap_files]

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


def detect_status(self: _EmsesDiagnostics, run_dir: Path) -> str:
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
    work_dir = run_dir / WORK_DIR
    if not work_dir.is_dir():
        return "unknown"

    # Check for errors in log files
    for pattern in ("stderr.*.log", "*.err"):
        for log in work_dir.glob(pattern):
            try:
                content = log.read_text(errors="replace")
                if any(
                    kw in content.lower()
                    for kw in ("error", "segmentation fault", "killed", "oom")
                ):
                    return "failed"
            except OSError:
                pass

    # Check energy file for simulation progress
    for output_dir in (work_dir / "latest", work_dir):
        energy_file = output_dir / "energy"
        if not energy_file.is_file():
            continue
        try:
            nstep = self._get_expected_nstep(run_dir)
            lines = [
                line
                for line in energy_file.read_text(encoding="utf-8").strip().split("\n")
                if line.strip()
            ]
            if lines and nstep:
                last_parts = lines[-1].strip().split()
                if last_parts:
                    last_step = int(float(last_parts[0]))
                    if last_step >= nstep:
                        return "completed"
                    return "running"
        except (ValueError, IndexError, OSError):
            pass

    # Fallback: check for any output files
    for output_dir in (work_dir / "latest", work_dir):
        if list(output_dir.glob("*.h5")):
            return "running"

    return "unknown"


def summarize(self: _EmsesDiagnostics, run_dir: Path) -> dict[str, Any]:
    """Extract key metrics from EMSES outputs.

    Args:
        run_dir: The run directory.

    Returns:
        Summary dictionary with status, output counts, energy data,
        and simulation parameters.
    """
    summary: dict[str, Any] = {}
    work_dir = run_dir / WORK_DIR

    summary["status"] = self.detect_status(run_dir)

    # Count outputs by category
    outputs = self.detect_outputs(run_dir)
    summary["output_counts"] = {
        k: len(v) if isinstance(v, list) else 1 for k, v in outputs.items()
    }

    # Energy diagnostics
    for output_dir in (work_dir / "latest", work_dir):
        energy_file = output_dir / "energy"
        if not energy_file.is_file():
            continue
        try:
            lines = [
                line
                for line in energy_file.read_text(encoding="utf-8").strip().split("\n")
                if line.strip()
            ]
            if lines:
                summary["total_energy_lines"] = len(lines)
                last_parts = lines[-1].strip().split()
                if last_parts:
                    summary["last_step"] = int(float(last_parts[0]))
        except (ValueError, OSError):
            pass
        break

    # Simulation parameters from plasma.toml
    config = self._load_input_config(run_dir)
    if config:
        tmgrid = config.get("tmgrid", {})
        for key in ("nx", "ny", "nz", "dt"):
            if key in tmgrid:
                summary[key] = tmgrid[key]
        jobcon = config.get("jobcon", {})
        if "nstep" in jobcon:
            summary["nstep"] = jobcon["nstep"]

    return summary
