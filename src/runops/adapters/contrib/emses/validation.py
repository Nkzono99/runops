"""EMSES parameter loading and validation helpers."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from runops.adapters._utils.toml_utils import apply_dotted_overrides
from runops.core.validation import ValidationIssue

from .constants import DOMAIN_DECOMP_KEY, DOMAIN_DECOMP_SECTION


def compute_mpi_processes(config: dict[str, Any]) -> int | None:
    """Compute the required MPI process count from domain decomposition."""
    mpi_section = config.get(DOMAIN_DECOMP_SECTION, {})
    nodes = mpi_section.get(DOMAIN_DECOMP_KEY)
    if nodes is None:
        return None
    if isinstance(nodes, (list, tuple)):
        result = 1
        for n in nodes:
            result *= int(n)
        return result
    return int(nodes)


def resolve_config(case_data: dict[str, Any]) -> dict[str, Any]:
    """Load template config and apply param overrides."""
    case_section = case_data.get("case", {})
    params = case_data.get("params", {})
    config: dict[str, Any] = {}

    case_dir_str = case_section.get("case_dir", "")
    if case_dir_str:
        candidate = Path(case_dir_str) / "plasma.toml"
        if candidate.is_file():
            with open(candidate, "rb") as f:
                config = tomllib.load(f)

    if params and config:
        config = apply_dotted_overrides(config, params)

    return config


def validate_params(case_data: dict[str, Any]) -> list[ValidationIssue]:
    """Validate EMSES parameters against physics constraints."""
    issues: list[ValidationIssue] = []
    config = resolve_config(case_data)
    if not config:
        return issues

    tmgrid = config.get("tmgrid", {})
    plasma = config.get("plasma", {})
    esorem = config.get("esorem", {})
    mpi_sec = config.get(DOMAIN_DECOMP_SECTION, {})
    species_list = config.get("species", [])

    dt = tmgrid.get("dt")
    nx = tmgrid.get("nx")
    ny = tmgrid.get("ny")
    nz = tmgrid.get("nz")
    cv = plasma.get("cv", 1.0)

    emflag = esorem.get("emflag", 1)
    if dt is not None and cv is not None and emflag != 0:
        cfl_ratio = float(dt) * float(cv)
        if cfl_ratio >= 1.0:
            issues.append(
                ValidationIssue(
                    severity="error",
                    message=(
                        f"CFL condition violated: dt*cv = {cfl_ratio:.3f} >= 1.0. "
                        f"Reduce dt below {1.0 / float(cv):.3f}."
                    ),
                    parameter="tmgrid.dt",
                    constraint_name="cfl_condition",
                    details={
                        "dt": dt,
                        "cv": cv,
                        "cfl_ratio": cfl_ratio,
                        "max_dt": 1.0 / float(cv),
                    },
                )
            )
        elif cfl_ratio > 0.8:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    message=(
                        f"CFL ratio dt*cv = {cfl_ratio:.3f} is close to "
                        "stability limit (1.0). Consider reducing dt."
                    ),
                    parameter="tmgrid.dt",
                    constraint_name="cfl_condition",
                    details={"cfl_ratio": cfl_ratio},
                )
            )

    for i, sp in enumerate(species_list):
        wp = sp.get("wp")
        vdthz = sp.get("vdthz") or sp.get("vdth", {}).get("z")
        if wp and vdthz and float(wp) > 0:
            debye = float(vdthz) / float(wp)
            if debye < 0.5:
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        message=(
                            f"Species {i}: Debye length ({debye:.3f} dx) "
                            "is under-resolved by grid (dx=1). "
                            "Increase grid resolution or reduce density."
                        ),
                        parameter=f"species.{i}.wp",
                        constraint_name="debye_resolution",
                        details={
                            "species_index": i,
                            "debye_length": debye,
                            "wp": float(wp),
                            "vdthz": float(vdthz),
                        },
                    )
                )

    nodes = mpi_sec.get(DOMAIN_DECOMP_KEY)
    if nodes and isinstance(nodes, (list, tuple)):
        dims = [("nx", nx), ("ny", ny), ("nz", nz)]
        for idx, (dim_name, dim_val) in enumerate(dims):
            if dim_val is not None and idx < len(nodes):
                ndiv = int(nodes[idx])
                if int(dim_val) % ndiv != 0:
                    issues.append(
                        ValidationIssue(
                            severity="error",
                            message=(
                                f"Grid {dim_name}={dim_val} is not "
                                f"divisible by MPI decomposition "
                                f"nodes[{idx}]={ndiv}."
                            ),
                            parameter=f"tmgrid.{dim_name}",
                            constraint_name="grid_divisibility",
                            details={
                                "dimension": dim_name,
                                "grid_size": int(dim_val),
                                "mpi_division": ndiv,
                            },
                        )
                    )

    return issues
