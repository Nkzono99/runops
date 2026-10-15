"""Thin, mockable wrappers around sbatch / scancel / squeue / sacct."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from runops.errors import RunError
from runops.manifest import RunState


class CommandResult(NamedTuple):
    returncode: int
    stdout: str
    stderr: str


CommandRunner = Callable[[list[str]], CommandResult]


def default_runner(cmd: list[str]) -> CommandResult:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=120)
    except FileNotFoundError:
        raise RunError(f"{cmd[0]} not found; is Slurm available on this host?") from None
    except subprocess.TimeoutExpired:
        raise RunError(f"{cmd[0]} timed out after 120 s") from None
    return CommandResult(proc.returncode, proc.stdout, proc.stderr)


_STATE_MAP = {
    "PENDING": RunState.SUBMITTED,
    "REQUEUED": RunState.SUBMITTED,
    "CONFIGURING": RunState.RUNNING,
    "RUNNING": RunState.RUNNING,
    "COMPLETING": RunState.RUNNING,
    "SUSPENDED": RunState.RUNNING,
    "COMPLETED": RunState.COMPLETED,
    "FAILED": RunState.FAILED,
    "NODE_FAIL": RunState.FAILED,
    "OUT_OF_MEMORY": RunState.FAILED,
    "TIMEOUT": RunState.FAILED,
    "PREEMPTED": RunState.FAILED,
    "BOOT_FAIL": RunState.FAILED,
    "DEADLINE": RunState.FAILED,
    "CANCELLED": RunState.CANCELLED,
}

_JOB_RE = re.compile(r"Submitted batch job (\d+)")


@dataclass
class JobState:
    state: RunState
    slurm_state: str
    exit_code: str = ""


def map_state(raw: str) -> RunState | None:
    key = raw.strip().split()[0].rstrip("+") if raw.strip() else ""
    return _STATE_MAP.get(key)


def sbatch(
    job_script: Path,
    workdir: Path,
    *,
    extra: list[str],
    runner: CommandRunner,
) -> tuple[str, CommandResult]:
    cmd = ["sbatch", f"--chdir={workdir}", *extra, str(job_script)]
    result = runner(cmd)
    if result.returncode != 0:
        raise RunError(f"sbatch failed (exit {result.returncode}): {result.stderr.strip()}")
    match = _JOB_RE.search(result.stdout)
    if not match:
        raise RunError(f"could not parse job id from sbatch output: {result.stdout!r}")
    return match.group(1), result


def scancel(job_id: str, *, runner: CommandRunner) -> None:
    result = runner(["scancel", job_id])
    if result.returncode != 0:
        raise RunError(f"scancel {job_id} failed: {result.stderr.strip()}")


def query(job_id: str, *, runner: CommandRunner) -> JobState | None:
    """squeue first, then sacct. ``None`` when Slurm knows nothing of the job."""
    result = runner(["squeue", "--job", job_id, "--noheader", "--format=%T"])
    if result.returncode == 0 and result.stdout.strip():
        raw = result.stdout.strip().splitlines()[0]
        state = map_state(raw)
        if state is not None:
            return JobState(state, raw.split()[0])
    result = runner(
        [
            "sacct",
            "--jobs",
            job_id,
            "--noheader",
            "--parsable2",
            "--format=JobID,State,ExitCode",
        ]
    )
    if result.returncode != 0:
        raise RunError(f"sacct failed for job {job_id}: {result.stderr.strip()}")
    for line in result.stdout.splitlines():
        parts = line.split("|")
        if len(parts) >= 3 and parts[0].strip() == job_id:
            state = map_state(parts[1])
            if state is None:
                raise RunError(f"unknown Slurm state {parts[1]!r} for job {job_id}")
            return JobState(state, parts[1].split()[0].rstrip("+"), parts[2].strip())
    return None
