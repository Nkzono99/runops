"""Tests for Slurm job state query module."""

from __future__ import annotations

import pytest

from runops.core.state import RunState
from runops.slurm.query import (
    SlurmQueryError,
    _parse_timelimit,
    map_slurm_state,
    query_job_status,
    sacct_status,
    sinfo_partitions,
    squeue_status,
)
from runops.slurm.submit import CommandResult, SlurmNotFoundError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _runner(
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> callable:
    """Return a mock runner that always returns the given result."""

    def run(cmd: list[str]) -> CommandResult:
        return CommandResult(returncode=returncode, stdout=stdout, stderr=stderr)

    return run


# ---------------------------------------------------------------------------
# map_slurm_state
# ---------------------------------------------------------------------------


class TestMapSlurmState:
    """Tests for the Slurm-to-runops state mapping."""

    @pytest.mark.parametrize(
        ("slurm_state", "expected"),
        [
            ("PENDING", RunState.SUBMITTED),
            ("RUNNING", RunState.RUNNING),
            ("CONFIGURING", RunState.RUNNING),
            ("COMPLETING", RunState.RUNNING),
            ("COMPLETED", RunState.COMPLETED),
            ("FAILED", RunState.FAILED),
            ("NODE_FAIL", RunState.FAILED),
            ("OUT_OF_MEMORY", RunState.FAILED),
            ("TIMEOUT", RunState.FAILED),
            ("CANCELLED", RunState.CANCELLED),
            ("PREEMPTED", RunState.FAILED),
            ("REQUEUED", RunState.SUBMITTED),
        ],
    )
    def test_known_states(self, slurm_state: str, expected: RunState) -> None:
        assert map_slurm_state(slurm_state) == expected

    def test_cancelled_by_user(self) -> None:
        """CANCELLED by UID variant should still map to CANCELLED."""
        assert map_slurm_state("CANCELLED by 1000") == RunState.CANCELLED

    def test_state_with_plus_suffix(self) -> None:
        """States like COMPLETING+ should be handled."""
        assert map_slurm_state("COMPLETING+") == RunState.RUNNING

    def test_unknown_state_raises(self) -> None:
        with pytest.raises(SlurmQueryError, match="Unknown Slurm job state"):
            map_slurm_state("TOTALLY_UNKNOWN")


# ---------------------------------------------------------------------------
# squeue_status
# ---------------------------------------------------------------------------


class TestSqueueStatus:
    """Tests for squeue_status."""

    def test_running_job(self) -> None:
        result = squeue_status("12345", runner=_runner(stdout="RUNNING\n"))
        assert result == "RUNNING"

    def test_pending_job(self) -> None:
        result = squeue_status("12345", runner=_runner(stdout="PENDING\n"))
        assert result == "PENDING"

    def test_job_not_in_queue(self) -> None:
        """Empty output means the job left the queue."""
        result = squeue_status("12345", runner=_runner(stdout=""))
        assert result is None

    def test_invalid_job_id_stderr(self) -> None:
        """Some clusters return non-zero with 'Invalid job id'."""
        result = squeue_status(
            "99999",
            runner=_runner(
                returncode=1,
                stderr="slurm_load_jobs error: Invalid job id",
            ),
        )
        assert result is None

    def test_other_error_raises(self) -> None:
        with pytest.raises(SlurmQueryError, match="squeue failed"):
            squeue_status(
                "12345",
                runner=_runner(returncode=1, stderr="Connection refused"),
            )


# ---------------------------------------------------------------------------
# sacct_status
# ---------------------------------------------------------------------------


class TestSacctStatus:
    """Tests for sacct_status."""

    def test_completed_job(self) -> None:
        stdout = "12345|COMPLETED|0:0\n12345.batch|COMPLETED|0:0\n"
        result = sacct_status("12345", runner=_runner(stdout=stdout))
        assert result is not None
        assert result["state"] == "COMPLETED"
        assert result["exit_code"] == "0:0"

    def test_failed_job(self) -> None:
        stdout = "12345|FAILED|1:0\n12345.batch|FAILED|1:0\n"
        result = sacct_status("12345", runner=_runner(stdout=stdout))
        assert result is not None
        assert result["state"] == "FAILED"
        assert result["exit_code"] == "1:0"

    def test_cancelled_job(self) -> None:
        stdout = "12345|CANCELLED by 1000|0:0\n"
        result = sacct_status("12345", runner=_runner(stdout=stdout))
        assert result is not None
        assert result["state"] == "CANCELLED by 1000"

    def test_job_not_found(self) -> None:
        result = sacct_status("12345", runner=_runner(stdout=""))
        assert result is None

    def test_sacct_error_raises(self) -> None:
        with pytest.raises(SlurmQueryError, match="sacct failed"):
            sacct_status(
                "12345",
                runner=_runner(returncode=1, stderr="Slurm accounting error"),
            )

    def test_ignores_substep_lines(self) -> None:
        """Only the main job line (exact ID match) should be returned."""
        stdout = "12345.batch|COMPLETED|0:0\n12345.extern|COMPLETED|0:0\n"
        result = sacct_status("12345", runner=_runner(stdout=stdout))
        assert result is None

    def test_main_line_present_among_steps(self) -> None:
        stdout = (
            "12345|COMPLETED|0:0\n"
            "12345.batch|COMPLETED|0:0\n"
            "12345.extern|COMPLETED|0:0\n"
        )
        result = sacct_status("12345", runner=_runner(stdout=stdout))
        assert result is not None
        assert result["state"] == "COMPLETED"


# ---------------------------------------------------------------------------
# query_job_status (combined)
# ---------------------------------------------------------------------------


class TestQueryJobStatus:
    """Tests for the combined query_job_status function."""

    def test_active_job_uses_squeue(self) -> None:
        """If squeue returns a state, sacct is not needed."""
        call_log: list[str] = []

        def runner(cmd: list[str]) -> CommandResult:
            call_log.append(cmd[0])
            if cmd[0] == "squeue":
                return CommandResult(0, "RUNNING\n", "")
            return CommandResult(0, "", "")

        result = query_job_status("12345", runner=runner)
        assert result.run_state is RunState.RUNNING
        assert result.slurm_state == "RUNNING"
        assert "sacct" not in call_log

    def test_completed_job_falls_to_sacct(self) -> None:
        """If squeue returns empty, sacct should be consulted."""

        def runner(cmd: list[str]) -> CommandResult:
            if cmd[0] == "squeue":
                return CommandResult(0, "", "")
            # sacct
            return CommandResult(0, "12345|COMPLETED|0:0\n", "")

        result = query_job_status("12345", runner=runner)
        assert result.run_state is RunState.COMPLETED
        assert result.slurm_state == "COMPLETED"

    def test_failed_job_from_sacct(self) -> None:
        def runner(cmd: list[str]) -> CommandResult:
            if cmd[0] == "squeue":
                return CommandResult(0, "", "")
            return CommandResult(0, "12345|FAILED|1:0\n", "")

        result = query_job_status("12345", runner=runner)
        assert result.run_state is RunState.FAILED
        assert result.failure_reason == "exit_error"
        assert result.exit_code == "1:0"

    def test_cancelled_from_sacct(self) -> None:
        def runner(cmd: list[str]) -> CommandResult:
            if cmd[0] == "squeue":
                return CommandResult(0, "", "")
            return CommandResult(0, "12345|CANCELLED by 1000|0:0\n", "")

        result = query_job_status("12345", runner=runner)
        assert result.run_state is RunState.CANCELLED

    def test_timeout_records_reason(self) -> None:
        """TIMEOUT should map to failed with reason='timeout'."""

        def runner(cmd: list[str]) -> CommandResult:
            if cmd[0] == "squeue":
                return CommandResult(0, "", "")
            return CommandResult(0, "12345|TIMEOUT|0:0\n", "")

        result = query_job_status("12345", runner=runner)
        assert result.run_state is RunState.FAILED
        assert result.failure_reason == "timeout"

    def test_oom_records_reason(self) -> None:
        """OUT_OF_MEMORY should map to failed with reason='oom'."""

        def runner(cmd: list[str]) -> CommandResult:
            if cmd[0] == "squeue":
                return CommandResult(0, "", "")
            return CommandResult(0, "12345|OUT_OF_MEMORY|0:0\n", "")

        result = query_job_status("12345", runner=runner)
        assert result.run_state is RunState.FAILED
        assert result.failure_reason == "oom"

    def test_job_purged_raises(self) -> None:
        """If neither squeue nor sacct finds the job, raise."""

        def runner(cmd: list[str]) -> CommandResult:
            return CommandResult(0, "", "")

        with pytest.raises(SlurmQueryError, match="not found in squeue or sacct"):
            query_job_status("12345", runner=runner)

    def test_slurm_not_found_propagates(self) -> None:
        def runner(cmd: list[str]) -> CommandResult:
            raise SlurmNotFoundError("squeue not found")

        with pytest.raises(SlurmNotFoundError):
            query_job_status("12345", runner=runner)


# ---------------------------------------------------------------------------
# _parse_timelimit
# ---------------------------------------------------------------------------


class TestParseTimelimit:
    """Tests for Slurm time limit parsing."""

    def test_days_hours_minutes_seconds(self) -> None:
        assert _parse_timelimit("5-00:00:00") == 120.0

    def test_hours_minutes_seconds(self) -> None:
        assert _parse_timelimit("120:00:00") == 120.0

    def test_one_day(self) -> None:
        assert _parse_timelimit("1-00:00:00") == 24.0

    def test_mixed(self) -> None:
        result = _parse_timelimit("1-12:30:00")
        assert abs(result - 36.5) < 0.01

    def test_infinite(self) -> None:
        assert _parse_timelimit("infinite") == float("inf")

    def test_na(self) -> None:
        assert _parse_timelimit("n/a") == float("inf")

    @pytest.mark.parametrize(
        "timelimit",
        ["00:00:00", "01:60:00", "01:00:60", "-01:00:00"],
    )
    def test_invalid_or_non_positive_limit_is_unknown(self, timelimit: str) -> None:
        assert _parse_timelimit(timelimit) == float("inf")


# ---------------------------------------------------------------------------
# sinfo_partitions
# ---------------------------------------------------------------------------


class TestSinfoPartitions:
    """Tests for sinfo partition query."""

    def test_parses_multiple_partitions(self) -> None:
        stdout = (
            "gr10451a|up|5-00:00:00|16\n"
            "gr10451b*|up|1-00:00:00|8\n"
            "debug|up|01:00:00|2\n"
        )
        result = sinfo_partitions(runner=_runner(stdout=stdout))
        assert len(result) == 3
        assert "gr10451a" in result
        assert "gr10451b" in result  # trailing * stripped
        assert "debug" in result

        assert result["gr10451a"].timelimit_hours == 120.0
        assert result["gr10451b"].timelimit_hours == 24.0
        assert result["gr10451a"].nodes_total == 16
        assert result["debug"].avail == "up"

    def test_empty_output(self) -> None:
        result = sinfo_partitions(runner=_runner(stdout=""))
        assert len(result) == 0

    def test_error_raises(self) -> None:
        with pytest.raises(SlurmQueryError, match="sinfo failed"):
            sinfo_partitions(
                runner=_runner(returncode=1, stderr="Connection refused"),
            )

    def test_slurm_not_found(self) -> None:
        def runner(cmd: list[str]) -> CommandResult:
            raise SlurmNotFoundError("sinfo not found")

        with pytest.raises(SlurmNotFoundError):
            sinfo_partitions(runner=runner)
