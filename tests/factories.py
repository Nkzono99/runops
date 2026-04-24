"""Shared filesystem factories for runops tests."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

import tomli_w


def _merge_nested(
    base: dict[str, Any],
    overlay: Mapping[str, Any],
) -> dict[str, Any]:
    """Recursively merge overlay values into a copied dictionary."""
    result = deepcopy(base)
    for key, value in overlay.items():
        existing = result.get(key)
        if isinstance(existing, dict) and isinstance(value, Mapping):
            result[key] = _merge_nested(existing, value)
        else:
            result[key] = deepcopy(value)
    return result


def write_toml(path: Path, data: Mapping[str, Any]) -> None:
    """Write TOML data, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        tomli_w.dump(dict(data), f)


def create_minimal_project(root: Path, *, name: str = "test-project") -> Path:
    """Create the minimal project layout used by CLI tests."""
    (root / "runops.toml").write_text(
        f'[project]\nname = "{name}"\n',
        encoding="utf-8",
    )
    (root / "cases").mkdir(exist_ok=True)
    (root / "runs").mkdir(exist_ok=True)
    return root


def make_manifest(
    run_id: str,
    *,
    status: str = "created",
    display_name: str | None = None,
    job_id: str = "",
    submitted_at: str = "",
    origin_case: str = "",
    simulator_name: str = "fake_sim",
    adapter: str = "fake_sim",
    last_slurm_state: str = "",
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a minimal manifest dictionary with optional section overrides."""
    run: dict[str, Any] = {
        "id": run_id,
        "display_name": display_name if display_name is not None else f"d_{run_id}",
        "status": status,
        "created_at": "2026-03-27T13:00:00+09:00",
    }
    if last_slurm_state:
        run["last_slurm_state"] = last_slurm_state

    manifest: dict[str, Any] = {
        "run": run,
        "origin": {
            "case": origin_case,
            "survey": "",
            "parent_run": "",
        },
        "job": {
            "scheduler": "slurm",
            "job_id": job_id,
            "partition": "debug",
            "submitted_at": submitted_at,
        },
        "simulator": {
            "name": simulator_name,
            "adapter": adapter,
        },
    }
    if extra:
        manifest = _merge_nested(manifest, extra)
    return manifest


def create_run_manifest(
    run_dir: Path,
    *,
    run_id: str | None = None,
    status: str = "created",
    display_name: str | None = None,
    job_id: str = "",
    submitted_at: str = "",
    origin_case: str = "",
    simulator_name: str = "fake_sim",
    adapter: str = "fake_sim",
    last_slurm_state: str = "",
    extra: Mapping[str, Any] | None = None,
) -> Path:
    """Create a run directory with a minimal ``manifest.toml``."""
    resolved_run_id = run_id or run_dir.name
    manifest = make_manifest(
        resolved_run_id,
        status=status,
        display_name=display_name,
        job_id=job_id,
        submitted_at=submitted_at,
        origin_case=origin_case,
        simulator_name=simulator_name,
        adapter=adapter,
        last_slurm_state=last_slurm_state,
        extra=extra,
    )
    write_toml(run_dir / "manifest.toml", manifest)
    return run_dir
