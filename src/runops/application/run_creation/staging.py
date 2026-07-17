"""Staging helpers for transactional run creation."""

from __future__ import annotations

import shutil
from pathlib import Path

from runops.core.run import next_run_id
from runops.core.survey import NamingConfig, render_run_directory_name


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
    *,
    display_name: str = "",
    naming: NamingConfig | None = None,
) -> tuple[str, Path]:
    """Return the next run_id whose final directory is currently free."""
    while True:
        run_id = next_run_id(known_ids)
        directory_name = render_run_directory_name(run_id, display_name, naming)
        final_run_dir = (parent_dir / directory_name).resolve()
        claim_dir = parent_dir / f".tmp-{run_id}"
        existing_candidates = list(parent_dir.glob(f"{run_id}*"))
        if not existing_candidates and not claim_dir.exists():
            return run_id, final_run_dir
        known_ids.add(run_id)
