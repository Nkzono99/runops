"""Shared constants for the BEACH adapter."""

from __future__ import annotations

INPUT_DIR = "input"
WORK_DIR = "work"
LATEST_OUTPUT_DIR = f"{WORK_DIR}/latest"

OUTPUT_FILES = {
    "summary": "summary.txt",
    "charges": "charges.csv",
    "mesh_triangles": "mesh_triangles.csv",
    "mesh_sources": "mesh_sources.csv",
    "charge_history": "charge_history.csv",
    "potential_history": "potential_history.csv",
    "mesh_potential": "mesh_potential.csv",
    "rng_state": "rng_state.txt",
    "performance_profile": "performance_profile.csv",
}
