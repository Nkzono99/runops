"""Tests for runops runs archive / purge-work / cancel / delete commands."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
import tomli_w
from typer.testing import CliRunner

from runops.cli.main import app

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

runner = CliRunner()


def _create_run(
    parent: Path,
    run_id: str,
    *,
    status: str = "completed",
    job_id: str = "",
) -> Path:
    """Create a minimal run directory with manifest.toml."""
    run_dir = parent / run_id
    run_dir.mkdir(parents=True)
    for sub in ("input", "submit", "work", "analysis", "status"):
        (run_dir / sub).mkdir()

    manifest: dict[str, Any] = {
        "run": {
            "id": run_id,
            "display_name": "test run",
            "status": status,
        },
    }
    if job_id:
        manifest["job"] = {"job_id": job_id}
    with open(run_dir / "manifest.toml", "wb") as f:
        tomli_w.dump(manifest, f)
    return run_dir


def _read_manifest(path: Path) -> dict[str, Any]:
    with open(path / "manifest.toml", "rb") as f:
        return tomllib.load(f)


class TestArchive:
    def test_archive_completed_run(self, tmp_path: Path) -> None:
        run_dir = _create_run(tmp_path, "R20260327-0001", status="completed")
        archived_dir = tmp_path / "_archive" / "R20260327-0001"

        result = runner.invoke(app, ["runs", "archive", "--yes", str(run_dir)])
        assert result.exit_code == 0
        assert "Archived run R20260327-0001" in result.output
        assert "Moved:" in result.output
        assert not run_dir.exists()
        assert archived_dir.exists()

    def test_archive_verifies_manifest_state(self, tmp_path: Path) -> None:
        """After archive, manifest should show 'archived' status."""
        run_dir = _create_run(tmp_path, "R20260327-0001", status="completed")
        archived_dir = tmp_path / "_archive" / "R20260327-0001"

        result = runner.invoke(app, ["runs", "archive", "--yes", str(run_dir)])
        assert result.exit_code == 0

        data = _read_manifest(archived_dir)
        assert data["run"]["status"] == "archived"
        assert data["path"]["run_dir"] == str(archived_dir.resolve())
        assert data["path"]["archived_from"] == str(run_dir.resolve())

    def test_archive_keep_in_place(self, tmp_path: Path) -> None:
        run_dir = _create_run(tmp_path, "R20260327-0001", status="completed")

        result = runner.invoke(
            app,
            ["runs", "archive", "--yes", "--keep-in-place", str(run_dir)],
        )

        assert result.exit_code == 0, result.output
        assert "Path:" in result.output
        assert "Moved:" not in result.output
        assert run_dir.exists()
        data = _read_manifest(run_dir)
        assert data["run"]["status"] == "archived"

    def test_archive_move_to_custom_root(self, tmp_path: Path) -> None:
        run_dir = _create_run(tmp_path, "R20260327-0001", status="completed")
        archive_root = tmp_path / "runs" / "_archive_2026"
        archived_dir = archive_root / "R20260327-0001"

        result = runner.invoke(
            app,
            [
                "runs",
                "archive",
                "--yes",
                "--move-to",
                str(archive_root),
                str(run_dir),
            ],
        )

        assert result.exit_code == 0, result.output
        assert not run_dir.exists()
        assert archived_dir.exists()
        data = _read_manifest(archived_dir)
        assert data["run"]["status"] == "archived"

    def test_archive_cancelled_without_confirmation(self, tmp_path: Path) -> None:
        run_dir = _create_run(tmp_path, "R20260327-0001", status="completed")

        result = runner.invoke(app, ["runs", "archive", str(run_dir)], input="n\n")
        assert result.exit_code == 0
        assert "Cancelled." in result.output

        from runops.core.manifest import read_manifest

        manifest = read_manifest(run_dir)
        assert manifest.run["status"] == "completed"

    def test_archive_rejects_non_completed(self, tmp_path: Path) -> None:
        run_dir = _create_run(tmp_path, "R20260327-0001", status="created")

        result = runner.invoke(app, ["runs", "archive", str(run_dir)])
        assert result.exit_code == 1
        assert "completed" in result.output.lower()

    def test_archive_rejects_failed(self, tmp_path: Path) -> None:
        run_dir = _create_run(tmp_path, "R20260327-0001", status="failed")

        result = runner.invoke(app, ["runs", "archive", str(run_dir)])
        assert result.exit_code == 1

    def test_archive_nonexistent_run(self) -> None:
        result = runner.invoke(app, ["runs", "archive", "/nonexistent/run"])
        assert result.exit_code == 1
        assert "Error" in result.output

    def test_archive_preserves_project_relative_path_and_run_id_lookup(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Default relocation keeps the path below runs/_archive discoverable."""
        (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
        run_dir = _create_run(
            tmp_path / "runs" / "scan",
            "R20260327-0001",
            status="completed",
        )
        archived_dir = tmp_path / "runs" / "_archive" / "scan" / "R20260327-0001"
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["runs", "archive", "--yes", "R20260327-0001"])

        assert result.exit_code == 0, result.output
        assert not run_dir.exists()
        assert archived_dir.exists()

        status = runner.invoke(app, ["runs", "status", "R20260327-0001"])
        assert status.exit_code == 0, status.output
        assert "archived" in status.output

    def test_archive_directory_archives_completed_runs_and_skips_others(
        self, tmp_path: Path
    ) -> None:
        survey_dir = tmp_path / "runs" / "scan"
        completed = _create_run(
            survey_dir,
            "R20260327-0001",
            status="completed",
        )
        created = _create_run(survey_dir, "R20260327-0002", status="created")

        result = runner.invoke(app, ["runs", "archive", "--yes", str(survey_dir)])

        archived = survey_dir / "_archive" / "R20260327-0001"
        assert result.exit_code == 0, result.output
        assert not completed.exists()
        assert archived.exists()
        assert created.exists()
        assert "Skipped 1 run(s)" in result.output


