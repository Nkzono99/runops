"""Site profile: HPC environment abstraction.

A SiteProfile encapsulates all HPC-site-specific configuration that
affects job script generation — resource styles, module systems,
SBATCH customisations, environment variables, etc.

This cleanly separates environment concerns from:
- **Launcher** (pure MPI launch command: srun/mpirun/mpiexec)
- **SimulatorAdapter** (simulator-specific input/output handling)

Configuration sources (in priority order):
1. ``site.toml`` at the project root (primary)
2. Legacy: site keys embedded in ``launchers.toml`` (backward compat)
3. Fallback: ``STANDARD_SITE`` (no site customisation)

For testing, use ``MOCK_SITE`` which provides deterministic defaults
without any HPC-environment dependency.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

logger = logging.getLogger(__name__)

_SITE_FILE = "site.toml"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SiteProfile:
    """HPC site configuration that affects job script generation.

    Attributes:
        name: Site identifier (e.g. ``"camphor3"``).
        resource_style: Resource specification style
            (``"standard"`` or ``"rsc"``).
        modules: Site-wide module names to ``module load``.
        simulator_modules: Per-simulator additional modules.
        stdout_format: Custom ``#SBATCH -o`` format (e.g.
            ``"stdout.%J.log"``).  ``None`` means use default path.
        stderr_format: Custom ``#SBATCH -e`` format.
        extra_sbatch: Additional raw ``#SBATCH`` directive lines.
        env: Environment variables to ``export`` in job scripts.
        setup_commands: Shell commands to run before the main execution.
    """

    name: str = ""
    resource_style: str = "standard"
    modules: list[str] = field(default_factory=list)
    simulator_modules: dict[str, list[str]] = field(default_factory=dict)
    stdout_format: str | None = None
    stderr_format: str | None = None
    extra_sbatch: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    setup_commands: list[str] = field(default_factory=list)

    def modules_for(self, simulator_name: str) -> list[str]:
        """Return combined modules for a specific simulator.

        Merges site-wide modules with simulator-specific additions,
        avoiding duplicates while preserving order.

        Args:
            simulator_name: Simulator name to look up.

        Returns:
            Combined module list.
        """
        combined = list(self.modules)
        for m in self.simulator_modules.get(simulator_name, []):
            if m not in combined:
                combined.append(m)
        return combined


# ---------------------------------------------------------------------------
# Well-known profiles
# ---------------------------------------------------------------------------

#: Standard site with no customisation.  Used when no site.toml exists.
STANDARD_SITE = SiteProfile(name="standard")

#: Mock site for testing.  Provides deterministic values that don't
#: depend on any real HPC environment.
MOCK_SITE = SiteProfile(
    name="mock",
    resource_style="standard",
    modules=["mock/compiler", "mock/mpi"],
    simulator_modules={
        "test_sim": ["mock/hdf5"],
    },
    stdout_format=None,
    stderr_format=None,
    extra_sbatch=[],
    env={},
    setup_commands=[],
)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_site_profile(project_root: Path) -> SiteProfile:
    """Load the site profile for a project.

    Resolution order:
    1. ``site.toml`` at the project root.
    2. Legacy: site-related keys in ``launchers.toml`` (first profile that
       has ``resource_style`` or ``modules``).
    3. Fallback: :data:`STANDARD_SITE`.

    Args:
        project_root: Root directory of the runops project.

    Returns:
        Loaded :class:`SiteProfile`.
    """
    # 1. Try site.toml
    site_file = project_root / _SITE_FILE
    if site_file.is_file():
        return _load_site_toml(site_file)

    # 2. Legacy: extract from launchers.toml
    launchers_file = project_root / "launchers.toml"
    if launchers_file.is_file():
        profile = _load_from_launchers_toml(launchers_file)
        if profile is not None:
            return profile

    # 3. Fallback
    return STANDARD_SITE


def _load_site_toml(path: Path) -> SiteProfile:
    """Parse a ``site.toml`` file into a :class:`SiteProfile`.

    Expected format::

        [site]
        name = "camphor3"
        resource_style = "rsc"
        modules = ["intel/2023.2", "intelmpi/2023.2"]
        stdout = "stdout.%J.log"
        stderr = "stderr.%J.log"

        [site.env]
        OMP_PROC_BIND = "spread"

        [site.simulators.emses]
        modules = ["hdf5/1.12.2_intel-2023.2-impi"]

    Args:
        path: Path to site.toml.

    Returns:
        Parsed SiteProfile.
    """
    with open(path, "rb") as f:
        raw = tomllib.load(f)

    site = raw.get("site", {})
    if not isinstance(site, dict):
        logger.warning("Invalid [site] section in %s, using defaults", path)
        return STANDARD_SITE

    # Parse per-simulator modules
    sim_modules: dict[str, list[str]] = {}
    for sim_name, sim_data in site.get("simulators", {}).items():
        if isinstance(sim_data, dict):
            mods = sim_data.get("modules", [])
            if isinstance(mods, list):
                sim_modules[sim_name] = [str(m) for m in mods]

    # Parse env vars
    env_raw = site.get("env", {})
    env = (
        {str(k): str(v) for k, v in env_raw.items()}
        if isinstance(env_raw, dict)
        else {}
    )

    # Parse setup_commands
    setup_raw = site.get("setup_commands", [])
    setup_commands = [str(c) for c in setup_raw] if isinstance(setup_raw, list) else []

    # Parse extra_sbatch
    extra_raw = site.get("extra_sbatch", [])
    extra_sbatch = [str(d) for d in extra_raw] if isinstance(extra_raw, list) else []

    return SiteProfile(
        name=str(site.get("name", path.stem)),
        resource_style=str(site.get("resource_style", "standard")),
        modules=[str(m) for m in site.get("modules", [])],
        simulator_modules=sim_modules,
        stdout_format=site.get("stdout") or None,
        stderr_format=site.get("stderr") or None,
        extra_sbatch=extra_sbatch,
        env=env,
        setup_commands=setup_commands,
    )


def _load_from_launchers_toml(path: Path) -> SiteProfile | None:
    """Extract a SiteProfile from legacy launchers.toml.

    Looks for site-related keys (``resource_style``, ``modules``,
    ``stdout``, ``stderr``, ``extra_sbatch``, ``env``) in launcher
    profiles.  Returns ``None`` if no site-specific keys are found.

    Args:
        path: Path to launchers.toml.

    Returns:
        Extracted SiteProfile, or None if no site keys present.
    """
    with open(path, "rb") as f:
        raw = tomllib.load(f)

    site_keys = {
        "resource_style",
        "modules",
        "stdout",
        "stderr",
        "extra_sbatch",
        "env",
        "setup_commands",
    }

    # Check each launcher profile for site-related keys
    launchers = raw.get("launchers", raw)
    for _name, profile in launchers.items():
        if not isinstance(profile, dict):
            continue
        if not site_keys.intersection(profile.keys()):
            continue

        # Found site keys — extract them
        env_raw = profile.get("env", {})
        env = (
            {str(k): str(v) for k, v in env_raw.items()}
            if isinstance(env_raw, dict)
            else {}
        )

        setup_raw = profile.get("setup_commands", [])
        setup_commands = (
            [str(c) for c in setup_raw] if isinstance(setup_raw, list) else []
        )

        extra_raw = profile.get("extra_sbatch", [])
        extra_sbatch = (
            [str(d) for d in extra_raw] if isinstance(extra_raw, list) else []
        )

        logger.debug(
            "Extracted site profile from launchers.toml profile '%s' "
            "(consider migrating to site.toml)",
            _name,
        )
        return SiteProfile(
            name=f"legacy:{_name}",
            resource_style=str(profile.get("resource_style", "standard")),
            modules=[str(m) for m in profile.get("modules", [])],
            stdout_format=profile.get("stdout") or None,
            stderr_format=profile.get("stderr") or None,
            extra_sbatch=extra_sbatch,
            env=env,
            setup_commands=setup_commands,
        )

    return None


def save_site_profile(project_root: Path, profile: SiteProfile) -> Path:
    """Write a SiteProfile to ``site.toml``.

    Args:
        project_root: Root directory of the runops project.
        profile: SiteProfile to save.

    Returns:
        Path to the written site.toml.
    """
    try:
        import tomli_w
    except ImportError as exc:
        raise RuntimeError("tomli_w is required to write site.toml") from exc

    data: dict[str, Any] = {
        "site": {
            "name": profile.name,
            "resource_style": profile.resource_style,
        },
    }

    site = data["site"]

    if profile.modules:
        site["modules"] = list(profile.modules)
    if profile.stdout_format:
        site["stdout"] = profile.stdout_format
    if profile.stderr_format:
        site["stderr"] = profile.stderr_format
    if profile.extra_sbatch:
        site["extra_sbatch"] = list(profile.extra_sbatch)
    if profile.env:
        site["env"] = dict(profile.env)
    if profile.setup_commands:
        site["setup_commands"] = list(profile.setup_commands)

    if profile.simulator_modules:
        sims: dict[str, Any] = {}
        for sim_name, mods in profile.simulator_modules.items():
            sims[sim_name] = {"modules": list(mods)}
        site["simulators"] = sims

    site_file = project_root / _SITE_FILE
    with open(site_file, "wb") as f:
        tomli_w.dump(data, f)

    return site_file
