"""Execution environment description and auto-detection."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

try:
    import tomli_w
except ImportError:
    tomli_w = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_SIMCTL_DIR = ".runops"
_ENV_FILE = "environment.toml"


@dataclass
class PartitionInfo:
    """Slurm partition metadata.

    Attributes:
        name: Partition name.
        max_nodes: Maximum allocatable nodes.
        max_walltime: Maximum walltime string (e.g. ``"72:00:00"``).
        gpu: Whether GPU nodes are available.
        default: Whether this is the default partition.
    """

    name: str
    max_nodes: int = 0
    max_walltime: str = ""
    gpu: bool = False
    default: bool = False


@dataclass
class EnvironmentInfo:
    """Execution environment description.

    Attributes:
        cluster_name: HPC cluster name.
        scheduler: Job scheduler type (e.g. ``"slurm"``).
        partitions: Available partition metadata.
        modules: Named module sets.
        scratch_path: Scratch filesystem path template.
        constraints: Cluster-wide constraints.
        raw: Raw TOML dict (if loaded from file).
    """

    cluster_name: str = ""
    scheduler: str = "slurm"
    partitions: list[PartitionInfo] = field(default_factory=list)
    modules: dict[str, list[str]] = field(default_factory=dict)
    scratch_path: str = ""
    constraints: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


def _parse_environment_data(raw: dict[str, Any]) -> EnvironmentInfo:
    """Build :class:`EnvironmentInfo` from TOML-compatible raw data."""
    cluster = raw.get("cluster", {})
    if not isinstance(cluster, dict):
        cluster = {}

    partitions: list[PartitionInfo] = []
    partition_map = cluster.get("partitions", {})
    if isinstance(partition_map, dict):
        for name, pdata in partition_map.items():
            if not isinstance(pdata, dict):
                continue
            partitions.append(
                PartitionInfo(
                    name=name,
                    max_nodes=pdata.get("max_nodes", 0),
                    max_walltime=pdata.get("max_walltime", ""),
                    gpu=pdata.get("gpu", False),
                    default=pdata.get("default", False),
                )
            )

    modules: dict[str, list[str]] = {}
    module_sets = raw.get("modules", {})
    if isinstance(module_sets, dict):
        for name, mlist in module_sets.items():
            if isinstance(mlist, list):
                modules[name] = [str(item) for item in mlist]

    constraints = cluster.get("constraints", {})
    if not isinstance(constraints, dict):
        constraints = {}

    return EnvironmentInfo(
        cluster_name=cluster.get("name", ""),
        scheduler=cluster.get("scheduler", "slurm"),
        partitions=partitions,
        modules=modules,
        scratch_path=cluster.get("scratch_path", ""),
        constraints=constraints,
        raw=raw,
    )


def load_environment(project_root: Path) -> EnvironmentInfo | None:
    """Load .runops/environment.toml if it exists."""
    env_file = project_root / _SIMCTL_DIR / _ENV_FILE
    if not env_file.is_file():
        return None

    with open(env_file, "rb") as f:
        raw = tomllib.load(f)

    return _parse_environment_data(raw)


def _detect_cluster_name() -> str:
    """Detect cluster name from environment variables or hostname."""
    cluster_name = os.environ.get("SLURM_CLUSTER_NAME", "")
    if cluster_name:
        return cluster_name

    result = subprocess.run(
        ["hostname", "-s"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return result.stdout.strip()
    return ""


def detect_environment() -> EnvironmentInfo:
    """Auto-detect the HPC execution environment.

    Probes Slurm (sinfo), module system, and filesystem to build
    an EnvironmentInfo.
    """
    info = EnvironmentInfo()

    # Detect scheduler
    if _command_exists("sinfo"):
        info.scheduler = "slurm"
        info.partitions = _detect_slurm_partitions()

    info.cluster_name = _detect_cluster_name()
    info.modules = _detect_modules()

    return info


def save_environment(project_root: Path, info: EnvironmentInfo) -> Path:
    """Save environment info to .runops/environment.toml."""
    if tomli_w is None:
        msg = "tomli_w is required to write environment.toml"
        raise RuntimeError(msg)

    runops_dir = project_root / _SIMCTL_DIR
    runops_dir.mkdir(exist_ok=True)
    env_file = runops_dir / _ENV_FILE

    data: dict[str, Any] = {
        "cluster": {
            "name": info.cluster_name,
            "scheduler": info.scheduler,
        },
    }

    if info.scratch_path:
        data["cluster"]["scratch_path"] = info.scratch_path

    if info.constraints:
        data["cluster"]["constraints"] = info.constraints

    if info.partitions:
        parts: dict[str, Any] = {}
        for p in info.partitions:
            pd: dict[str, Any] = {}
            if p.max_nodes:
                pd["max_nodes"] = p.max_nodes
            if p.max_walltime:
                pd["max_walltime"] = p.max_walltime
            if p.gpu:
                pd["gpu"] = True
            if p.default:
                pd["default"] = True
            parts[p.name] = pd
        data["cluster"]["partitions"] = parts

    if info.modules:
        data["modules"] = info.modules

    with open(env_file, "wb") as f:
        tomli_w.dump(data, f)

    return env_file


def _command_exists(cmd: str) -> bool:
    """Check if a command is available in PATH."""
    return shutil.which(cmd) is not None


def _parse_sinfo_output(output: str) -> list[PartitionInfo]:
    """Parse ``sinfo --format=%P %D %l`` output into partition records."""
    partitions: list[PartitionInfo] = []
    for line in output.strip().splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        name = parts[0]
        is_default = name.endswith("*")
        if is_default:
            name = name[:-1]
        try:
            max_nodes = int(parts[1])
        except ValueError:
            max_nodes = 0
        max_walltime = parts[2] if parts[2] != "infinite" else ""
        partitions.append(
            PartitionInfo(
                name=name,
                max_nodes=max_nodes,
                max_walltime=max_walltime,
                default=is_default,
            )
        )
    return partitions


def _detect_slurm_partitions() -> list[PartitionInfo]:
    """Detect Slurm partitions via sinfo."""
    result = subprocess.run(
        [
            "sinfo",
            "--noheader",
            "--format=%P %D %l",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    return _parse_sinfo_output(result.stdout)


def _parse_module_list_output(output: str) -> dict[str, list[str]]:
    """Parse ``module list`` output into the current module set."""
    modules: list[str] = []
    for line in output.splitlines():
        normalized = line.strip()
        if (
            not normalized
            or normalized.startswith("Currently")
            or normalized.startswith("No")
        ):
            continue
        for part in normalized.split():
            candidate = part.strip().rstrip(")")
            if "/" in candidate and not candidate.startswith("-"):
                modules.append(candidate)

    if modules:
        return {"current": modules}
    return {}


def _detect_modules() -> dict[str, list[str]]:
    """Detect loaded modules (if module system is available)."""
    result = subprocess.run(
        ["bash", "-c", "module list 2>&1"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return {}
    return _parse_module_list_output(result.stdout)