class TestPurgeWork:
    def test_purge_archived_run(self, tmp_path: Path) -> None:
        run_dir = _create_run(tmp_path, "R20260327-0001", status="archived")

        # Create work subdirectories with files
        for dirname in ("outputs", "restart", "tmp"):
            d = run_dir / "work" / dirname
            d.mkdir()
            (d / "data.bin").write_bytes(b"x" * 1024)

        result = runner.invoke(app, ["runs", "purge-work", "--yes", str(run_dir)])
        assert result.exit_code == 0
        assert "Purged work files" in result.output
        assert "Freed" in result.output

        # Verify directories are removed
        assert not (run_dir / "work" / "outputs").exists()
        assert not (run_dir / "work" / "restart").exists()
        assert not (run_dir / "work" / "tmp").exists()
        # work/ itself should still exist
        assert (run_dir / "work").exists()

    def test_purge_updates_state(self, tmp_path: Path) -> None:
        import sys

        if sys.version_info >= (3, 11):
            import tomllib
        else:
            import tomli as tomllib

        run_dir = _create_run(tmp_path, "R20260327-0001", status="archived")

        result = runner.invoke(app, ["runs", "purge-work", "--yes", str(run_dir)])
        assert result.exit_code == 0

        with open(run_dir / "manifest.toml", "rb") as f:
            data = tomllib.load(f)
        assert data["run"]["status"] == "purged"

    def test_purge_cancelled_without_confirmation(self, tmp_path: Path) -> None:
        run_dir = _create_run(tmp_path, "R20260327-0001", status="archived")

        work_outputs = run_dir / "work" / "outputs"
        work_outputs.mkdir()
        (work_outputs / "data.bin").write_bytes(b"x" * 1024)

        result = runner.invoke(
            app,
            ["runs", "purge-work", str(run_dir)],
            input="n\n",
        )
        assert result.exit_code == 0
        assert "Cancelled." in result.output
        assert work_outputs.exists()

        from runops.core.manifest import read_manifest

        manifest = read_manifest(run_dir)
        assert manifest.run["status"] == "archived"

    def test_purge_rejects_non_archived(self, tmp_path: Path) -> None:
        run_dir = _create_run(tmp_path, "R20260327-0001", status="completed")

        result = runner.invoke(app, ["runs", "purge-work", str(run_dir)])
        assert result.exit_code == 1
        assert "archived" in result.output.lower()

    def test_purge_nonexistent_run(self) -> None:
        result = runner.invoke(app, ["runs", "purge-work", "/nonexistent/run"])
        assert result.exit_code == 1
        assert "Error" in result.output

    def test_purge_no_work_dirs(self, tmp_path: Path) -> None:
        """Purge succeeds even if work subdirectories don't exist."""
        run_dir = _create_run(tmp_path, "R20260327-0001", status="archived")

        result = runner.invoke(app, ["runs", "purge-work", "--yes", str(run_dir)])
        assert result.exit_code == 0
        assert "Freed: 0.0 B" in result.output


