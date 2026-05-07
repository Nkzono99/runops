"""Tests for runops runs status and runs sync CLI commands."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from runops.cli.main import app
from runops.core.state import RunState
from runops.slurm.query import JobStatus
from tests.factories import create_minimal_project, create_run_manifest, write_toml

runner = CliRunner()


# ---------------------------------------------------------------------------
# status command tests
# ---------------------------------------------------------------------------


def test_status_shows_run_info(tmp_path: Path) -> None:
    """status should display run_id, state, and job_id."""
    create_minimal_project(tmp_path, name="test")
    run_dir = tmp_path / "runs" / "R20260327-0001"
    create_run_manifest(run_dir, status="submitted", job_id="12345")

    with (
        patch("runops.cli.status.Path.cwd", return_value=tmp_path),
        patch(
            "runops.cli.status.query_job_status",
            return_value=JobStatus(run_state=RunState.RUNNING, slurm_state="RUNNING"),
        ),
    ):
        result = runner.invoke(app, ["runs", "status", str(run_dir)])

    assert result.exit_code == 0
    assert "R20260327-0001" in result.output
    assert "submitted" in result.output
    assert "12345" in result.output
    assert "RUNNING" in result.output


def test_status_no_job_id(tmp_path: Path) -> None:
    """status with no job_id should show 'not submitted'."""
    create_minimal_project(tmp_path, name="test")
    run_dir = tmp_path / "runs" / "R20260327-0001"
    create_run_manifest(run_dir, status="created", job_id="")

    with patch("runops.cli.status.Path.cwd", return_value=tmp_path):
        result = runner.invoke(app, ["runs", "status", str(run_dir)])

    assert result.exit_code == 0
    assert "not submitted" in result.output


def test_status_shows_completed_run_readiness_warning(tmp_path: Path) -> None:
    """Completed scheduler state should not hide missing required artifacts."""
    create_minimal_project(tmp_path, name="test")
    run_dir = tmp_path / "runs" / "R20260507-0001"
    create_run_manifest(
        run_dir,
        status="completed",
        simulator_name="emses",
        adapter="emses",
    )
    write_toml(run_dir / "input" / "plasma.toml", {"jobcon": {"nstep": 100}})
    (run_dir / "work").mkdir(parents=True, exist_ok=True)
    (run_dir / "work" / "energy").write_text("100 1.0 2.0\n", encoding="utf-8")

    with patch("runops.cli.status.Path.cwd", return_value=tmp_path):
        result = runner.invoke(app, ["runs", "status", str(run_dir)])

    assert result.exit_code == 0, result.output
    assert "State:  completed" in result.output
    assert "Analysis: incomplete" in result.output
    assert "Missing artifacts: hdf5_fields" in result.output


def test_status_slurm_unavailable(tmp_path: Path) -> None:
    """status should gracefully handle missing Slurm commands."""
    create_minimal_project(tmp_path, name="test")
    run_dir = tmp_path / "runs" / "R20260327-0001"
    create_run_manifest(run_dir, status="submitted", job_id="12345")

    from runops.slurm.submit import SlurmNotFoundError

    with (
        patch("runops.cli.status.Path.cwd", return_value=tmp_path),
        patch(
            "runops.cli.status.query_job_status",
            side_effect=SlurmNotFoundError("squeue not found"),
        ),
    ):
        result = runner.invoke(app, ["runs", "status", str(run_dir)])

    assert result.exit_code == 0
    assert "not available" in result.output


def test_status_run_not_found(tmp_path: Path) -> None:
    """status for a non-existent run should error."""
    create_minimal_project(tmp_path, name="test")

    with patch("runops.cli.status.Path.cwd", return_value=tmp_path):
        result = runner.invoke(app, ["runs", "status", "nonexistent"])
    assert result.exit_code != 0


def test_status_short_lists_runs_compactly(tmp_path: Path) -> None:
    """--short produces 1 line per run and skips Slurm queries."""
    create_minimal_project(tmp_path, name="test")
    survey = tmp_path / "runs" / "series_A"

    for i, state in enumerate(["completed", "running", "submitted"], start=1):
        run_dir = survey / f"R20260407-000{i}"
        create_run_manifest(
            run_dir,
            run_id=f"R20260407-000{i}",
            status=state,
            display_name=f"vti={0.02 * i:.2f}",
            job_id="" if state == "submitted" else "99",
            origin_case="series_A_flat_plate",
        )

    with patch("runops.cli.status.Path.cwd", return_value=tmp_path):
        result = runner.invoke(app, ["runs", "status", "--short", str(survey)])

    assert result.exit_code == 0, result.output
    lines = [ln for ln in result.output.strip().splitlines() if ln.strip()]
    assert len(lines) == 3
    assert "R20260407-0001" in result.output
    assert "completed" in result.output
    assert "series_A_flat_plate" in result.output
    assert "Run:    " not in result.output
    assert "Slurm:" not in result.output


def test_status_summary_aggregates_by_case(tmp_path: Path) -> None:
    """--summary groups runs by origin.case x state."""
    create_minimal_project(tmp_path, name="test")
    survey = tmp_path / "runs"

    layout = [
        ("series_A", "completed", 2),
        ("series_A", "running", 1),
        ("series_B", "failed", 3),
    ]
    counter = 0
    for case, state, n in layout:
        for _ in range(n):
            counter += 1
            run_dir = survey / case / f"R202604{counter:04d}"
            create_run_manifest(
                run_dir,
                run_id=f"R202604{counter:04d}",
                status=state,
                display_name="x",
                job_id="",
                origin_case=case,
            )

    with patch("runops.cli.status.Path.cwd", return_value=tmp_path):
        result = runner.invoke(app, ["runs", "status", "--summary", str(survey)])

    assert result.exit_code == 0, result.output
    assert "series_A" in result.output
    assert "completed=2" in result.output
    assert "running=1" in result.output
    assert "series_B" in result.output
    assert "failed=3" in result.output
    assert "6 run(s)" in result.output


def test_status_short_and_summary_are_mutually_exclusive(tmp_path: Path) -> None:
    create_minimal_project(tmp_path, name="test")
    with patch("runops.cli.status.Path.cwd", return_value=tmp_path):
        result = runner.invoke(app, ["runs", "status", "--short", "--summary"])
    assert result.exit_code == 2
    assert "mutually exclusive" in result.output


# ---------------------------------------------------------------------------
# sync command tests
# ---------------------------------------------------------------------------


def test_sync_updates_state(tmp_path: Path) -> None:
    """sync should transition state and show old -> new."""
    create_minimal_project(tmp_path, name="test")
    run_dir = tmp_path / "runs" / "R20260327-0001"
    create_run_manifest(run_dir, status="submitted", job_id="12345")

    with (
        patch("runops.cli.status.Path.cwd", return_value=tmp_path),
        patch(
            "runops.slurm.query.query_job_status",
            return_value=JobStatus(run_state=RunState.RUNNING, slurm_state="RUNNING"),
        ),
    ):
        result = runner.invoke(app, ["runs", "sync", str(run_dir)])

    assert result.exit_code == 0
    assert "submitted" in result.output
    assert "running" in result.output
    assert "->" in result.output

    # Verify manifest was actually updated
    from runops.core.manifest import read_manifest

    updated = read_manifest(run_dir)
    assert updated.run["status"] == "running"

    # Verify state.json was written
    state_json = run_dir / "status" / "state.json"
    assert state_json.exists()


def test_sync_no_change(tmp_path: Path) -> None:
    """sync should report no change when states match."""
    create_minimal_project(tmp_path, name="test")
    run_dir = tmp_path / "runs" / "R20260327-0001"
    create_run_manifest(run_dir, status="running", job_id="12345")

    with (
        patch("runops.cli.status.Path.cwd", return_value=tmp_path),
        patch(
            "runops.slurm.query.query_job_status",
            return_value=JobStatus(run_state=RunState.RUNNING, slurm_state="RUNNING"),
        ),
    ):
        result = runner.invoke(app, ["runs", "sync", str(run_dir)])

    assert result.exit_code == 0
    assert "unchanged" in result.output


def test_sync_no_job_id(tmp_path: Path) -> None:
    """sync without a job_id should error."""
    create_minimal_project(tmp_path, name="test")
    run_dir = tmp_path / "runs" / "R20260327-0001"
    create_run_manifest(run_dir, status="created", job_id="")

    with patch("runops.cli.status.Path.cwd", return_value=tmp_path):
        result = runner.invoke(app, ["runs", "sync", str(run_dir)])

    assert result.exit_code != 0
    assert "no job_id" in result.output.lower()


def test_sync_slurm_query_failure(tmp_path: Path) -> None:
    """sync should handle Slurm query failures gracefully."""
    create_minimal_project(tmp_path, name="test")
    run_dir = tmp_path / "runs" / "R20260327-0001"
    create_run_manifest(run_dir, status="submitted", job_id="12345")

    from runops.slurm.query import SlurmQueryError

    with (
        patch("runops.cli.status.Path.cwd", return_value=tmp_path),
        patch(
            "runops.slurm.query.query_job_status",
            side_effect=SlurmQueryError("Job not found"),
        ),
    ):
        result = runner.invoke(app, ["runs", "sync", str(run_dir)])

    assert result.exit_code != 0
    assert "query failed" in result.output or "Job not found" in result.output


def test_sync_completed(tmp_path: Path) -> None:
    """sync should transition running -> completed."""
    create_minimal_project(tmp_path, name="test")
    run_dir = tmp_path / "runs" / "R20260327-0001"
    create_run_manifest(run_dir, status="running", job_id="12345")

    with (
        patch("runops.cli.status.Path.cwd", return_value=tmp_path),
        patch(
            "runops.slurm.query.query_job_status",
            return_value=JobStatus(
                run_state=RunState.COMPLETED, slurm_state="COMPLETED"
            ),
        ),
    ):
        result = runner.invoke(app, ["runs", "sync", str(run_dir)])

    assert result.exit_code == 0
    assert "running" in result.output
    assert "completed" in result.output

    from runops.core.manifest import read_manifest

    updated = read_manifest(run_dir)
    assert updated.run["status"] == "completed"


# ---------------------------------------------------------------------------
# Bulk sync / status tests (multi-target argument list, survey directory)
# ---------------------------------------------------------------------------


def test_sync_survey_dir_processes_all_runs(tmp_path: Path) -> None:
    """Passing a survey directory syncs every run inside it."""
    create_minimal_project(tmp_path, name="test")
    survey = tmp_path / "runs" / "series_x"
    create_run_manifest(
        survey / "R20260327-0001",
        run_id="R20260327-0001",
        status="running",
        job_id="11111",
    )
    create_run_manifest(
        survey / "R20260327-0002",
        run_id="R20260327-0002",
        status="running",
        job_id="22222",
    )

    seen: list[str] = []

    def fake_query(job_id: str, runner=None):  # type: ignore[no-untyped-def]
        seen.append(job_id)
        return JobStatus(run_state=RunState.COMPLETED, slurm_state="COMPLETED")

    with (
        patch("runops.cli.status.Path.cwd", return_value=tmp_path),
        patch("runops.slurm.query.query_job_status", side_effect=fake_query),
    ):
        result = runner.invoke(app, ["runs", "sync", str(survey)])

    assert result.exit_code == 0, result.output
    assert "R20260327-0001" in result.output
    assert "R20260327-0002" in result.output
    assert sorted(seen) == ["11111", "22222"]


def test_sync_bulk_skips_runs_without_job_id(tmp_path: Path) -> None:
    """In multi-target mode, runs without job_id are silently skipped."""
    create_minimal_project(tmp_path, name="test")
    survey = tmp_path / "runs" / "series_x"
    create_run_manifest(
        survey / "R20260327-0001",
        run_id="R20260327-0001",
        status="created",
        job_id="",
    )
    create_run_manifest(
        survey / "R20260327-0002",
        run_id="R20260327-0002",
        status="running",
        job_id="22222",
    )

    with (
        patch("runops.cli.status.Path.cwd", return_value=tmp_path),
        patch(
            "runops.slurm.query.query_job_status",
            return_value=JobStatus(
                run_state=RunState.COMPLETED, slurm_state="COMPLETED"
            ),
        ),
    ):
        result = runner.invoke(app, ["runs", "sync", str(survey)])

    assert result.exit_code == 0, result.output
    # The second run gets sync'd, the first is skipped silently.
    assert "R20260327-0002" in result.output
    # First run's id should not show up — its sync was skipped.
    # (It may still appear elsewhere in path strings, so check the
    #  state-change output specifically.)
    assert "R20260327-0001:" not in result.output


def test_sync_multi_run_arguments(tmp_path: Path) -> None:
    """Passing multiple run paths processes each one."""
    create_minimal_project(tmp_path, name="test")
    run1 = tmp_path / "runs" / "R20260327-0001"
    run2 = tmp_path / "runs" / "R20260327-0002"
    create_run_manifest(run1, run_id="R20260327-0001", status="running", job_id="11111")
    create_run_manifest(run2, run_id="R20260327-0002", status="running", job_id="22222")

    with (
        patch("runops.cli.status.Path.cwd", return_value=tmp_path),
        patch(
            "runops.slurm.query.query_job_status",
            return_value=JobStatus(
                run_state=RunState.COMPLETED, slurm_state="COMPLETED"
            ),
        ),
    ):
        result = runner.invoke(app, ["runs", "sync", str(run1), str(run2)])

    assert result.exit_code == 0
    assert "R20260327-0001" in result.output
    assert "R20260327-0002" in result.output


def test_sync_bulk_skips_terminal_states(tmp_path: Path) -> None:
    """In multi-target mode, completed/failed/cancelled runs are skipped silently.

    Without this skip, ``sync_run_action`` raises a precondition_failed
    error for terminal states (it only accepts submitted/running) and
    ``runops runs sync runs/`` would error out the moment any run in the
    survey has finished — exactly the wrong behaviour for monitoring a
    long survey.
    """
    create_minimal_project(tmp_path, name="test")
    survey = tmp_path / "runs" / "series_x"
    create_run_manifest(
        survey / "R20260327-0001",
        run_id="R20260327-0001",
        status="completed",
        job_id="11111",
    )
    create_run_manifest(
        survey / "R20260327-0002",
        run_id="R20260327-0002",
        status="running",
        job_id="22222",
    )
    create_run_manifest(
        survey / "R20260327-0003",
        run_id="R20260327-0003",
        status="failed",
        job_id="33333",
    )

    with (
        patch("runops.cli.status.Path.cwd", return_value=tmp_path),
        patch(
            "runops.slurm.query.query_job_status",
            return_value=JobStatus(
                run_state=RunState.COMPLETED, slurm_state="COMPLETED"
            ),
        ),
    ):
        result = runner.invoke(app, ["runs", "sync", str(survey)])

    assert result.exit_code == 0, result.output
    # Only the running run goes through the sync action.
    assert "R20260327-0002" in result.output
    # The completed and failed runs are skipped silently — their lines
    # should not appear as state-change records.
    assert "R20260327-0001:" not in result.output
    assert "R20260327-0003:" not in result.output


def test_sync_single_terminal_run_reports_skip(tmp_path: Path) -> None:
    """Single-target sync of a terminal run prints a skip notice (no error)."""
    create_minimal_project(tmp_path, name="test")
    run_dir = tmp_path / "runs" / "R20260327-0001"
    create_run_manifest(run_dir, status="completed", job_id="11111")

    with patch("runops.cli.status.Path.cwd", return_value=tmp_path):
        result = runner.invoke(app, ["runs", "sync", str(run_dir)])

    assert result.exit_code == 0
    assert "completed" in result.output
    assert "nothing to sync" in result.output


def test_status_multi_run_arguments(tmp_path: Path) -> None:
    """Status accepts multiple targets and prints each."""
    create_minimal_project(tmp_path, name="test")
    run1 = tmp_path / "runs" / "R20260327-0001"
    run2 = tmp_path / "runs" / "R20260327-0002"
    create_run_manifest(run1, run_id="R20260327-0001", status="running", job_id="11111")
    create_run_manifest(run2, run_id="R20260327-0002", status="running", job_id="22222")

    with (
        patch("runops.cli.status.Path.cwd", return_value=tmp_path),
        patch(
            "runops.cli.status.query_job_status",
            return_value=JobStatus(run_state=RunState.RUNNING, slurm_state="RUNNING"),
        ),
    ):
        result = runner.invoke(app, ["runs", "status", str(run1), str(run2)])

    assert result.exit_code == 0
    assert "R20260327-0001" in result.output
    assert "R20260327-0002" in result.output
