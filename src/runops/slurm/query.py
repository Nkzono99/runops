"""Slurm job state queries via squeue and sacct.

Provides functions to query active and historical job states and map them to
runops ``RunState`` values.  All subprocess calls go through an injectable
``CommandRunner`` callable so that tests never invoke real Slurm commands.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass

from runops.core.case import parse_walltime_hours
from runops.core.state import RunState
from runops.slurm.submit import (
    CommandResult,
    CommandRunner,
    SlurmNotFoundError,
    _default_runner,
)

# ---------------------------------------------------------------------------
# Slurm state -> runops RunState mapping
# ---------------------------------------------------------------------------

_SLURM_STATE_MAP: dict[str, RunState] = {
    # Active / queued
    "PENDING": RunState.SUBMITTED,
    "CONFIGURING": RunState.RUNNING,
    "RUNNING": RunState.RUNNING,
    "COMPLETING": RunState.RUNNING,
    "SUSPENDED": RunState.RUNNING,
    "REQUEUED": RunState.SUBMITTED,
    # Successful termination
    "COMPLETED": RunState.COMPLETED,
    # Failure modes
    "FAILED": RunState.FAILED,
    "NODE_FAIL": RunState.FAILED,
    "OUT_OF_MEMORY": RunState.FAILED,
    "TIMEOUT": RunState.FAILED,
    "PREEMPTED": RunState.FAILED,
    "BOOT_FAIL": RunState.FAILED,
    "DEADLINE": RunState.FAILED,
    # Cancellation
    "CANCELLED": RunState.CANCELLED,
}


#: Maps Slurm failure states to human-readable failure reasons.
_FAILURE_REASON_MAP: dict[str, str] = {
    "TIMEOUT": "timeout",
    "OUT_OF_MEMORY": "oom",
    "NODE_FAIL": "node_fail",
    "PREEMPTED": "preempted",
    "BOOT_FAIL": "boot_fail",
    "DEADLINE": "deadline",
    "FAILED": "exit_error",
}


class SlurmQueryError(RuntimeError):
    """Raised when a Slurm query command fails unexpectedly."""


@dataclass(frozen=True)
class PartitionInfo:
    """Information about a Slurm partition from ``sinfo``.

    Attributes:
        name: Partition name.
        avail: Availability status (e.g. ``"up"``).
        timelimit: Raw time limit string from sinfo (e.g. ``"5-00:00:00"``).
        timelimit_hours: Time limit in hours (for easy comparison).
        nodes_total: Total node count in the partition.
    """

    name: str
    avail: str
    timelimit: str
    timelimit_hours: float
    nodes_total: int = 0


@dataclass(frozen=True)
class JobStatus:
    """Result of a Slurm job status query.

    Attributes:
        run_state: Mapped runops RunState.
        slurm_state: Raw Slurm state string.
        failure_reason: Reason for failure (empty if not failed).
        exit_code: Slurm exit code string (if available).
    """

    run_state: RunState
    slurm_state: str
    failure_reason: str = ""
    exit_code: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def map_slurm_state(slurm_state: str) -> RunState:
    """Map a raw Slurm job state string to a runops ``RunState``.

    Slurm may append qualifiers like ``CANCELLED by 1000`` -- only the first
    word is used for the lookup.

    Args:
        slurm_state: Raw state string from squeue or sacct (e.g.
            ``"RUNNING"``, ``"CANCELLED by 1000"``).

    Returns:
        The corresponding ``RunState``.

    Raises:
        SlurmQueryError: If the state is not recognised.
    """
    # Take first token to handle "CANCELLED by UID" variants
    key = slurm_state.strip().split()[0].rstrip("+")
    try:
        return _SLURM_STATE_MAP[key]
    except KeyError:
        raise SlurmQueryError(f"Unknown Slurm job state: {slurm_state!r}") from None


# ---------------------------------------------------------------------------
# sinfo (partition queries)
# ---------------------------------------------------------------------------


def _parse_timelimit(timelimit: str) -> float:
    """Parse a Slurm time limit string to hours.

    Supports formats like ``5-00:00:00``, ``120:00:00``, ``infinite``.

    Args:
        timelimit: Raw time limit string from sinfo.

    Returns:
        Time limit in hours, or ``float('inf')`` for unlimited.
    """
    if timelimit.lower() in ("infinite", "n/a"):
        return float("inf")
    parsed = parse_walltime_hours(timelimit.strip())
    return parsed if parsed is not None else float("inf")


def sinfo_partitions(
    *,
    runner: CommandRunner | None = None,
) -> OrderedDict[str, PartitionInfo]:
    """Query ``sinfo`` for available partitions and their limits.

    Args:
        runner: Optional command runner for testing.

    Returns:
        Ordered dict mapping partition name to :class:`PartitionInfo`.

    Raises:
        SlurmNotFoundError: If ``sinfo`` is not on PATH.
        SlurmQueryError: If sinfo returns an error.
    """
    run = runner or _default_runner
    cmd = [
        "sinfo",
        "--noheader",
        "--format=%P|%a|%l|%D",
    ]

    try:
        result: CommandResult = run(cmd)
    except SlurmNotFoundError:
        raise

    if result.returncode != 0:
        raise SlurmQueryError(
            f"sinfo failed (exit {result.returncode}):\n{result.stderr.strip()}"
        )

    partitions: OrderedDict[str, PartitionInfo] = OrderedDict()
    for line in result.stdout.strip().splitlines():
        parts = line.strip().split("|")
        if len(parts) < 4:
            continue
        name = parts[0].rstrip("*")  # default partition has trailing '*'
        avail = parts[1]
        timelimit = parts[2]
        try:
            nodes_total = int(parts[3])
        except ValueError:
            nodes_total = 0

        partitions[name] = PartitionInfo(
            name=name,
            avail=avail,
            timelimit=timelimit,
            timelimit_hours=_parse_timelimit(timelimit),
            nodes_total=nodes_total,
        )

    return partitions


# ---------------------------------------------------------------------------
# squeue
# ---------------------------------------------------------------------------


def squeue_status(
    job_id: str,
    *,
    runner: CommandRunner | None = None,
) -> str | None:
    """Query ``squeue`` for an active job's state.

    Args:
        job_id: Slurm job ID.
        runner: Optional command runner for testing.

    Returns:
        The raw Slurm state string (e.g. ``"RUNNING"``) if the job is still
        in the queue, or ``None`` if it has left the queue.

    Raises:
        SlurmNotFoundError: If ``squeue`` is not on PATH.
        SlurmQueryError: If squeue returns a non-zero exit code.
    """
    run = runner or _default_runner
    cmd = [
        "squeue",
        "--job",
        job_id,
        "--noheader",
        "--format=%T",
    ]

    try:
        result: CommandResult = run(cmd)
    except SlurmNotFoundError:
        raise

    if result.returncode != 0:
        # squeue returns non-zero when the job is not found on some clusters
        if "Invalid job id" in result.stderr:
            return None
        raise SlurmQueryError(
            f"squeue failed (exit {result.returncode}):\n{result.stderr.strip()}"
        )

    state = result.stdout.strip()
    if not state:
        return None
    return state


# ---------------------------------------------------------------------------
# sacct
# ---------------------------------------------------------------------------


def sacct_status(
    job_id: str,
    *,
    runner: CommandRunner | None = None,
) -> dict[str, str] | None:
    """Query ``sacct`` for a historical job's state and exit code.

    Uses ``--parsable2 --noheader`` with explicit format fields for reliable
    parsing.

    Args:
        job_id: Slurm job ID.
        runner: Optional command runner for testing.

    Returns:
        A dictionary with keys ``"state"`` and ``"exit_code"`` if the job is
        found, or ``None`` if sacct has no record.

    Raises:
        SlurmNotFoundError: If ``sacct`` is not on PATH.
        SlurmQueryError: If sacct returns a non-zero exit code.
    """
    run = runner or _default_runner
    cmd = [
        "sacct",
        "--jobs",
        job_id,
        "--noheader",
        "--parsable2",
        "--format=JobID,State,ExitCode",
    ]

    try:
        result: CommandResult = run(cmd)
    except SlurmNotFoundError:
        raise

    if result.returncode != 0:
        raise SlurmQueryError(
            f"sacct failed (exit {result.returncode}):\n{result.stderr.strip()}"
        )

    # sacct may return multiple lines (one per step).  We want the "batch"
    # line or the main job line (the one whose JobID matches exactly).
    for line in result.stdout.strip().splitlines():
        parts = line.split("|")
        if len(parts) < 3:
            continue
        sacct_job_id, state, exit_code = parts[0], parts[1], parts[2]
        # Match the main job entry (not sub-steps like "12345.batch")
        if sacct_job_id.strip() == job_id:
            return {"state": state.strip(), "exit_code": exit_code.strip()}

    return None


# ---------------------------------------------------------------------------
# Combined query
# ---------------------------------------------------------------------------


def query_job_status(
    job_id: str,
    *,
    runner: CommandRunner | None = None,
) -> JobStatus:
    """Determine the current runops state of a Slurm job.

    Strategy: try ``squeue`` first (cheap, covers active jobs).  If the job
    is no longer in the queue, fall back to ``sacct`` (covers completed /
    historical jobs).

    Args:
        job_id: Slurm job ID.
        runner: Optional command runner for testing.

    Returns:
        A :class:`JobStatus` with the mapped state, raw Slurm state,
        failure reason, and exit code.

    Raises:
        SlurmNotFoundError: If Slurm commands are not on PATH.
        SlurmQueryError: If neither squeue nor sacct can find the job, or
            if the returned state is unrecognised.
    """
    # 1. Try squeue (active jobs)
    sq_state = squeue_status(job_id, runner=runner)
    if sq_state is not None:
        raw = sq_state.strip().split()[0].rstrip("+")
        return JobStatus(
            run_state=map_slurm_state(sq_state),
            slurm_state=raw,
        )

    # 2. Fall back to sacct (historical jobs)
    sa_info = sacct_status(job_id, runner=runner)
    if sa_info is not None:
        raw = sa_info["state"].strip().split()[0].rstrip("+")
        run_state = map_slurm_state(sa_info["state"])
        return JobStatus(
            run_state=run_state,
            slurm_state=raw,
            failure_reason=_FAILURE_REASON_MAP.get(raw, ""),
            exit_code=sa_info.get("exit_code", ""),
        )

    raise SlurmQueryError(
        f"Job {job_id} not found in squeue or sacct. "
        "It may have been purged from the Slurm database."
    )