class TestDelete:
    """Tests for `runops runs delete`."""

    @pytest.mark.parametrize("status", ["created", "cancelled", "failed"])
    def test_delete_terminal_run_removes_directory(
        self, tmp_path: Path, status: str
    ) -> None:
        """Created/cancelled/failed runs can be deleted."""
        run_dir = _create_run(tmp_path, "R20260327-0001", status=status)
        assert run_dir.exists()

        result = runner.invoke(app, ["runs", "delete", "--yes", str(run_dir)])
        assert result.exit_code == 0, result.output
        assert "Deleted run R20260327-0001" in result.output
        assert not run_dir.exists()

    @pytest.mark.parametrize(
        "status", ["submitted", "running", "completed", "archived"]
    )
    def test_delete_rejects_non_terminal_or_completed(
        self, tmp_path: Path, status: str
    ) -> None:
        """Live or valuable runs are protected from accidental deletion."""
        run_dir = _create_run(tmp_path, "R20260327-0001", status=status)

        result = runner.invoke(app, ["runs", "delete", "--yes", str(run_dir)])
        assert result.exit_code == 1
        assert run_dir.exists()  # not removed

    def test_delete_cancelled_without_confirmation(self, tmp_path: Path) -> None:
        """User can decline the confirmation prompt."""
        run_dir = _create_run(tmp_path, "R20260327-0001", status="cancelled")

        result = runner.invoke(app, ["runs", "delete", str(run_dir)], input="n\n")
        assert result.exit_code == 0
        assert "Cancelled." in result.output
        assert run_dir.exists()  # still there

    def test_delete_nonexistent_run(self) -> None:
        result = runner.invoke(app, ["runs", "delete", "/nonexistent/run"])
        assert result.exit_code == 1

    def test_delete_resolves_run_id_from_project_subdirectory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """run_id lookup should work project-wide, not only under cwd."""
        (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
        run_dir = _create_run(
            tmp_path / "runs",
            "R20260327-0001",
            status="failed",
        )
        nested = tmp_path / "cases" / "example"
        nested.mkdir(parents=True)
        monkeypatch.chdir(nested)

        result = runner.invoke(app, ["runs", "delete", "--yes", "R20260327-0001"])

        assert result.exit_code == 0, result.output
        assert "Deleted run R20260327-0001" in result.output
        assert not run_dir.exists()


class TestCancel:
    """Tests for `runops runs cancel`."""

    def test_cancel_requires_active_state(self, tmp_path: Path) -> None:
        run_dir = _create_run(
            tmp_path, "R20260327-0001", status="completed", job_id="12345"
        )
        result = runner.invoke(app, ["runs", "cancel", "--yes", str(run_dir)])
        assert result.exit_code == 1
        assert "submitted/running" in result.output.lower()

    def test_cancel_requires_job_id(self, tmp_path: Path) -> None:
        run_dir = _create_run(tmp_path, "R20260327-0001", status="submitted")
        result = runner.invoke(app, ["runs", "cancel", "--yes", str(run_dir)])
        assert result.exit_code == 1
        assert "job_id" in result.output.lower()

    def test_cancel_running_calls_scancel(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`runs cancel` invokes scancel and then sync."""
        from runops.application import actions
        from runops.slurm import submit as slurm_submit
        from runops.slurm.submit import CommandResult

        run_dir = _create_run(
            tmp_path, "R20260327-0001", status="running", job_id="98765"
        )

        scancel_calls: list[list[str]] = []

        def fake_runner(cmd: list[str]) -> CommandResult:
            scancel_calls.append(cmd)
            return CommandResult(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(slurm_submit, "_default_runner", fake_runner)

        # Stub sync_run so we don't actually talk to Slurm.
        from runops.application.actions import ActionResult, ActionStatus

        def fake_sync(rd: Path) -> ActionResult:
            return ActionResult(
                action="sync_run",
                status=ActionStatus.SUCCESS,
                message="State: running -> cancelled",
                data={"slurm_state": "CANCELLED"},
                state_before="running",
                state_after="cancelled",
            )

        monkeypatch.setattr(actions, "sync_run", fake_sync)

        result = runner.invoke(app, ["runs", "cancel", "--yes", str(run_dir)])
        assert result.exit_code == 0, result.output
        assert any(cmd[:2] == ["scancel", "98765"] for cmd in scancel_calls)
        assert "running -> cancelled" in result.output

    def test_cancel_declined(self, tmp_path: Path) -> None:
        run_dir = _create_run(
            tmp_path, "R20260327-0001", status="running", job_id="98765"
        )
        result = runner.invoke(app, ["runs", "cancel", str(run_dir)], input="n\n")
        assert result.exit_code == 0
        assert "Cancelled." in result.output

    def test_cancel_multiple_runs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`runs cancel` accepts multiple run arguments and cancels each."""
        from runops.application import actions
        from runops.application.actions import ActionResult, ActionStatus

        (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
        r1 = _create_run(tmp_path, "R20260327-0001", status="running", job_id="100")
        r2 = _create_run(tmp_path, "R20260327-0002", status="submitted", job_id="101")
        # A run that should be skipped (already completed)
        _create_run(tmp_path, "R20260327-0003", status="completed", job_id="102")

        cancel_calls: list[Path] = []

        def fake_cancel(rd: Path) -> ActionResult:
            cancel_calls.append(rd)
            return ActionResult(
                action="cancel_run",
                status=ActionStatus.SUCCESS,
                message="cancelled",
                data={},
                state_before="running",
                state_after="cancelled",
            )

        monkeypatch.setattr(actions, "cancel_run", fake_cancel)
        monkeypatch.setattr("runops.cli.manage.cancel_run_action", fake_cancel)

        result = runner.invoke(
            app,
            ["runs", "cancel", "--yes", str(r1), str(r2)],
        )
        assert result.exit_code == 0, result.output
        assert len(cancel_calls) == 2

    def test_cancel_survey_dir_skips_non_active(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Passing a survey dir cancels only submitted/running runs."""
        from runops.application import actions
        from runops.application.actions import ActionResult, ActionStatus

        (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
        survey = tmp_path / "runs" / "series_A"
        _create_run(survey, "R20260327-0001", status="running", job_id="100")
        _create_run(survey, "R20260327-0002", status="completed", job_id="101")

        def fake_cancel(rd: Path) -> ActionResult:
            return ActionResult(
                action="cancel_run",
                status=ActionStatus.SUCCESS,
                message="cancelled",
                data={},
                state_before="running",
                state_after="cancelled",
            )

        monkeypatch.setattr(actions, "cancel_run", fake_cancel)
        monkeypatch.setattr("runops.cli.manage.cancel_run_action", fake_cancel)

        result = runner.invoke(app, ["runs", "cancel", "--yes", str(survey)])
        assert result.exit_code == 0, result.output
        assert "R20260327-0001" in result.output
        assert "Skipped 1 run" in result.output
