"""Tests for ``runo runs relabel``."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

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
    display_name: str = "size r7e6",
    status: str = "completed",
    basename: str | None = None,
    archived_from: Path | None = None,
) -> Path:
    run_dir = parent / (basename or run_id)
    run_dir.mkdir(parents=True)
    for subdir in ("input", "submit", "work", "analysis", "status"):
        (run_dir / subdir).mkdir()
    manifest: dict[str, Any] = {
        "run": {
            "id": run_id,
            "display_name": display_name,
            "status": status,
        },
        "path": {"run_dir": str(run_dir.resolve())},
    }
    if archived_from is not None:
        manifest["path"]["archived_from"] = str(archived_from.resolve())
        manifest["path"]["created_at_path"] = str(archived_from.resolve())
    with open(run_dir / "manifest.toml", "wb") as file:
        tomli_w.dump(manifest, file)
    (run_dir / "submit" / "job.sh").write_text(
        f"#!/bin/bash\ncd {archived_from or run_dir}\n",
        encoding="utf-8",
    )
    (run_dir / "work" / "result.dat").write_text("preserved\n", encoding="utf-8")
    return run_dir


def _manifest(run_dir: Path) -> dict[str, Any]:
    with open(run_dir / "manifest.toml", "rb") as file:
        return tomllib.load(file)


def test_relabel_dry_run_does_not_mutate(tmp_path: Path) -> None:
    run_dir = _create_run(tmp_path, "R20260721-0001")

    result = runner.invoke(app, ["runs", "relabel", "--dry-run", str(run_dir)])

    assert result.exit_code == 0, result.output
    assert "1 to relabel" in result.output
    assert "R20260721-0001--size-r7e6" in result.output
    assert run_dir.is_dir()


def test_relabel_moves_inactive_run_and_updates_paths(tmp_path: Path) -> None:
    run_id = "R20260721-0001"
    run_dir = _create_run(tmp_path, run_id)
    destination = tmp_path / f"{run_id}--size-r7e6"

    result = runner.invoke(app, ["runs", "relabel", "--yes", str(run_dir)])

    assert result.exit_code == 0, result.output
    assert not run_dir.exists()
    assert destination.is_dir()
    assert (destination / "work" / "result.dat").read_text() == "preserved\n"
    assert _manifest(destination)["path"]["run_dir"] == str(destination.resolve())
    job_text = (destination / "submit" / "job.sh").read_text()
    assert str(destination.resolve()) in job_text
    assert f"cd {run_dir.resolve()}\n" not in job_text


def test_relabel_updates_archived_restore_path(tmp_path: Path) -> None:
    run_id = "R20260721-0001"
    restore_path = tmp_path / "runs" / "scan" / run_id
    run_dir = _create_run(
        tmp_path / "runs" / "_archive" / "scan",
        run_id,
        status="archived",
        archived_from=restore_path,
    )
    destination = run_dir.with_name(f"{run_id}--size-r7e6")

    result = runner.invoke(app, ["runs", "relabel", "--yes", str(run_dir)])

    assert result.exit_code == 0, result.output
    manifest = _manifest(destination)
    assert manifest["path"]["archived_from"] == str(
        restore_path.with_name(f"{run_id}--size-r7e6").resolve()
    )
    assert manifest["path"]["created_at_path"] == str(restore_path.resolve())
    assert (
        str(restore_path.with_name(f"{run_id}--size-r7e6"))
        in (destination / "submit" / "job.sh").read_text()
    )


def test_relabel_skips_active_and_already_labeled_runs(tmp_path: Path) -> None:
    active = _create_run(tmp_path, "R20260721-0001", status="running")
    labeled = _create_run(
        tmp_path,
        "R20260721-0002",
        basename="R20260721-0002--baseline",
    )

    result = runner.invoke(app, ["runs", "relabel", "--yes", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "0 to relabel, 2 skipped" in result.output
    assert "active runs cannot be relabeled" in result.output
    assert "already has a label" in result.output
    assert active.is_dir()
    assert labeled.is_dir()


def test_relabel_skips_empty_display_name(tmp_path: Path) -> None:
    run_dir = _create_run(tmp_path, "R20260721-0001", display_name="")

    result = runner.invoke(app, ["runs", "relabel", "--yes", str(run_dir)])

    assert result.exit_code == 0, result.output
    assert "no run.display_name" in result.output
    assert run_dir.is_dir()
