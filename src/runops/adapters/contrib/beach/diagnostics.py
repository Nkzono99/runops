"""Attempt-aware BEACH output and status diagnostics."""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Protocol

from runops.adapters.contrib._paths import relative_to_run
from runops.adapters.contrib.beach.constants import INPUT_DIR, OUTPUT_FILES, WORK_DIR

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

_BATCH_PROGRESS_RE = re.compile(r"\bbatch\s+(\d+)\s*/\s*(\d+)\b", re.IGNORECASE)
_STDOUT_TAIL_BYTES = 256 * 1024


class _StatusSnapshot(Protocol):
    @property
    def status(self) -> str: ...

    @property
    def summary_file(self) -> Path | None: ...

    @property
    def progress(self) -> tuple[int, int, Path] | None: ...


class _BeachDiagnostics(Protocol):
    def _status_snapshot(self, run_dir: Path) -> _StatusSnapshot: ...

    def detect_outputs(self, run_dir: Path) -> dict[str, Any]: ...

    def _output_dirs(self, work_dir: Path) -> tuple[Path, ...]: ...

    def _mtime(self, path: Path) -> float | None: ...

    def _sort_logs(self, paths: Iterable[Path]) -> list[Path]: ...

    def _stdout_logs(self, work_dir: Path, *, job_id: str = "") -> list[Path]: ...

    def _existing_logs(self, work_dir: Path, names: tuple[str, ...]) -> list[Path]: ...

    def _newest_logs(self, work_dir: Path, patterns: tuple[str, ...]) -> list[Path]: ...

    def _read_text_tail(self, path: Path) -> str: ...

    def _parse_batch_progress(self, text: str) -> tuple[int, int] | None: ...


def detect_outputs(self: _BeachDiagnostics, run_dir: Path) -> dict[str, Any]:
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


def detect_status(self: _BeachDiagnostics, run_dir: Path) -> str:
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
    return self._status_snapshot(run_dir).status


def summarize(self: _BeachDiagnostics, run_dir: Path) -> dict[str, Any]:
    """Extract key metrics from BEACH outputs.

    Parses ``summary.txt`` for simulation statistics and reads
    configuration parameters from the input ``beach.toml``.

    Args:
        run_dir: The run directory.

    Returns:
        Summary dictionary.
    """
    summary: dict[str, Any] = {}
    snapshot = self._status_snapshot(run_dir)

    summary["status"] = snapshot.status

    # Parse summary.txt
    if snapshot.summary_file is not None:
        try:
            for line in snapshot.summary_file.read_text(encoding="utf-8").split("\n"):
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

    progress = snapshot.progress
    if progress is not None:
        last_batch, batch_count, _log_file = progress
        summary["last_step"] = last_batch
        summary["nstep"] = batch_count

    return summary


def _output_dirs(work_dir: Path) -> tuple[Path, ...]:
    """Return BEACH output directory candidates in lookup order."""
    return (
        work_dir / "latest",
        work_dir / "outputs" / "latest",
        work_dir / "outputs",
        work_dir,
    )


def _mtime(path: Path) -> float | None:
    """Return file mtime, or ``None`` when it cannot be read."""
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _newest_summary_file(self: _BeachDiagnostics, work_dir: Path) -> Path | None:
    """Return the newest readable ``summary.txt`` across output candidates."""
    candidates = self._sort_logs(
        output_dir / "summary.txt" for output_dir in self._output_dirs(work_dir)
    )
    return candidates[0] if candidates else None


def _latest_stdout_batch_progress(
    self: _BeachDiagnostics,
    work_dir: Path,
    *,
    job_id: str = "",
) -> tuple[int, int, Path] | None:
    """Return progress from the selected attempt stdout log, if present."""
    logs = self._stdout_logs(work_dir, job_id=job_id)
    if not logs:
        return None
    log_file = logs[0]
    progress = self._parse_batch_progress(self._read_text_tail(log_file))
    if progress is None:
        return None
    last_batch, batch_count = progress
    return last_batch, batch_count, log_file


def _stdout_logs(
    self: _BeachDiagnostics, work_dir: Path, *, job_id: str = ""
) -> list[Path]:
    """Return stdout candidates, scoped to ``job_id`` when available."""
    if job_id:
        return self._existing_logs(
            work_dir,
            (f"stdout.{job_id}.log", f"{job_id}.out"),
        )
    return self._newest_logs(work_dir, ("stdout.*.log", "*.out"))


def _has_error_log(self: _BeachDiagnostics, work_dir: Path, *, job_id: str) -> bool:
    """Return whether the selected attempt stderr contains an error marker."""
    if job_id:
        logs = self._existing_logs(
            work_dir,
            (f"stderr.{job_id}.log", f"{job_id}.err"),
        )
    else:
        logs = self._newest_logs(work_dir, ("stderr.*.log", "*.err"))
    return any(
        content.strip()
        and any(keyword in content for keyword in ("error", "fatal", "killed", "oom"))
        for content in (self._read_text_tail(log_file).lower() for log_file in logs)
    )


def _existing_logs(
    self: _BeachDiagnostics, work_dir: Path, names: tuple[str, ...]
) -> list[Path]:
    """Return exact-name log candidates newest first."""
    paths = [work_dir / name for name in names]
    return self._sort_logs(path for path in paths if path.is_file())


def _newest_logs(
    self: _BeachDiagnostics, work_dir: Path, patterns: tuple[str, ...]
) -> list[Path]:
    """Return at most the newest matching legacy log candidate."""
    paths: list[Path] = []
    for pattern in patterns:
        paths.extend(work_dir.glob(pattern))
    sorted_paths = self._sort_logs(paths)
    return sorted_paths[:1]


def _sort_logs(self: _BeachDiagnostics, paths: Iterable[Path]) -> list[Path]:
    """Deduplicate and sort readable log paths by mtime then name."""
    candidates: list[tuple[float, str, Path]] = []
    seen: set[Path] = set()
    for log_file in paths:
        if log_file in seen or not log_file.is_file():
            continue
        mtime = self._mtime(log_file)
        if mtime is None:
            continue
        candidates.append((mtime, log_file.name, log_file))
        seen.add(log_file)
    candidates.sort(reverse=True)
    return [path for _mtime, _name, path in candidates]


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


def _parse_batch_progress(text: str) -> tuple[int, int] | None:
    """Parse the last ``batch N/M`` progress marker from text."""
    latest: tuple[int, int] | None = None
    for match in _BATCH_PROGRESS_RE.finditer(text):
        latest = (int(match.group(1)), int(match.group(2)))
    return latest
