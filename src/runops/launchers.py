"""MPI launcher profiles: build the exec line for job.sh."""

from __future__ import annotations

import shlex
from typing import Any

from runops.config import LauncherConfig


def task_count(job: dict[str, Any]) -> int:
    return int(job.get("ntasks", job.get("processes", 1)) or 1)


def exec_line(launcher: LauncherConfig, program: list[str], job: dict[str, Any]) -> str:
    """Return the shell line that launches *program* with *launcher*."""
    if not program or not program[0]:
        raise ValueError("program command is empty")
    prog = " ".join(shlex.quote(p) for p in program)
    if launcher.kind == "none":
        return prog
    parts = [launcher.command or launcher.kind]
    ntasks = task_count(job)
    if not launcher.use_slurm_ntasks:
        flags = {"srun": [f"--ntasks={ntasks}"], "mpirun": ["-np", str(ntasks)]}
        parts += flags.get(launcher.kind, ["-n", str(ntasks)])
    parts += shlex.split(launcher.args) if launcher.args else []
    parts += launcher.extra_options
    return " ".join(shlex.quote(p) for p in parts) + " " + prog
