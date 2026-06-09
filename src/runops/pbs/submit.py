"""PBS qsub submission helpers."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

_QSUB_JOB_RE = re.compile(r"([0-9]+(?:\.[A-Za-z0-9_.-]+)?)")


class CommandResult(NamedTuple):
    """Result of a shell command execution."""

    returncode: int
    stdout: str
    stderr: str


CommandRunner = Callable[[list[str]], CommandResult]


class PbsNotFoundError(RuntimeError):
    """Raised when a PBS command is not found on PATH."""


class PbsSubmitError(RuntimeError):
    """Raised when qsub fails or returns unexpected output."""


class PbsCancelError(RuntimeError):
    """Raised when qdel fails."""


def _default_runner(cmd: list[str]) -> CommandResult:
    """Run a PBS command via ``subprocess.run``."""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except FileNotFoundError as exc:
        raise PbsNotFoundError(
            f"Command not found: {cmd[0]!r}. Is PBS installed and on PATH?"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise PbsSubmitError(f"{cmd[0]} timed out after 60 seconds: {exc}") from exc
    return CommandResult(
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
    )


def parse_job_id(qsub_stdout: str) -> str:
    """Extract a PBS job ID from qsub stdout."""
    match = _QSUB_JOB_RE.search(qsub_stdout.strip())
    if match is None:
        raise PbsSubmitError(
            f"Could not parse job ID from qsub output: {qsub_stdout!r}"
        )
    return match.group(1)


def qsub_submit(
    job_script: Path,
    working_dir: Path,
    *,
    extra_args: list[str] | None = None,
    afterok: str | None = None,
    runner: CommandRunner | None = None,
) -> str:
    """Submit a job script via ``qsub``.

    Args:
        job_script: Path to the job script file.
        working_dir: Directory used as PBS working directory via ``qsub -d``.
        extra_args: Additional qsub arguments.
        afterok: If set, add ``-W depend=afterok:<job_id>``.
        runner: Optional command runner for tests.

    Returns:
        PBS job ID as a string.
    """
    if not job_script.exists():
        raise FileNotFoundError(f"Job script not found: {job_script}")

    run = runner or _default_runner
    cmd = ["qsub", "-d", str(working_dir)]
    if afterok:
        cmd.extend(["-W", f"depend=afterok:{afterok}"])
    if extra_args:
        cmd.extend(extra_args)
    cmd.append(str(job_script))

    result = run(cmd)
    if result.returncode != 0:
        raise PbsSubmitError(
            f"qsub failed (exit {result.returncode}):\n{result.stderr.strip()}"
        )
    return parse_job_id(result.stdout)


def qdel_job(
    job_id: str,
    *,
    runner: CommandRunner | None = None,
) -> None:
    """Cancel a PBS job via ``qdel``."""
    run = runner or _default_runner
    result = run(["qdel", job_id])
    if result.returncode != 0:
        raise PbsCancelError(
            f"qdel failed (exit {result.returncode}):\n{result.stderr.strip()}"
        )
