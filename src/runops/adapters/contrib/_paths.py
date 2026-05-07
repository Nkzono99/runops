"""Shared path helpers for bundled simulator adapters."""

from __future__ import annotations

from pathlib import Path


def relative_to_run(path: Path, run_dir: Path) -> str:
    """Return a stable POSIX-style relative path under the run directory."""
    return path.relative_to(run_dir).as_posix()
