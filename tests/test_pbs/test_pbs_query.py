"""Tests for PBS qstat query helpers."""

from __future__ import annotations

import pytest

from runops.core.state import RunState
from runops.pbs.query import (
    PbsQueryError,
    map_pbs_state,
    qstat_status,
    query_job_status,
)
from runops.pbs.submit import CommandResult, PbsNotFoundError


def _runner(
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> callable:
    def run(cmd: list[str]) -> CommandResult:
        return CommandResult(returncode=returncode, stdout=stdout, stderr=stderr)

    return run


class TestMapPbsState:
    """Tests for PBS state mapping."""

    @pytest.mark.parametrize(
        ("pbs_state", "expected"),
        [
            ("Q", RunState.SUBMITTED),
            ("H", RunState.SUBMITTED),
            ("R", RunState.RUNNING),
            ("E", RunState.RUNNING),
            ("C", RunState.COMPLETED),
            ("F", RunState.COMPLETED),
        ],
    )
    def test_known_states(self, pbs_state: str, expected: RunState) -> None:
        state, reason = map_pbs_state(pbs_state)
        assert state is expected
        assert reason == ""

    def test_completed_nonzero_exit_fails(self) -> None:
        state, reason = map_pbs_state("C", exit_code="1")
        assert state is RunState.FAILED
        assert reason == "exit_error"

    def test_qdel_exit_status_cancels(self) -> None:
        state, reason = map_pbs_state("C", exit_code="271")
        assert state is RunState.CANCELLED
        assert reason == ""

    def test_unknown_state_raises(self) -> None:
        with pytest.raises(PbsQueryError, match="Unknown PBS job state"):
            map_pbs_state("?")


class TestQstatStatus:
    """Tests for qstat -f parsing."""

    def test_running_job(self) -> None:
        stdout = "Job Id: 123\n    job_state = R\n"
        result = qstat_status("123", runner=_runner(stdout=stdout))
        assert result == {"state": "R", "exit_status": ""}

    def test_completed_job_with_exit_status(self) -> None:
        stdout = "Job Id: 123\n    job_state = C\n    exit_status = 0\n"
        result = qstat_status("123", runner=_runner(stdout=stdout))
        assert result == {"state": "C", "exit_status": "0"}

    def test_unknown_job_returns_none(self) -> None:
        result = qstat_status(
            "999",
            runner=_runner(returncode=1, stderr="qstat: Unknown Job Id 999"),
        )
        assert result is None

    def test_other_error_raises(self) -> None:
        with pytest.raises(PbsQueryError, match="qstat failed"):
            qstat_status("123", runner=_runner(returncode=1, stderr="server down"))


class TestQueryJobStatus:
    """Tests for combined PBS query."""

    def test_active_job(self) -> None:
        result = query_job_status(
            "123",
            runner=_runner(stdout="Job Id: 123\n    job_state = R\n"),
        )
        assert result.run_state is RunState.RUNNING
        assert result.pbs_state == "R"

    def test_falls_back_to_historic(self) -> None:
        calls: list[list[str]] = []

        def runner(cmd: list[str]) -> CommandResult:
            calls.append(cmd)
            if "-x" in cmd:
                return CommandResult(0, "Job Id: 123\n    job_state = C\n", "")
            return CommandResult(1, "", "qstat: Unknown Job Id 123")

        result = query_job_status("123", runner=runner)
        assert result.run_state is RunState.COMPLETED
        assert any("-x" in call for call in calls)

    def test_job_not_found_raises(self) -> None:
        with pytest.raises(PbsQueryError, match="not found"):
            query_job_status(
                "123",
                runner=_runner(returncode=1, stderr="qstat: Unknown Job Id 123"),
            )

    def test_pbs_not_found_propagates(self) -> None:
        def runner(cmd: list[str]) -> CommandResult:
            raise PbsNotFoundError("qstat not found")

        with pytest.raises(PbsNotFoundError):
            query_job_status("123", runner=runner)
