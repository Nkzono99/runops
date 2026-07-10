"""Slurm sbatch submission.

Provides functions to submit job scripts via sbatch and parse the resulting
job ID.  All subprocess calls go through a single ``run_command`` callable
so that tests can inject a mock without touching the real Slurm installation.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

from runops.application.ports.scheduler import (
    SchedulerOutcomeUnknownError,
    SchedulerRejectedError,
)

# ---------------------------------------------------------------------------
# Thin subprocess abstraction
# ---------------------------------------------------------------------------

_SBATCH_JOB_RE = re.compile(r"Submitted batch job (\d+)")


class CommandResult(NamedTuple):
    """Result of a shell command execution."""

    returncode: int
    stdout: str
    stderr: str


#: Type alias for the injectable command runner.
CommandRunner = Callable[[list[str]], CommandResult]


def _default_runner(cmd: list[str]) -> CommandResult:
    """Run a command via ``subprocess.run``.

    This is the production implementation used when no mock is injected.

    Args:
        cmd: Command and arguments to execute.

    Returns:
        A ``CommandResult`` with return code, stdout, and stderr.

    Raises:
        SlurmNotFoundError: If the command executable is not found on PATH.
    """
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except FileNotFoundError as exc:
        raise SlurmNotFoundError(
            f"Command not found: {cmd[0]!r}. Is Slurm installed and on PATH?"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise SlurmSubmissionOutcomeUnknownError(
            f"sbatch timed out after 60 seconds: {exc}"
        ) from exc
    return CommandResult(
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
    )


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class SlurmNotFoundError(SchedulerRejectedError):
    """Raised when the Slurm command is not found on PATH."""


class SlurmSubmitError(RuntimeError):
    """Raised when sbatch fails or returns unexpected output."""


class SlurmSubmissionRejectedError(SlurmSubmitError, SchedulerRejectedError):
    """Raised when sbatch definitively rejects or cannot receive a request."""


class SlurmSubmissionOutcomeUnknownError(
    SlurmSubmitError,
    SchedulerOutcomeUnknownError,
):
    """Raised when sbatch may have accepted a request but no job ID is known."""


class SlurmCancelError(RuntimeError):
    """Raised when scancel fails."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_job_id(sbatch_stdout: str) -> str:
    """Extract the job ID from sbatch standard output.

    Expected format: ``Submitted batch job 12345``

    Args:
        sbatch_stdout: The captured stdout from an sbatch invocation.

    Returns:
        The numeric job ID as a string.

    Raises:
        SlurmSubmitError: If the output does not match the expected pattern.
    """
    match = _SBATCH_JOB_RE.search(sbatch_stdout)
    if match is None:
        raise SlurmSubmissionOutcomeUnknownError(
            f"Could not parse job ID from sbatch output: {sbatch_stdout!r}"
        )
    return match.group(1)


def submit_command(
    command: tuple[str, ...],
    *,
    runner: CommandRunner | None = None,
) -> str:
    """Execute one validated, already-planned ``sbatch`` command vector."""
    if not command or command[0] != "sbatch":
        raise SlurmSubmissionRejectedError(
            "submission command must start with 'sbatch'"
        )

    run = runner or _default_runner
    result = run(list(command))
    if result.returncode < 0:
        raise SlurmSubmissionOutcomeUnknownError(
            "sbatch client terminated by signal "
            f"{-result.returncode}; scheduler acceptance is unknown: "
            f"{result.stderr.strip()}"
        )
    if result.returncode > 0:
        raise SlurmSubmissionRejectedError(
            f"sbatch failed (exit {result.returncode}):\n{result.stderr.strip()}"
        )
    return parse_job_id(result.stdout)


def sbatch_submit(
    job_script: Path,
    working_dir: Path,
    *,
    extra_args: list[str] | None = None,
    afterok: str | None = None,
    runner: CommandRunner | None = None,
) -> str:
    """Submit a job script via ``sbatch``.

    Args:
        job_script: Path to the job script file (e.g. ``submit/job.sh``).
        working_dir: Working directory for the sbatch process (typically
            the run directory's ``work/`` subdirectory).
        extra_args: Additional sbatch arguments (e.g.
            ``["--partition=gr10451a"]``).  These override script directives.
        afterok: If set, add ``--dependency=afterok:<job_id>`` so this job
            starts only after the specified job completes successfully.
        runner: Optional callable that executes a command list and returns
            a ``CommandResult``.  Defaults to the real subprocess runner.
            Inject a mock here for testing.

    Returns:
        The Slurm job ID as a string.

    Raises:
        FileNotFoundError: If *job_script* does not exist.
        SlurmNotFoundError: If ``sbatch`` is not on PATH.
        SlurmSubmitError: If sbatch returns a non-zero exit code or its
            output cannot be parsed.
    """
    if not job_script.exists():
        raise FileNotFoundError(f"Job script not found: {job_script}")

    cmd = ["sbatch", f"--chdir={working_dir}"]
    if afterok:
        cmd.append(f"--dependency=afterok:{afterok}")
    if extra_args:
        cmd.extend(extra_args)
    cmd.append(str(job_script))
    return submit_command(tuple(cmd), runner=runner)


def scancel_job(
    job_id: str,
    *,
    runner: CommandRunner | None = None,
) -> None:
    """Cancel a Slurm job via ``scancel``.

    Args:
        job_id: The Slurm job ID to cancel.
        runner: Optional callable that executes a command list and returns
            a ``CommandResult``.  Defaults to the real subprocess runner.

    Raises:
        SlurmNotFoundError: If ``scancel`` is not on PATH.
        SlurmCancelError: If scancel returns a non-zero exit code.
    """
    run = runner or _default_runner
    result = run(["scancel", job_id])
    if result.returncode != 0:
        raise SlurmCancelError(
            f"scancel failed (exit {result.returncode}):\n{result.stderr.strip()}"
        )


# Keep the old name as an alias so the existing test import still works,
# but point it at the new implementation.
def sbatch(job_script: Path) -> str:
    """Submit a job script via sbatch (legacy wrapper).

    Deprecated: prefer ``sbatch_submit`` which accepts a working directory
    and an injectable runner.

    Args:
        job_script: Path to the job.sh file.

    Returns:
        The Slurm job_id as a string.
    """
    return sbatch_submit(job_script, job_script.parent)
