"""Tests for `runops runs retry`."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import tomli_w
from typer.testing import CliRunner

from runops.cli.main import app
from runops.core.manifest import read_manifest

runner = CliRunner()


def _create_run(
    parent: Path,
    run_id: str,
    *,
    status: str,
    failure_reason: str = "",
    attempt: int = 0,
) -> Path:
    run_dir = parent / run_id
    run_dir.mkdir(parents=True)
    for sub in ("input", "submit", "work", "analysis", "status"):
        (run_dir / sub).mkdir()

    manifest: dict[str, Any] = {
        "run": {
            "id": run_id,
            "display_name": "retry test",
            "status": status,
            "failure_reason": failure_reason,
        },
        "job": {
            "scheduler": "slurm",
            "job_id": "old-job-id",
            "attempt": attempt,
        },
    }
    with open(run_dir / "manifest.toml", "wb") as f:
        tomli_w.dump(manifest, f)
    return run_dir


def test_retry_resets_failed_run(tmp_path: Path) -> None:
    """Failed run can be retried and is reset to created."""
    (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
    run_dir = _create_run(tmp_path, "R20260418-0001", status="failed")

    with patch("runops.cli.retry.Path.cwd", return_value=tmp_path):
        result = runner.invoke(app, ["runs", "retry", str(run_dir)])

    assert result.exit_code == 0, result.output
    assert "Reset to created" in result.output
    assert "failed -> created" in result.output


def test_retry_resets_cancelled_run(tmp_path: Path) -> None:
    """Cancelled run can also be retried (addresses #26 workflow)."""
    (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
    run_dir = _create_run(tmp_path, "R20260418-0002", status="cancelled")

    with patch("runops.cli.retry.Path.cwd", return_value=tmp_path):
        result = runner.invoke(app, ["runs", "retry", str(run_dir)])

    assert result.exit_code == 0, result.output
    assert "Reset to created" in result.output
    assert "cancelled -> created" in result.output


def test_retry_rejects_exit_error_without_reviewed_log(tmp_path: Path) -> None:
    """failure_reason=exit_error requires --reviewed-log."""
    (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
    run_dir = _create_run(
        tmp_path,
        "R20260418-0003",
        status="failed",
        failure_reason="exit_error",
    )

    with patch("runops.cli.retry.Path.cwd", return_value=tmp_path):
        result = runner.invoke(app, ["runs", "retry", str(run_dir)])

    assert result.exit_code == 1
    assert "log review" in result.output


def test_retry_exit_error_with_reviewed_log_succeeds(tmp_path: Path) -> None:
    """--reviewed-log unlocks exit_error retries."""
    (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
    run_dir = _create_run(
        tmp_path,
        "R20260418-0004",
        status="failed",
        failure_reason="exit_error",
    )

    with patch("runops.cli.retry.Path.cwd", return_value=tmp_path):
        result = runner.invoke(app, ["runs", "retry", str(run_dir), "--reviewed-log"])

    assert result.exit_code == 0, result.output
    assert "Reset to created" in result.output


def test_retry_adjustments_parse_key_value(tmp_path: Path) -> None:
    """-a KEY=VAL is forwarded to retry_run as a dict."""
    (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
    run_dir = _create_run(tmp_path, "R20260418-0005", status="failed")

    with patch("runops.cli.retry.Path.cwd", return_value=tmp_path):
        result = runner.invoke(
            app,
            [
                "runs",
                "retry",
                str(run_dir),
                "-a",
                "walltime=24:00:00",
                "-a",
                "nodes=4",
            ],
        )

    assert result.exit_code == 0, result.output


def test_retry_plan_records_intent_without_reset(tmp_path: Path) -> None:
    """--plan records retry metadata and leaves state unchanged."""
    (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
    run_dir = _create_run(
        tmp_path,
        "R20260507-0001",
        status="failed",
        failure_reason="timeout",
        attempt=1,
    )
    (run_dir / "work" / "partial.dat").write_text("partial", encoding="utf-8")

    with patch("runops.cli.retry.Path.cwd", return_value=tmp_path):
        result = runner.invoke(
            app,
            [
                "runs",
                "retry",
                str(run_dir),
                "--plan",
                "-a",
                "walltime=24:00:00",
            ],
        )

    assert result.exit_code == 0, result.output
    assert "Planned retry" in result.output
    assert "Retry status: retry_planned" in result.output
    assert "Partial outputs:" in result.output
    manifest = read_manifest(run_dir)
    assert manifest.run["status"] == "failed"
    assert manifest.run["retry_status"] == "retry_planned"
    assert manifest.job["retry_adjustments"] == {"walltime": "24:00:00"}


def test_retry_rejects_invalid_adjustment(tmp_path: Path) -> None:
    """Adjustments without '=' raise BadParameter."""
    (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
    run_dir = _create_run(tmp_path, "R20260418-0006", status="failed")

    with patch("runops.cli.retry.Path.cwd", return_value=tmp_path):
        result = runner.invoke(app, ["runs", "retry", str(run_dir), "-a", "malformed"])

    assert result.exit_code != 0
    assert "missing '='" in result.output or 'missing "="' in result.output
