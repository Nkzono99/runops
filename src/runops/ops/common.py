"""Helpers shared by ops modules."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runops.adapters.registry import ResolvedAdapter, resolve_adapter
from runops.config import SimulatorConfig
from runops.errors import UsageError
from runops.manifest import Manifest
from runops.project import ARCHIVE_DIR, Project


@dataclass
class SimContext:
    sim: SimulatorConfig
    resolved: ResolvedAdapter

    @property
    def adapter(self) -> Any:
        return self.resolved.adapter


def sim_context(project: Project, sim_name: str) -> SimContext:
    sim = project.config.simulator(sim_name)
    return SimContext(sim, resolve_adapter(sim.adapter, project.root, sim.raw))


def run_sim_context(project: Project, manifest: Manifest) -> SimContext:
    return sim_context(project, str(manifest.section("simulator").get("name", "")))


def inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def resolve_dest(project: Project, dest: str) -> Path:
    """A ``--dest`` directory: under ``runs/``, outside ``_archive`` and outside any run."""
    path = Path(dest)
    if not path.is_absolute():
        path = project.root / path if path.parts[0] == "runs" else project.runs_dir / path
    if not inside(path, project.runs_dir):
        raise UsageError(f"--dest must be inside {project.runs_dir}")
    if inside(path, project.runs_dir / ARCHIVE_DIR):
        raise UsageError("--dest must not be inside runs/_archive")
    enclosing = project.enclosing_run(path)
    if enclosing is not None:
        # Discovery stops at a run directory, so a run nested in it would be lost.
        raise UsageError(f"--dest must not be inside the run {project.rel(enclosing)}")
    return path
