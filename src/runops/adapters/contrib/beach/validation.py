"""BEACH parameter loading and validation helpers."""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from runops.adapters._utils.toml_utils import apply_dotted_overrides
from runops.core.validation import ValidationIssue


def resolve_config(case_data: dict[str, Any]) -> dict[str, Any]:
    """Load template config and apply param overrides."""
    case_section = case_data.get("case", {})
    params = case_data.get("params", {})
    config: dict[str, Any] = {}

    case_dir_str = case_section.get("case_dir", "")
    if case_dir_str:
        case_dir = Path(case_dir_str)
        for name in ("beach.toml", "beach_template.toml"):
            for candidate in (case_dir / "input" / name, case_dir / name):
                if candidate.is_file():
                    with open(candidate, "rb") as f:
                        config = tomllib.load(f)
                    break
            if config:
                break

    if params and config:
        config = apply_dotted_overrides(config, params)

    return config


def validate_params(case_data: dict[str, Any]) -> list[ValidationIssue]:
    """Validate BEACH parameters against physics constraints."""
    issues: list[ValidationIssue] = []
    config = resolve_config(case_data)
    if not config:
        return issues

    sim = config.get("sim", {})
    env = config.get("environment", {})

    dt = sim.get("dt")
    max_step = sim.get("max_step")
    e_density = env.get("electron_density")
    e_temp = env.get("electron_temperature")
    i_density = env.get("ion_density")
    i_temp = env.get("ion_temperature")

    positives = [
        ("sim.dt", dt),
        ("sim.max_step", max_step),
        ("environment.electron_density", e_density),
        ("environment.electron_temperature", e_temp),
        ("environment.ion_density", i_density),
        ("environment.ion_temperature", i_temp),
    ]
    for param_name, value in positives:
        if value is not None and float(value) <= 0:
            issues.append(
                ValidationIssue(
                    severity="error",
                    message=f"{param_name} must be positive, got {value}.",
                    parameter=param_name,
                    constraint_name="positive_required",
                )
            )

    if dt is not None and e_density is not None and float(e_density) > 0:
        e_charge = 1.602176634e-19
        m_electron = 9.10938370e-31
        eps0 = 8.854187817e-12
        omega_pe = math.sqrt(float(e_density) * e_charge**2 / (m_electron * eps0))
        dt_omega = float(dt) * omega_pe
        if dt_omega > 0.5:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    message=(
                        f"dt * omega_pe = {dt_omega:.3f} > 0.5. "
                        "Time step may be too large for plasma "
                        f"timescale. Consider dt < {0.5 / omega_pe:.2e} s."
                    ),
                    parameter="sim.dt",
                    constraint_name="timestep_stability",
                    details={
                        "dt": float(dt),
                        "omega_pe": omega_pe,
                        "dt_omega_pe": dt_omega,
                        "recommended_max_dt": 0.5 / omega_pe,
                    },
                )
            )

    if e_density is not None and i_density is not None and float(e_density) > 0:
        ratio = float(i_density) / float(e_density)
        if abs(ratio - 1.0) > 0.1:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    message=(
                        "Charge neutrality: ion/electron density "
                        f"ratio = {ratio:.3f}. Significant imbalance "
                        "may be intentional but verify."
                    ),
                    parameter="environment.ion_density",
                    constraint_name="charge_neutrality",
                    details={
                        "electron_density": float(e_density),
                        "ion_density": float(i_density),
                        "ratio": ratio,
                    },
                )
            )

    return issues
