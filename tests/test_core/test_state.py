"""Tests for core state module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runops.core.exceptions import InvalidStateTransitionError
from runops.core.manifest import ManifestData, write_manifest
from runops.core.state import (
    RunState,
    reset_state_for_retry,
    transition_state,
    update_state,
    validate_transition,
)


class TestRunState:
    """Tests for RunState enum."""

    def test_all_states_defined(self) -> None:
        expected = {
            "created",
            "submitted",
            "running",
            "completed",
            "failed",
            "cancelled",
            "archived",
            "purged",
        }
        assert {s.value for s in RunState} == expected

    def test_string_equality(self) -> None:
        assert RunState.CREATED == "created"
        assert RunState.COMPLETED == "completed"


class TestValidateTransition:
    """Tests for validate_transition()."""

    def test_valid_created_to_submitted(self) -> None:
        assert validate_transition(RunState.CREATED, RunState.SUBMITTED) is True

    def test_valid_created_to_failed(self) -> None:
        assert validate_transition(RunState.CREATED, RunState.FAILED) is True

    def test_valid_submitted_to_running(self) -> None:
        assert validate_transition(RunState.SUBMITTED, RunState.RUNNING) is True

    def test_valid_submitted_to_cancelled(self) -> None:
        assert validate_transition(RunState.SUBMITTED, RunState.CANCELLED) is True

    def test_valid_running_to_completed(self) -> None:
        assert validate_transition(RunState.RUNNING, RunState.COMPLETED) is True

    def test_valid_running_to_failed(self) -> None:
        assert validate_transition(RunState.RUNNING, RunState.FAILED) is True

    def test_valid_completed_to_archived(self) -> None:
        assert validate_transition(RunState.COMPLETED, RunState.ARCHIVED) is True

    def test_valid_archived_to_purged(self) -> None:
        assert validate_transition(RunState.ARCHIVED, RunState.PURGED) is True

    def test_invalid_created_to_completed(self) -> None:
        assert validate_transition(RunState.CREATED, RunState.COMPLETED) is False

    def test_invalid_failed_to_anything(self) -> None:
        for target in RunState:
            assert validate_transition(RunState.FAILED, target) is False

    def test_invalid_purged_to_anything(self) -> None:
        for target in RunState:
            assert validate_transition(RunState.PURGED, target) is False


class TestTransitionState:
    """Tests for transition_state()."""

    def test_valid_transition_returns_target(self) -> None:
        result = transition_state(RunState.CREATED, RunState.SUBMITTED)
        assert result is RunState.SUBMITTED

    def test_invalid_transition_raises(self) -> None:
        with pytest.raises(InvalidStateTransitionError) as exc_info:
            transition_state(RunState.CREATED, RunState.COMPLETED)
        assert exc_info.value.current == "created"
        assert exc_info.value.target == "completed"


class TestUpdateState:
    """Tests for update_state()."""

    def test_update_created_to_submitted(self, tmp_path: Path) -> None:
        data = ManifestData(
            run={"id": "R20260327-0001", "status": "created"},
        )
        write_manifest(tmp_path, data)
        (tmp_path / "status").mkdir()

        update_state(tmp_path, RunState.SUBMITTED)

        # Check manifest was updated
        from runops.core.manifest import read_manifest

        manifest = read_manifest(tmp_path)
        assert manifest.run["status"] == "submitted"

        # Check state.json was written
        state_file = tmp_path / "status" / "state.json"
        assert state_file.exists()
        state_data = json.loads(state_file.read_text())
        assert state_data["state"] == "submitted"
        assert state_data["previous_state"] == "created"

    def test_invalid_transition_raises(self, tmp_path: Path) -> None:
        data = ManifestData(
            run={"id": "R20260327-0001", "status": "created"},
        )
        write_manifest(tmp_path, data)

        with pytest.raises(InvalidStateTransitionError):
            update_state(tmp_path, RunState.COMPLETED)

    def test_creates_status_dir(self, tmp_path: Path) -> None:
        data = ManifestData(
            run={"id": "R20260327-0001", "status": "created"},
        )
        write_manifest(tmp_path, data)
        # status/ dir does not exist yet

        update_state(tmp_path, RunState.SUBMITTED)
        assert (tmp_path / "status" / "state.json").exists()


class TestResetStateForRetry:
    """Tests for reset_state_for_retry()."""

    def test_resets_failed_run_and_writes_state_json(self, tmp_path: Path) -> None:
        data = ManifestData(
            run={
                "id": "R20260327-0001",
                "status": "failed",
                "failure_reason": "timeout",
                "last_slurm_state": "TIMEOUT",
            },
            job={
                "job_id": "12345",
                "submitted_at": "2026-04-01T00:00:00Z",
            },
        )
        write_manifest(tmp_path, data)

        previous = reset_state_for_retry(
            tmp_path,
            job_updates={"attempt": 1, "retry_adjustments": {"walltime": "2x"}},
        )

        assert previous is RunState.FAILED

        from runops.core.manifest import read_manifest

        manifest = read_manifest(tmp_path)
        assert manifest.run["status"] == "created"
        assert manifest.run["failure_reason"] == ""
        assert manifest.run["last_slurm_state"] == ""
        assert manifest.job["job_id"] == ""
        assert manifest.job["submitted_at"] == ""
        assert manifest.job["attempt"] == 1
        assert manifest.job["retry_adjustments"] == {"walltime": "2x"}

        state_data = json.loads((tmp_path / "status" / "state.json").read_text())
        assert state_data["state"] == "created"
        assert state_data["previous_state"] == "failed"
        assert state_data["reason"] == "retry"
        assert "slurm_state" not in state_data

    def test_resets_cancelled_run(self, tmp_path: Path) -> None:
        data = ManifestData(
            run={
                "id": "R20260327-0002",
                "status": "cancelled",
                "last_slurm_state": "CANCELLED",
            },
            job={"job_id": "12345"},
        )
        write_manifest(tmp_path, data)

        previous = reset_state_for_retry(tmp_path)

        assert previous is RunState.CANCELLED

        from runops.core.manifest import read_manifest

        manifest = read_manifest(tmp_path)
        assert manifest.run["status"] == "created"
        assert manifest.run["last_slurm_state"] == ""
        assert manifest.job["job_id"] == ""

    def test_rejects_non_terminal_retry_reset(self, tmp_path: Path) -> None:
        data = ManifestData(
            run={"id": "R20260327-0003", "status": "created"},
        )
        write_manifest(tmp_path, data)

        with pytest.raises(InvalidStateTransitionError) as exc_info:
            reset_state_for_retry(tmp_path)

        assert exc_info.value.current == "created"
        assert exc_info.value.target == "created"
