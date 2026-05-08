"""Tests for runops runs submit CLI command."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import tomli_w
from typer.testing import CliRunner

from runops.cli.main import app

runner = CliRunner()


def _write_manifest(run_dir: Path, data: dict[str, Any]) -> None:
    """Write a manifest.toml into the given run directory."""
    run_dir.mkdir(parents=True, exist_ok=True)
    with open(run_dir / "manifest.toml", "wb") as f:
        tomli_w.dump(data, f)


def _create_run(
    run_dir: Path,
    *,
    run_id: str = "R20260327-0001",
    status: str = "created",
    job_id: str = "",
) -> None:
    """Create a minimal run directory with manifest and job script."""
    manifest_data: dict[str, Any] = {
        "run": {
            "id": run_id,
            "display_name": "test_run",
            "status": status,
            "created_at": "2026-03-27T13:00:00+09:00",
        },
        "job": {
            "scheduler": "slurm",
            "job_id": job_id,
            "partition": "debug",
        },
    }
    _write_manifest(run_dir, manifest_data)

    # Create job script
    submit_dir = run_dir / "submit"
    submit_dir.mkdir(parents=True, exist_ok=True)
    job_sh = submit_dir / "job.sh"
    job_sh.write_text("#!/bin/bash\n#SBATCH --job-name=test\necho hello\n")

    # Create input files (pre-flight checks require non-empty input/)
    input_dir = run_dir / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    (input_dir / "params.json").write_text('{"nx": 64}')

    # Create work directory
    (run_dir / "work").mkdir(parents=True, exist_ok=True)


def test_submit_no_args() -> None:
    """Submit without arguments should show an error."""
    result = runner.invoke(app, ["runs", "submit"])
    assert result.exit_code != 0
    assert "RUN argument is required" in result.output or result.exit_code != 0


def test_submit_run_not_found(tmp_path: Path) -> None:
    """Submit a non-existent run should error."""
    # Create a project so project lookup works
    (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
    (tmp_path / "runs").mkdir()

    with patch("runops.cli.submit.Path.cwd", return_value=tmp_path):
        result = runner.invoke(app, ["runs", "submit", "nonexistent"])
    assert result.exit_code != 0


def test_submit_already_submitted(tmp_path: Path) -> None:
    """Submit a run that is already submitted should report an error."""
    (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
    run_dir = tmp_path / "runs" / "R20260327-0001"
    _create_run(run_dir, status="submitted", job_id="12345")

    with patch("runops.cli.submit.Path.cwd", return_value=tmp_path):
        result = runner.invoke(app, ["runs", "submit", str(run_dir)])
    assert result.exit_code != 0
    assert "submitted" in result.output


def test_submit_missing_job_script(tmp_path: Path) -> None:
    """Submit a run with no job.sh should error."""
    (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
    run_dir = tmp_path / "runs" / "R20260327-0001"
    _write_manifest(
        run_dir,
        {
            "run": {"id": "R20260327-0001", "status": "created"},
            "job": {"job_id": ""},
        },
    )
    # No submit/job.sh created

    with patch("runops.cli.submit.Path.cwd", return_value=tmp_path):
        result = runner.invoke(app, ["runs", "submit", str(run_dir)])
    assert result.exit_code != 0
    assert "Job script not found" in result.output


def test_submit_success(tmp_path: Path) -> None:
    """Successful submission should print job_id and update manifest."""
    (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
    run_dir = tmp_path / "runs" / "R20260327-0001"
    _create_run(run_dir)

    with (
        patch("runops.cli.submit.Path.cwd", return_value=tmp_path),
        patch(
            "runops.slurm.submit.sbatch_submit",
            return_value="99999",
        ),
    ):
        result = runner.invoke(app, ["runs", "submit", str(run_dir)])

    assert result.exit_code == 0
    assert "99999" in result.output
    assert "Submitted" in result.output

    # Verify manifest was updated
    from runops.core.manifest import read_manifest

    updated = read_manifest(run_dir)
    assert updated.job.get("job_id") == "99999"
    assert updated.run.get("status") == "submitted"
    assert updated.job.get("submitted_at") != ""
    assert "T" in updated.job["submitted_at"]  # ISO format check
    assert (run_dir / "status" / "state.json").exists()


def test_submit_dry_run(tmp_path: Path) -> None:
    """Dry-run should show info without actually submitting."""
    (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
    run_dir = tmp_path / "runs" / "R20260327-0001"
    _create_run(run_dir)

    with patch("runops.cli.submit.Path.cwd", return_value=tmp_path):
        result = runner.invoke(app, ["runs", "submit", "--dry-run", str(run_dir)])

    assert result.exit_code == 0
    assert "Would submit" in result.output


def test_submit_all(tmp_path: Path) -> None:
    """--all should submit all created runs and skip non-created ones."""
    (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
    survey_dir = tmp_path / "runs" / "survey1"

    # Two created runs, one already submitted
    _create_run(survey_dir / "R20260327-0001", run_id="R20260327-0001")
    _create_run(survey_dir / "R20260327-0002", run_id="R20260327-0002")
    _create_run(
        survey_dir / "R20260327-0003",
        run_id="R20260327-0003",
        status="submitted",
        job_id="11111",
    )

    with (
        patch("runops.cli.submit.Path.cwd", return_value=tmp_path),
        patch(
            "runops.slurm.submit.sbatch_submit",
            side_effect=["22222", "33333"],
        ),
    ):
        result = runner.invoke(
            app,
            ["runs", "submit", "--all", "--yes", str(survey_dir)],
        )

    assert result.exit_code == 0
    assert "22222" in result.output
    assert "33333" in result.output
    assert "2 submitted" in result.output
    assert "1 skipped" in result.output


def test_submit_all_confirmation_decline(tmp_path: Path) -> None:
    """--all should ask for confirmation before submitting created runs."""
    (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
    survey_dir = tmp_path / "runs" / "survey1"
    _create_run(survey_dir / "R20260327-0001", run_id="R20260327-0001")

    with (
        patch("runops.cli.submit.Path.cwd", return_value=tmp_path),
        patch("runops.slurm.submit.sbatch_submit") as mock_submit,
    ):
        result = runner.invoke(
            app,
            ["runs", "submit", "--all", str(survey_dir)],
            input="n\n",
        )

    assert result.exit_code == 0
    assert "About to submit 1 created run" in result.output
    assert "Cancelled." in result.output
    mock_submit.assert_not_called()


def test_submit_all_dry_run(tmp_path: Path) -> None:
    """--all --dry-run should list runs without submitting."""
    (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
    survey_dir = tmp_path / "runs" / "survey1"
    _create_run(survey_dir / "R20260327-0001", run_id="R20260327-0001")
    _create_run(
        survey_dir / "R20260327-0002",
        run_id="R20260327-0002",
        status="submitted",
        job_id="11111",
    )

    with patch("runops.cli.submit.Path.cwd", return_value=tmp_path):
        result = runner.invoke(
            app,
            ["runs", "submit", "--all", "--dry-run", str(survey_dir)],
        )

    assert result.exit_code == 0
    assert "would submit" in result.output
    assert "skip" in result.output


def test_submit_empty_input_dir(tmp_path: Path) -> None:
    """Submit a run with empty input/ should error."""
    (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
    run_dir = tmp_path / "runs" / "R20260327-0001"
    # Create run but remove input files
    _create_run(run_dir)
    # Remove the input file we created
    for f in (run_dir / "input").iterdir():
        f.unlink()

    with (
        patch("runops.cli.submit.Path.cwd", return_value=tmp_path),
        patch(
            "runops.slurm.submit.sbatch_submit",
            return_value="99999",
        ),
    ):
        result = runner.invoke(app, ["runs", "submit", str(run_dir)])

    assert result.exit_code != 0
    assert "input/" in result.output


def test_submit_sbatch_failure(tmp_path: Path) -> None:
    """sbatch failure should produce a user-friendly error."""
    (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
    run_dir = tmp_path / "runs" / "R20260327-0001"
    _create_run(run_dir)

    from runops.slurm.submit import SlurmSubmitError

    with (
        patch("runops.cli.submit.Path.cwd", return_value=tmp_path),
        patch(
            "runops.slurm.submit.sbatch_submit",
            side_effect=SlurmSubmitError("sbatch failed (exit 1):\nPermission denied"),
        ),
    ):
        result = runner.invoke(app, ["runs", "submit", str(run_dir)])

    assert result.exit_code != 0
    assert "sbatch failed" in result.output
