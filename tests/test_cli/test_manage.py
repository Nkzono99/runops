"""Tests for runops runs archive / restore / purge-work / cancel / delete."""

from __future__ import annotations

import shutil
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
        assert data["path"]["run_dir"] == str(run_dir.resolve())
        assert data["path"]["archived_from"] == str(run_dir.resolve())

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

    def test_archive_same_cli_command_resumes_after_move_interruption(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from runops.application.actions import admin as admin_module

        (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
        run_dir = _create_run(
            tmp_path / "runs" / "scan",
            "R20260327-0010",
            status="completed",
        )
        archived_dir = tmp_path / "runs" / "_archive" / "scan" / run_dir.name
        monkeypatch.chdir(tmp_path)
        real_move = admin_module.move_directory_noreplace

        def interrupt_after_move(source: Path, destination: Path) -> Any:
            real_move(source, destination)
            raise KeyboardInterrupt("injected after archive move")

        monkeypatch.setattr(
            admin_module,
            "move_directory_noreplace",
            interrupt_after_move,
        )
        command = ["runs", "archive", "--yes", "runs/scan/R20260327-0010"]

        interrupted = runner.invoke(app, command)

        assert interrupted.exit_code != 0
        assert not run_dir.exists()
        assert archived_dir.is_dir()
        assert list((tmp_path / ".runops" / "lifecycle").glob("archive_run-*.json"))
        monkeypatch.undo()
        monkeypatch.chdir(tmp_path)

        resumed = runner.invoke(app, command)

        assert resumed.exit_code == 0, resumed.output
        assert "Archived run R20260327-0010" in resumed.output
        assert _read_manifest(archived_dir)["run"]["status"] == "archived"
        assert not list((tmp_path / ".runops" / "lifecycle").glob("archive_run-*.json"))

    def test_archive_run_id_resumes_after_move_interruption(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from runops.application.actions import admin as admin_module

        (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
        run_id = "R20260327-0015"
        run_dir = _create_run(
            tmp_path / "runs" / "scan",
            run_id,
            status="completed",
        )
        archived_dir = tmp_path / "runs" / "_archive" / "scan" / run_id
        monkeypatch.chdir(tmp_path)
        real_move = admin_module.move_directory_noreplace

        def interrupt_after_move(source: Path, destination: Path) -> Any:
            real_move(source, destination)
            raise KeyboardInterrupt("injected after archive move")

        monkeypatch.setattr(
            admin_module,
            "move_directory_noreplace",
            interrupt_after_move,
        )
        command = ["runs", "archive", "--yes", run_id]

        interrupted = runner.invoke(app, command)

        assert interrupted.exit_code != 0
        assert not run_dir.exists()
        assert archived_dir.is_dir()
        assert list((tmp_path / ".runops" / "lifecycle").glob("archive_run-*.json"))
        monkeypatch.undo()
        monkeypatch.chdir(tmp_path)

        resumed = runner.invoke(app, command)

        assert resumed.exit_code == 0, resumed.output
        assert "Archived run R20260327-0015" in resumed.output
        assert _read_manifest(archived_dir)["run"]["status"] == "archived"
        assert not list((tmp_path / ".runops" / "lifecycle").glob("archive_run-*.json"))

    @pytest.mark.parametrize("selection", ["directory", "all"])
    def test_archive_bulk_resumes_moved_run_before_archiving_remaining_runs(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        selection: str,
    ) -> None:
        from runops.application.actions import admin as admin_module

        (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
        survey_dir = tmp_path / "runs" / "scan"
        first = _create_run(survey_dir, "R20260327-0016", status="completed")
        second = _create_run(survey_dir, "R20260327-0017", status="completed")
        first_archived = tmp_path / "runs" / "_archive" / "scan" / first.name
        second_archived = tmp_path / "runs" / "_archive" / "scan" / second.name
        monkeypatch.chdir(tmp_path)
        real_move = admin_module.move_directory_noreplace
        interrupted_once = False

        def interrupt_after_first_move(source: Path, destination: Path) -> Any:
            nonlocal interrupted_once
            real_move(source, destination)
            if not interrupted_once:
                interrupted_once = True
                raise KeyboardInterrupt("injected after first archive move")

        monkeypatch.setattr(
            admin_module,
            "move_directory_noreplace",
            interrupt_after_first_move,
        )
        command = (
            ["runs", "archive", "--yes", "runs/scan"]
            if selection == "directory"
            else ["runs", "archive", "--yes", "--all"]
        )

        interrupted = runner.invoke(app, command)

        assert interrupted.exit_code != 0
        assert first_archived.is_dir()
        assert second.is_dir()
        assert list((tmp_path / ".runops" / "lifecycle").glob("archive_run-*.json"))
        monkeypatch.undo()
        monkeypatch.chdir(tmp_path)

        resumed = runner.invoke(app, command)

        assert resumed.exit_code == 0, resumed.output
        assert not first.exists()
        assert not second.exists()
        assert first_archived.is_dir()
        assert second_archived.is_dir()
        assert _read_manifest(first_archived)["run"]["status"] == "archived"
        assert _read_manifest(second_archived)["run"]["status"] == "archived"
        assert not list((tmp_path / ".runops" / "lifecycle").glob("archive_run-*.json"))

    def test_archive_all_uses_only_canonical_active_run_tree(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
        active = _create_run(
            tmp_path / "runs" / "scan",
            "R20260327-0025",
            status="completed",
        )
        result_dir = tmp_path / "research" / "results" / "R0001-summary"
        result_dir.mkdir(parents=True)
        with (result_dir / "manifest.toml").open("wb") as stream:
            tomli_w.dump(
                {
                    "result": {
                        "id": "R0001-summary",
                        "status": "draft",
                        "title": "Not a formal Run",
                    }
                },
                stream,
            )
        cold_bundle = tmp_path / "runs" / "_archive" / "old-scan"
        cold = _create_run(
            cold_bundle,
            "R20260327-0026",
            status="completed",
        )
        with (cold_bundle / ".runops-archive.toml").open("wb") as stream:
            tomli_w.dump(
                {
                    "bundle": {
                        "format_version": 1,
                        "archived_from": str(tmp_path / "runs" / "old-scan"),
                        "run_count": 1,
                    }
                },
                stream,
            )
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["runs", "archive", "--yes", "--all"])

        assert result.exit_code == 0, result.output
        archived = tmp_path / "runs" / "_archive" / "scan" / active.name
        assert archived.is_dir()
        assert _read_manifest(archived)["run"]["status"] == "archived"
        assert cold.is_dir()
        assert _read_manifest(cold)["run"]["status"] == "completed"
        assert (result_dir / "manifest.toml").is_file()

    def test_archive_rejects_explicit_completed_child_inside_cold_bundle(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
        cold_bundle = tmp_path / "runs" / "_archive" / "old-scan"
        cold = _create_run(
            cold_bundle,
            "R20260327-0027",
            status="completed",
        )
        with (cold_bundle / ".runops-archive.toml").open("wb") as stream:
            tomli_w.dump(
                {
                    "bundle": {
                        "format_version": 1,
                        "archived_from": str(tmp_path / "runs" / "old-scan"),
                        "run_count": 1,
                    }
                },
                stream,
            )
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["runs", "archive", "--yes", str(cold)])

        assert result.exit_code == 1
        assert "not a unique active formal Run" in result.output
        assert _read_manifest(cold)["run"]["status"] == "completed"

    def test_archive_run_id_recovery_fails_closed_on_tampered_receipt(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import json

        from runops.application.actions import admin as admin_module

        (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
        run_id = "R20260327-0018"
        run_dir = _create_run(
            tmp_path / "runs" / "scan",
            run_id,
            status="completed",
        )
        archived_dir = tmp_path / "runs" / "_archive" / "scan" / run_id
        monkeypatch.chdir(tmp_path)
        real_move = admin_module.move_directory_noreplace

        def interrupt_after_move(source: Path, destination: Path) -> Any:
            real_move(source, destination)
            raise KeyboardInterrupt("injected after archive move")

        monkeypatch.setattr(
            admin_module,
            "move_directory_noreplace",
            interrupt_after_move,
        )
        interrupted = runner.invoke(app, ["runs", "archive", "--yes", run_id])
        assert interrupted.exit_code != 0
        receipt = next((tmp_path / ".runops" / "lifecycle").glob("archive_run-*.json"))
        payload = json.loads(receipt.read_text())
        payload["run_id"] = "R20260327-9999"
        receipt.write_text(json.dumps(payload) + "\n")
        monkeypatch.undo()
        monkeypatch.chdir(tmp_path)

        resumed = runner.invoke(app, ["runs", "archive", "--yes", run_id])

        assert resumed.exit_code == 1
        assert "cannot inspect archive recovery" in resumed.output
        assert not run_dir.exists()
        assert archived_dir.is_dir()
        assert receipt.is_file()

    def test_archive_run_id_recovery_rejects_ambiguous_receipts(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from runops.application.actions import admin as admin_module

        (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
        run_id = "R20260327-0019"
        first = _create_run(
            tmp_path / "runs" / "scan-a",
            run_id,
            status="completed",
        )
        second = _create_run(
            tmp_path / "runs" / "scan-b",
            run_id,
            status="completed",
        )
        monkeypatch.chdir(tmp_path)
        real_move = admin_module.move_directory_noreplace

        def interrupt_after_move(source: Path, destination: Path) -> Any:
            real_move(source, destination)
            raise KeyboardInterrupt("injected after archive move")

        monkeypatch.setattr(
            admin_module,
            "move_directory_noreplace",
            interrupt_after_move,
        )
        for run_dir in (first, second):
            interrupted = runner.invoke(
                app,
                ["runs", "archive", "--yes", str(run_dir)],
            )
            assert interrupted.exit_code != 0
        monkeypatch.undo()
        monkeypatch.chdir(tmp_path)

        resumed = runner.invoke(app, ["runs", "archive", "--yes", run_id])

        assert resumed.exit_code == 1
        assert "multiple pending archive recoveries" in resumed.output
        assert (
            len(list((tmp_path / ".runops" / "lifecycle").glob("archive_run-*.json")))
            == 2
        )

    def test_archive_run_id_recovery_rejects_duplicate_live_run_id(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from runops.application.actions import admin as admin_module

        (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
        run_id = "R20260327-0024"
        source = _create_run(
            tmp_path / "runs" / "scan-a",
            run_id,
            status="completed",
        )
        monkeypatch.chdir(tmp_path)
        real_move = admin_module.move_directory_noreplace

        def interrupt_after_move(move_source: Path, destination: Path) -> Any:
            real_move(move_source, destination)
            raise KeyboardInterrupt("injected after archive move")

        monkeypatch.setattr(
            admin_module,
            "move_directory_noreplace",
            interrupt_after_move,
        )
        interrupted = runner.invoke(
            app,
            ["runs", "archive", "--yes", str(source)],
        )
        assert interrupted.exit_code != 0
        monkeypatch.undo()
        monkeypatch.chdir(tmp_path)
        _create_run(
            tmp_path / "runs" / "scan-b",
            run_id,
            status="completed",
        )

        resumed = runner.invoke(app, ["runs", "archive", "--yes", run_id])

        assert resumed.exit_code == 1
        assert "Duplicate Run ID" in resumed.output
        assert list((tmp_path / ".runops" / "lifecycle").glob("archive_run-*.json"))

    def test_archive_run_id_recovery_rejects_ambiguous_topology(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from runops.application.actions import admin as admin_module

        (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
        run_id = "R20260327-0021"
        run_dir = _create_run(
            tmp_path / "runs" / "scan",
            run_id,
            status="completed",
        )
        archived_dir = tmp_path / "runs" / "_archive" / "scan" / run_id
        monkeypatch.chdir(tmp_path)
        real_move = admin_module.move_directory_noreplace

        def interrupt_after_move(source: Path, destination: Path) -> Any:
            real_move(source, destination)
            raise KeyboardInterrupt("injected after archive move")

        monkeypatch.setattr(
            admin_module,
            "move_directory_noreplace",
            interrupt_after_move,
        )
        interrupted = runner.invoke(app, ["runs", "archive", "--yes", run_id])
        assert interrupted.exit_code != 0
        monkeypatch.undo()
        monkeypatch.chdir(tmp_path)
        shutil.copytree(archived_dir, run_dir)

        resumed = runner.invoke(app, ["runs", "archive", "--yes", run_id])

        assert resumed.exit_code == 1
        assert "requires exactly one Run endpoint" in resumed.output
        assert run_dir.is_dir()
        assert archived_dir.is_dir()
        assert list((tmp_path / ".runops" / "lifecycle").glob("archive_run-*.json"))

    def test_archive_directory_recovery_keeps_other_scope_pending(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from runops.application.actions import admin as admin_module

        (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
        first = _create_run(
            tmp_path / "runs" / "scan-a",
            "R20260327-0022",
            status="completed",
        )
        second = _create_run(
            tmp_path / "runs" / "scan-b",
            "R20260327-0023",
            status="completed",
        )
        monkeypatch.chdir(tmp_path)
        real_move = admin_module.move_directory_noreplace

        def interrupt_after_move(source: Path, destination: Path) -> Any:
            real_move(source, destination)
            raise KeyboardInterrupt("injected after archive move")

        monkeypatch.setattr(
            admin_module,
            "move_directory_noreplace",
            interrupt_after_move,
        )
        for run_dir in (first, second):
            interrupted = runner.invoke(
                app,
                ["runs", "archive", "--yes", str(run_dir)],
            )
            assert interrupted.exit_code != 0
        monkeypatch.undo()
        monkeypatch.chdir(tmp_path)

        resumed = runner.invoke(
            app,
            ["runs", "archive", "--yes", "runs/scan-a"],
        )

        assert resumed.exit_code == 0, resumed.output
        first_archived = tmp_path / "runs" / "_archive" / "scan-a" / first.name
        second_archived = tmp_path / "runs" / "_archive" / "scan-b" / second.name
        assert _read_manifest(first_archived)["path"]["archived_from"] == str(first)
        assert "path" not in _read_manifest(second_archived)
        receipts = list((tmp_path / ".runops" / "lifecycle").glob("archive_run-*.json"))
        assert len(receipts) == 1

    def test_archive_recovery_requires_the_same_custom_archive_root(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from runops.application.actions import admin as admin_module

        (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
        run_dir = _create_run(
            tmp_path / "runs" / "scan",
            "R20260327-0011",
            status="completed",
        )
        archive_root = tmp_path / "runs" / "_archive" / "cold"
        archived_dir = archive_root / "scan" / run_dir.name
        monkeypatch.chdir(tmp_path)
        real_move = admin_module.move_directory_noreplace

        def interrupt_after_move(source: Path, destination: Path) -> Any:
            real_move(source, destination)
            raise KeyboardInterrupt("injected after archive move")

        monkeypatch.setattr(
            admin_module,
            "move_directory_noreplace",
            interrupt_after_move,
        )
        command = [
            "runs",
            "archive",
            "--yes",
            "--move-to",
            str(archive_root),
            "runs/scan/R20260327-0011",
        ]
        interrupted = runner.invoke(app, command)
        assert interrupted.exit_code != 0
        monkeypatch.undo()
        monkeypatch.chdir(tmp_path)

        wrong_root = runner.invoke(
            app,
            [
                "runs",
                "archive",
                "--yes",
                "--move-to",
                "runs/_archive/wrong",
                "runs/scan/R20260327-0011",
            ],
        )

        assert wrong_root.exit_code == 1
        assert "destination does not match" in wrong_root.output
        assert archived_dir.is_dir()

        resumed = runner.invoke(app, command)

        assert resumed.exit_code == 0, resumed.output
        assert _read_manifest(archived_dir)["run"]["status"] == "archived"

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

    def test_archive_bundle_moves_parent_with_cancelled_runs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
        survey_dir = tmp_path / "runs" / "scan"
        survey_dir.mkdir(parents=True)
        (survey_dir / "survey.toml").write_text("[survey]\n")
        _create_run(survey_dir, "R20260327-0001", status="completed")
        _create_run(survey_dir, "R20260327-0002", status="cancelled")
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(
            app,
            ["runs", "archive", "--bundle", "--yes", "runs/scan"],
        )

        archived = tmp_path / "runs" / "_archive" / "scan"
        assert result.exit_code == 0, result.output
        assert "Archived bundle scan (2 runs)." in result.output
        assert not survey_dir.exists()
        assert (archived / "survey.toml").is_file()
        assert _read_manifest(archived / "R20260327-0001")["run"]["status"] == (
            "completed"
        )
        assert _read_manifest(archived / "R20260327-0002")["run"]["status"] == (
            "cancelled"
        )

    def test_archive_bundle_rejects_keep_in_place(self, tmp_path: Path) -> None:
        survey_dir = tmp_path / "runs" / "scan"
        _create_run(survey_dir, "R20260327-0001", status="completed")

        result = runner.invoke(
            app,
            [
                "runs",
                "archive",
                "--bundle",
                "--keep-in-place",
                str(survey_dir),
            ],
        )

        assert result.exit_code == 1
        assert "--bundle cannot be used with --keep-in-place" in result.output

    def test_archive_bundle_adopts_previously_archived_run_with_preview(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
        survey_dir = tmp_path / "runs" / "scan"
        survey_dir.mkdir(parents=True)
        (survey_dir / "survey.toml").write_text("[survey]\n")
        archived_run = _create_run(
            survey_dir,
            "R20260327-0001",
            status="completed",
        )
        _create_run(survey_dir, "R20260327-0002", status="cancelled")
        monkeypatch.chdir(tmp_path)
        individual = runner.invoke(
            app,
            ["runs", "archive", "--yes", str(archived_run)],
        )
        assert individual.exit_code == 0, individual.output

        result = runner.invoke(
            app,
            ["runs", "archive", "--bundle", "--adopt-archived", "runs/scan"],
            input="y\n",
        )

        archive_root = tmp_path / "runs" / "_archive" / "scan"
        assert result.exit_code == 0, result.output
        assert "Previously archived runs to adopt:" in result.output
        assert "R20260327-0001 (archived)" in result.output
        assert "Adopted 1 previously archived run." in result.output
        assert (archive_root / "survey.toml").is_file()
        assert (archive_root / "R20260327-0001").is_dir()
        assert (archive_root / "R20260327-0002").is_dir()

    @pytest.mark.parametrize("interrupt_phase", ["move", "transaction_removed"])
    def test_archive_bundle_same_cli_command_resumes_adoption_interruption(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        interrupt_phase: str,
    ) -> None:
        from runops.application.actions import bundle_archive as bundle_module

        (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
        survey_dir = tmp_path / "runs" / "scan"
        survey_dir.mkdir(parents=True)
        (survey_dir / "survey.toml").write_text("[survey]\n")
        adopted = _create_run(
            survey_dir,
            "R20260327-0013",
            status="completed",
        )
        _create_run(survey_dir, "R20260327-0014", status="cancelled")
        monkeypatch.chdir(tmp_path)
        individual = runner.invoke(
            app,
            ["runs", "archive", "--yes", str(adopted)],
        )
        assert individual.exit_code == 0, individual.output
        destination = tmp_path / "runs" / "_archive" / "scan"

        if interrupt_phase == "move":
            real_move = bundle_module.move_directory_noreplace

            def interrupt_after_move(source: Path, target: Path) -> Any:
                real_move(source, target)
                raise KeyboardInterrupt("injected after adoption move")

            monkeypatch.setattr(
                bundle_module,
                "move_directory_noreplace",
                interrupt_after_move,
            )
        else:
            real_fsync = bundle_module._fsync_directory
            interrupted = False

            def interrupt_after_transaction_removal(path: Path) -> None:
                nonlocal interrupted
                transactions = list(
                    destination.parent.glob(f".tmp-adopt-{destination.name}-*")
                )
                if path == destination.parent and not transactions and not interrupted:
                    interrupted = True
                    raise KeyboardInterrupt("injected after transaction removal")
                real_fsync(path)

            monkeypatch.setattr(
                bundle_module,
                "_fsync_directory",
                interrupt_after_transaction_removal,
            )

        command = [
            "runs",
            "archive",
            "--bundle",
            "--adopt-archived",
            "--yes",
            "runs/scan",
        ]
        first = runner.invoke(app, command)

        assert first.exit_code != 0
        if interrupt_phase == "transaction_removed":
            assert not survey_dir.exists()
            assert destination.is_dir()
            assert not list(destination.parent.glob(f".tmp-adopt-{destination.name}-*"))
        else:
            assert list(destination.parent.glob(f".tmp-adopt-{destination.name}-*"))
        monkeypatch.undo()
        monkeypatch.chdir(tmp_path)

        resumed = runner.invoke(app, command)

        assert resumed.exit_code == 0, resumed.output
        assert "Archived bundle scan (2 runs)." in resumed.output
        assert not survey_dir.exists()
        assert (destination / "R20260327-0013").is_dir()
        assert (destination / "R20260327-0014").is_dir()
        assert not list(destination.parent.glob(f".tmp-adopt-{destination.name}-*"))

    def test_adopt_archived_requires_bundle(self, tmp_path: Path) -> None:
        run_dir = _create_run(tmp_path, "R20260327-0001", status="completed")

        result = runner.invoke(
            app,
            ["runs", "archive", "--adopt-archived", str(run_dir)],
        )

        assert result.exit_code == 1
        assert "--adopt-archived requires --bundle" in result.output


class TestRestore:
    def test_restore_archived_run_to_original_location(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
        run_dir = _create_run(
            tmp_path / "runs" / "scan",
            "R20260327-0001",
            status="completed",
        )
        output = run_dir / "work" / "outputs" / "result.dat"
        output.parent.mkdir(parents=True)
        output.write_text("preserved\n")
        monkeypatch.chdir(tmp_path)

        archived = runner.invoke(app, ["runs", "archive", "--yes", "R20260327-0001"])
        assert archived.exit_code == 0, archived.output

        restored = runner.invoke(app, ["runs", "restore", "R20260327-0001"])

        assert restored.exit_code == 0, restored.output
        assert "Restored run R20260327-0001" in restored.output
        assert run_dir.exists()
        assert output.read_text() == "preserved\n"
        assert _read_manifest(run_dir)["run"]["status"] == "completed"

    def test_restore_same_cli_command_resumes_after_move_interruption(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from runops.application.actions import admin as admin_module

        (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
        run_dir = _create_run(
            tmp_path / "runs" / "scan",
            "R20260327-0012",
            status="completed",
        )
        monkeypatch.chdir(tmp_path)
        archived = runner.invoke(
            app,
            ["runs", "archive", "--yes", "runs/scan/R20260327-0012"],
        )
        assert archived.exit_code == 0, archived.output
        archived_dir = tmp_path / "runs" / "_archive" / "scan" / run_dir.name
        real_move = admin_module.move_directory_noreplace

        def interrupt_after_move(source: Path, destination: Path) -> Any:
            real_move(source, destination)
            raise KeyboardInterrupt("injected after restore move")

        monkeypatch.setattr(
            admin_module,
            "move_directory_noreplace",
            interrupt_after_move,
        )
        command = [
            "runs",
            "restore",
            "runs/_archive/scan/R20260327-0012",
        ]

        interrupted = runner.invoke(app, command)

        assert interrupted.exit_code != 0
        assert run_dir.is_dir()
        assert not archived_dir.exists()
        assert list((tmp_path / ".runops" / "lifecycle").glob("restore_run-*.json"))
        monkeypatch.undo()
        monkeypatch.chdir(tmp_path)

        resumed = runner.invoke(app, command)

        assert resumed.exit_code == 0, resumed.output
        assert "Restored run R20260327-0012" in resumed.output
        assert _read_manifest(run_dir)["run"]["status"] == "completed"
        assert not list((tmp_path / ".runops" / "lifecycle").glob("restore_run-*.json"))

    def test_restore_run_id_resumes_after_move_interruption(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from runops.application.actions import admin as admin_module

        (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
        run_id = "R20260327-0020"
        run_dir = _create_run(
            tmp_path / "runs" / "scan",
            run_id,
            status="completed",
        )
        monkeypatch.chdir(tmp_path)
        archived = runner.invoke(app, ["runs", "archive", "--yes", run_id])
        assert archived.exit_code == 0, archived.output
        archived_dir = tmp_path / "runs" / "_archive" / "scan" / run_id
        real_move = admin_module.move_directory_noreplace

        def interrupt_after_move(source: Path, destination: Path) -> Any:
            real_move(source, destination)
            raise KeyboardInterrupt("injected after restore move")

        monkeypatch.setattr(
            admin_module,
            "move_directory_noreplace",
            interrupt_after_move,
        )
        command = ["runs", "restore", run_id]

        interrupted = runner.invoke(app, command)

        assert interrupted.exit_code != 0
        assert run_dir.is_dir()
        assert not archived_dir.exists()
        assert list((tmp_path / ".runops" / "lifecycle").glob("restore_run-*.json"))
        monkeypatch.undo()
        monkeypatch.chdir(tmp_path)

        resumed = runner.invoke(app, command)

        assert resumed.exit_code == 0, resumed.output
        assert "Restored run R20260327-0020" in resumed.output
        assert _read_manifest(run_dir)["run"]["status"] == "completed"
        assert not list((tmp_path / ".runops" / "lifecycle").glob("restore_run-*.json"))

    def test_restore_rejects_non_archived_run(self, tmp_path: Path) -> None:
        run_dir = _create_run(tmp_path, "R20260327-0001", status="completed")

        result = runner.invoke(app, ["runs", "restore", str(run_dir)])

        assert result.exit_code == 1
        assert "archived" in result.output.lower()

    def test_restore_bundle_moves_parent_back(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
        survey_dir = tmp_path / "runs" / "scan"
        survey_dir.mkdir(parents=True)
        (survey_dir / "survey.toml").write_text("[survey]\n")
        _create_run(survey_dir, "R20260327-0001", status="cancelled")
        monkeypatch.chdir(tmp_path)
        archived = runner.invoke(
            app,
            ["runs", "archive", "--bundle", "--yes", "runs/scan"],
        )
        assert archived.exit_code == 0, archived.output

        result = runner.invoke(
            app,
            ["runs", "restore", "--bundle", "runs/_archive/scan"],
        )

        assert result.exit_code == 0, result.output
        assert "Restored bundle scan (1 run)." in result.output
        assert survey_dir.is_dir()
        assert not (tmp_path / "runs" / "_archive" / "scan").exists()


class TestPurgeWork:
    @pytest.mark.parametrize("selector", ["path", "run_id"])
    def test_purge_same_cli_command_resumes_after_manifest_commit_interruption(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        selector: str,
    ) -> None:
        from runops.core import manifest as manifest_module

        (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
        run_id = "R20260327-0020"
        run_dir = _create_run(
            tmp_path / "runs" / "_archive" / "scan",
            run_id,
            status="archived",
        )
        output = run_dir / "work" / "outputs" / "data.bin"
        output.parent.mkdir()
        output.write_bytes(b"committed purge")
        monkeypatch.chdir(tmp_path)
        real_write = manifest_module.write_manifest
        interrupted = False

        def interrupt_after_manifest(path: Path, manifest: Any, **kwargs: Any) -> Any:
            nonlocal interrupted
            result = real_write(path, manifest, **kwargs)
            if not interrupted and manifest.run.get("status") == "purged":
                interrupted = True
                raise KeyboardInterrupt("injected after purge manifest")
            return result

        monkeypatch.setattr(
            manifest_module,
            "write_manifest",
            interrupt_after_manifest,
        )
        target = str(run_dir) if selector == "path" else run_id
        command = [
            "runs",
            "purge-work",
            "--yes",
            "--discard-incomplete",
            "--reason",
            "CLI durable purge recovery fixture.",
            target,
        ]

        first = runner.invoke(app, command)

        assert first.exit_code != 0
        assert interrupted
        assert _read_manifest(run_dir)["run"]["status"] == "purged"
        receipt = run_dir / "status" / ".purge-pending.json"
        assert receipt.is_file()
        monkeypatch.setattr(manifest_module, "write_manifest", real_write)

        resumed = runner.invoke(app, command)

        assert resumed.exit_code == 0, resumed.output
        assert "Purged work files" in resumed.output
        assert not receipt.exists()
        assert not output.exists()

    def test_purge_rejects_purged_run_without_pending_receipt(
        self,
        tmp_path: Path,
    ) -> None:
        run_dir = _create_run(tmp_path, "R20260327-0021", status="purged")

        result = runner.invoke(app, ["runs", "purge-work", "--yes", str(run_dir)])

        assert result.exit_code == 1
        assert "can only purge 'archived' runs" in result.output

    def test_purge_rejects_tampered_pending_receipt(
        self,
        tmp_path: Path,
    ) -> None:
        run_dir = _create_run(tmp_path, "R20260327-0022", status="purged")
        receipt = run_dir / "status" / ".purge-pending.json"
        receipt.write_text('{"schema_version": 1, "run_id": 7}\n')

        result = runner.invoke(app, ["runs", "purge-work", "--yes", str(run_dir)])

        assert result.exit_code == 1
        assert "cannot inspect purge recovery" in result.output
        assert receipt.is_file()

    def test_purge_archived_run(self, tmp_path: Path) -> None:
        run_dir = _create_run(tmp_path, "R20260327-0001", status="archived")

        # Create work subdirectories with files
        for dirname in ("outputs", "restart", "tmp"):
            d = run_dir / "work" / dirname
            d.mkdir()
            (d / "data.bin").write_bytes(b"x" * 1024)

        result = runner.invoke(
            app,
            [
                "runs",
                "purge-work",
                "--yes",
                "--discard-incomplete",
                "--reason",
                "CLI purge fixture has no readiness evidence.",
                str(run_dir),
            ],
        )
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

        result = runner.invoke(
            app,
            [
                "runs",
                "purge-work",
                "--yes",
                "--discard-incomplete",
                "--reason",
                "CLI purge fixture has no readiness evidence.",
                str(run_dir),
            ],
        )
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

        result = runner.invoke(
            app,
            [
                "runs",
                "purge-work",
                "--yes",
                "--discard-incomplete",
                "--reason",
                "CLI purge fixture has no readiness evidence.",
                str(run_dir),
            ],
        )
        assert result.exit_code == 0
        assert "Freed: 0.0 B" in result.output

    def test_purge_incomplete_uses_inline_disposition(self, tmp_path: Path) -> None:
        from runops.application.execution.readiness import (
            probe_run_readiness,
            write_readiness_cache,
        )
        from runops.core.manifest import read_manifest, update_manifest

        run_dir = _create_run(tmp_path, "R20260327-0002", status="completed")
        update_manifest(
            run_dir,
            {
                "job": {"job_id": "12345", "attempt": 1},
                "simulator": {"name": "emses", "adapter": "emses"},
            },
        )
        with (run_dir / "input" / "plasma.toml").open("wb") as stream:
            tomli_w.dump({"jobcon": {"nstep": 100}}, stream)
        (run_dir / "work" / "energy").write_text(
            "100 1.0 2.0\n",
            encoding="utf-8",
        )
        manifest = read_manifest(run_dir)
        write_readiness_cache(
            run_dir,
            probe_run_readiness(run_dir, manifest=manifest),
            manifest=manifest,
        )
        update_manifest(run_dir, {"run": {"status": "archived"}})
        (run_dir / "work" / "outputs").mkdir()

        blocked = runner.invoke(
            app,
            ["runs", "purge-work", "--yes", str(run_dir)],
        )

        assert blocked.exit_code == 1
        assert "--discard-incomplete --reason" in blocked.output

        accepted = runner.invoke(
            app,
            [
                "runs",
                "purge-work",
                "--yes",
                "--discard-incomplete",
                "--reason",
                "outputs are unusable",
                str(run_dir),
            ],
        )

        assert accepted.exit_code == 0, accepted.output
        assert read_manifest(run_dir).run["readiness_disposition"] == (
            "discarded_incomplete"
        )


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
