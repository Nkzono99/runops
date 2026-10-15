"""Helpers shared by ops modules."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runops.adapters.registry import ResolvedAdapter, resolve_adapter
from runops.config import SimulatorConfig
from runops.manifest import Manifest
from runops.project import Project


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
