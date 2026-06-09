"""PBS job state queries via qstat."""

from __future__ import annotations

from dataclasses import dataclass

from runops.core.state import RunState
from runops.pbs.submit import (
    CommandResult,
    CommandRunner,
    PbsNotFoundError,
    _default_runner,
)

_PBS_STATE_MAP: dict[str, RunState] = {
    "Q": RunState.SUBMITTED,
    "H": RunState.SUBMITTED,
    "W": RunState.SUBMITTED,
    "T": RunState.SUBMITTED,
    "R": RunState.RUNNING,
    "E": RunState.RUNNING,
    "S": RunState.RUNNING,
}


class PbsQueryError(RuntimeError):
    """Raised when a PBS query command fails unexpectedly."""


@dataclass(frozen=True)
class PbsJobStatus:
    """Result of a PBS job status query."""

    run_state: RunState
    pbs_state: str
    failure_reason: str = ""
    exit_code: str = ""


def _parse_qstat_full(stdout: str) -> dict[str, str] | None:
    """Parse the subset of ``qstat -f`` output runops needs."""
    state = ""
    exit_status = ""
    for line in stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("job_state ="):
            state = stripped.split("=", 1)[1].strip()
        elif stripped.startswith("exit_status ="):
            exit_status = stripped.split("=", 1)[1].strip()
    if not state:
        return None
    return {"state": state, "exit_status": exit_status}


def map_pbs_state(pbs_state: str, *, exit_code: str = "") -> tuple[RunState, str]:
    """Map a PBS state code to runops state and failure reason."""
    key = pbs_state.strip().split()[0][:1].upper()
    if key in _PBS_STATE_MAP:
        return _PBS_STATE_MAP[key], ""
    if key in {"C", "F"}:
        if exit_code == "271":
            return RunState.CANCELLED, ""
        if exit_code and exit_code != "0":
            return RunState.FAILED, "exit_error"
        return RunState.COMPLETED, ""
    raise PbsQueryError(f"Unknown PBS job state: {pbs_state!r}")


def qstat_status(
    job_id: str,
    *,
    historic: bool = False,
    runner: CommandRunner | None = None,
) -> dict[str, str] | None:
    """Query ``qstat`` for a PBS job state."""
    run = runner or _default_runner
    cmd = ["qstat"]
    if historic:
        cmd.append("-x")
    cmd.extend(["-f", job_id])

    try:
        result: CommandResult = run(cmd)
    except PbsNotFoundError:
        raise

    if result.returncode != 0:
        stderr = result.stderr.strip()
        if "Unknown Job Id" in stderr or "Unknown Job Identifier" in stderr:
            return None
        raise PbsQueryError(f"qstat failed (exit {result.returncode}):\n{stderr}")

    return _parse_qstat_full(result.stdout)


def query_job_status(
    job_id: str,
    *,
    runner: CommandRunner | None = None,
) -> PbsJobStatus:
    """Query active then historical PBS state for a job."""
    info = qstat_status(job_id, runner=runner)
    if info is None:
        info = qstat_status(job_id, historic=True, runner=runner)
    if info is None:
        raise PbsQueryError(f"Job {job_id} not found in qstat or qstat -x")

    state = info["state"]
    exit_code = info.get("exit_status", "")
    run_state, failure_reason = map_pbs_state(state, exit_code=exit_code)
    return PbsJobStatus(
        run_state=run_state,
        pbs_state=state,
        failure_reason=failure_reason,
        exit_code=exit_code,
    )
