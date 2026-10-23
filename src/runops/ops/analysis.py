"""Discover conventional analysis directories and disposable job logs (SPEC §9.1)."""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from runops.manifest import ACTIVE_STATES, MANIFEST_FILE, Manifest, RunState
from runops.project import ARCHIVE_DIR, Project

GROUP_ANALYSIS = "_analysis"
_JOB_LOG = re.compile(r"^(.+)\.([0-9]+(?:_[0-9]+)?)\.(out|err)$")


def plain_path(path: Path, root: Path) -> bool:
    """Within *root*, with no symlink components (including broken links)."""
    try:
        relative = path.absolute().relative_to(root.absolute())
    except ValueError:
        return False
    current = root
    for part in relative.parts:
        if part == "..":
            return False
        current /= part
        if current.is_symlink():
            return False
    return True


def group_analysis_dirs(project: Project, under: Path | None = None) -> Iterator[Path]:
    """Walk current groups, stopping at runs and analysis; never visit work/ outputs."""
    base = under or project.runs_dir
    if not plain_path(base, project.root) or ARCHIVE_DIR in base.relative_to(project.root).parts:
        return
    for directory, dirs, files in os.walk(base):
        parent = Path(directory)
        if MANIFEST_FILE in files:
            dirs[:] = []
            continue
        analysis = parent / GROUP_ANALYSIS
        if GROUP_ANALYSIS in dirs and not analysis.is_symlink():
            yield analysis
        dirs[:] = sorted(
            d
            for d in dirs
            if d not in (GROUP_ANALYSIS, ARCHIVE_DIR)
            and not d.startswith(".")
            and not (parent / d).is_symlink()
        )


def group_topics(project: Project) -> dict[str, list[str]]:
    result = {}
    for directory in group_analysis_dirs(project):
        topics = sorted(
            p.name
            for p in directory.iterdir()
            if not p.name.startswith(".")
            and plain_path(p / "README.md", project.root)
            and (p / "README.md").is_file()
        )
        if topics:
            result[project.rel(directory.parent)] = topics
    return result


def log_directories(project: Project, runs: list[Manifest]) -> Iterator[Path]:
    roots = [project.root / "analysis", *group_analysis_dirs(project)]
    roots += [
        m.run_dir / "analysis"
        for m in runs
        if not m.pinned
        and m.status not in (*ACTIVE_STATES, RunState.ARCHIVED)
        and ARCHIVE_DIR not in m.run_dir.relative_to(project.runs_dir).parts
    ]
    for root in roots:
        if not plain_path(root, project.root):
            continue
        for directory, dirs, _ in os.walk(root):
            parent = Path(directory)
            dirs[:] = sorted(
                d for d in dirs if not d.startswith(".") and not (parent / d).is_symlink()
            )
            if parent.name == "logs":
                yield parent
                dirs[:] = []


def old_log_pairs(directory: Path, cutoff: datetime) -> dict[str, list[Path]]:
    """Old job-name/id pairs, retaining the most recently modified pair per job name."""
    jobs: dict[str, dict[str, list[tuple[Path, float]]]] = {}
    for path in sorted(directory.iterdir()):
        match = _JOB_LOG.fullmatch(path.name)
        if match and not path.is_symlink() and path.is_file():
            name, job_id, _ = match.groups()
            jobs.setdefault(name, {}).setdefault(job_id, []).append((path, path.stat().st_mtime))
    result = {}
    for name, pairs in jobs.items():
        newest = max(
            pairs,
            key=lambda job: (
                max(mtime for _, mtime in pairs[job]),
                tuple(int(n) for n in job.split("_")),
            ),
        )
        for job_id, files in pairs.items():
            if job_id != newest and max(mtime for _, mtime in files) < cutoff.timestamp():
                result[f"{name}.{job_id}"] = [path for path, _ in files]
    return result
