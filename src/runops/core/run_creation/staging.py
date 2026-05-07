"""Staging helpers for transactional run creation."""

from __future__ import annotations

import shutil
from pathlib import Path

from runops.core.run import next_run_id


def copy_case_files(case_dir: Path, input_dir: Path) -> list[str]:
    src_dir = case_dir / "input"
    if not src_dir.is_dir():
        return []
    input_dir.mkdir(parents=True, exist_ok=True)
    created: list[str] = []
    for src in src_dir.rglob("*"):
        if not src.is_file():
            continue
        rel = src.relative_to(src_dir)
        dest = input_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        created.append(str(Path("input") / rel))
    return created


def next_available_run_target(
    parent_dir: Path,
    known_ids: set[str],
) -> tuple[str, Path]:
    """Return the next run_id whose final directory is currently free."""
    while True:
        run_id = next_run_id(known_ids)
        final_run_dir = (parent_dir / run_id).resolve()
        if not final_run_dir.exists():
            return run_id, final_run_dir
        known_ids.add(run_id)
