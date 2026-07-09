"""Tests for `runops runs dashboard`."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from runops.cli.main import app
from tests.factories import create_minimal_project, create_run_manifest

if TYPE_CHECKING:
    import pytest

runner = CliRunner()


def _create_dashboard_run(
    runs_dir: Path,
    run_id: str,
    *,
    status: str,
    job_id: str = "",
    display_name: str = "",
    simulator_name: str = "fake_sim",
    adapter: str = "fake_sim",
    last_slurm_state: str = "",
) -> Path:
    """Create a minimal dashboard run under ``runs_dir``."""
    return create_run_manifest(
        runs_dir / run_id,
        run_id=run_id,
        status=status,
        job_id=job_id,
        display_name=display_name or None,
        simulator_name=simulator_name,
        adapter=adapter,
        last_slurm_state=last_slurm_state,
    )


class TestDashboard:
    """Tests for the basic (non-watch) dashboard command."""

    def test_dashboard_lists_active_runs(self, tmp_path: Path) -> None:
        project_dir = create_minimal_project(tmp_path)
        survey = project_dir / "runs" / "series_x"
        _create_dashboard_run(
            survey,
            "R20260327-0001",
            status="running",
            job_id="11111",
            last_slurm_state="RUNNING",
        )
        _create_dashboard_run(
            survey,
            "R20260327-0002",
            status="completed",
            job_id="22222",
        )

        result = runner.invoke(app, ["runs", "dashboard", str(survey)])
        assert result.exit_code == 0, result.output
        # Active runs are shown by default; completed runs are hidden.
        assert "R20260327-0001" in result.output
        assert "R20260327-0002" not in result.output

    def test_dashboard_all_includes_completed(self, tmp_path: Path) -> None:
        project_dir = create_minimal_project(tmp_path)
        survey = project_dir / "runs" / "series_x"
        _create_dashboard_run(
            survey, "R20260327-0001", status="completed", job_id="11111"
        )

        result = runner.invoke(app, ["runs", "dashboard", "--all", str(survey)])
        assert result.exit_code == 0
        assert "R20260327-0001" in result.output
        assert "completed" in result.output

    def test_dashboard_no_active_runs(self, tmp_path: Path) -> None:
        project_dir = create_minimal_project(tmp_path)
        survey = project_dir / "runs" / "series_x"
        _create_dashboard_run(
            survey, "R20260327-0001", status="completed", job_id="11111"
        )

        result = runner.invoke(app, ["runs", "dashboard", str(survey)])
        assert result.exit_code == 0
        assert "No active runs" in result.output

    def test_dashboard_includes_state_column(self, tmp_path: Path) -> None:
        project_dir = create_minimal_project(tmp_path)
        survey = project_dir / "runs" / "series_x"
        _create_dashboard_run(
            survey,
            "R20260327-0001",
            status="running",
            job_id="11111",
            last_slurm_state="RUNNING",
        )

        result = runner.invoke(app, ["runs", "dashboard", str(survey)])
        assert result.exit_code == 0
        # Header row contains the expected columns.
        assert "RUN_ID" in result.output
        assert "STATE" in result.output
        assert "STEP" in result.output
        assert "%" in result.output
        assert "SLURM" in result.output

    def test_dashboard_hides_terminal_slurm_state_for_active_run(
        self,
        tmp_path: Path,
    ) -> None:
        project_dir = create_minimal_project(tmp_path)
        survey = project_dir / "runs" / "series_x"
        _create_dashboard_run(
            survey,
            "R20260327-0001",
            status="submitted",
            job_id="33333",
            last_slurm_state="COMPLETED",
        )

        result = runner.invoke(app, ["runs", "dashboard", str(survey)])

        assert result.exit_code == 0
        assert "R20260327-0001" in result.output
        assert "COMPLETED" not in result.output

    def test_dashboard_shows_beach_stdout_batch_progress(
        self,
        tmp_path: Path,
    ) -> None:
        project_dir = create_minimal_project(tmp_path)
        survey = project_dir / "runs" / "series_x"
        run_dir = _create_dashboard_run(
            survey,
            "R20260327-0001",
            status="running",
            job_id="11111",
            last_slurm_state="RUNNING",
            simulator_name="beach",
            adapter="beach",
        )
        work_dir = run_dir / "work"
        work_dir.mkdir()
        (work_dir / "stdout.11111.log").write_text(
            "---------- batch 170490/280000 rel_change=1.9e-6 ----------\n",
            encoding="utf-8",
        )

        result = runner.invoke(app, ["runs", "dashboard", str(survey)])

        assert result.exit_code == 0, result.output
        assert "170490/280000" in result.output
        assert " 60.9%" in result.output


class TestDashboardWatch:
    """Tests for the --watch refresh loop."""

    def test_watch_refreshes_then_stops(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from runops.cli import dashboard as dashboard_cli

        project_dir = create_minimal_project(tmp_path)
        survey = project_dir / "runs" / "series_x"
        _create_dashboard_run(
            survey, "R20260327-0001", status="running", job_id="11111"
        )

        call_count = {"n": 0}

        def fake_print(run_dirs: list[Path], *, all_states: bool) -> None:
            call_count["n"] += 1
            dashboard_cli.typer.echo(f"call {call_count['n']}")

        def fake_sleep(seconds: float) -> None:
            if call_count["n"] >= 2:
                raise KeyboardInterrupt

        monkeypatch.setattr(dashboard_cli, "_print_dashboard", fake_print)
        monkeypatch.setattr(dashboard_cli.time, "sleep", fake_sleep)

        result = runner.invoke(
            app, ["runs", "dashboard", "--watch", "0.01", str(survey)]
        )
        assert result.exit_code == 0
        assert call_count["n"] >= 2
        assert "Stopped." in result.output
