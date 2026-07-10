"""Tests for runops runs submit CLI command."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import tomli_w
from typer.testing import CliRunner

from runops.application.actions import ActionResult, ActionStatus
from runops.application.execution.submission import SubmitRequest, plan_submit
from runops.cli.main import app
from runops.core.manifest import update_manifest

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
            "runops.slurm.submit.submit_command",
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
    """Single-target dry-run renders the shared plan without mutation."""
    (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
    run_dir = tmp_path / "runs" / "R20260327-0001"
    _create_run(run_dir)
    plan = plan_submit(SubmitRequest(run_dir=run_dir))
    before = (run_dir / "manifest.toml").read_bytes()

    with patch("runops.cli.submit.Path.cwd", return_value=tmp_path):
        result = runner.invoke(app, ["runs", "submit", "--dry-run", str(run_dir)])

    assert result.exit_code == 0
    assert "Would submit" in result.output
    for argument in plan.command:
        assert argument in result.output
    for check in plan.preconditions:
        assert check.name in result.output
        assert check.message in result.output
    assert (run_dir / "manifest.toml").read_bytes() == before
    assert not (run_dir / "status").exists()


def test_submit_cwd_dry_run_passes_options_to_shared_plan(tmp_path: Path) -> None:
    """Cwd dry-run renders exact option-bearing command without mutation."""
    run_dir = tmp_path / "R20260327-0001"
    _create_run(run_dir)
    plan = plan_submit(
        SubmitRequest(
            run_dir=run_dir,
            queue_name="compute",
            qos="normal",
            afterok="123",
        )
    )
    before = (run_dir / "manifest.toml").read_bytes()

    with patch("runops.cli.submit.Path.cwd", return_value=run_dir):
        result = runner.invoke(
            app,
            [
                "runs",
                "submit",
                "--dry-run",
                "--queue-name",
                "compute",
                "--qos",
                "normal",
                "--afterok",
                "123",
            ],
        )

    assert result.exit_code == 0
    for argument in plan.command:
        assert argument in result.output
    for check in plan.preconditions:
        assert check.name in result.output
        assert check.message in result.output
    assert (run_dir / "manifest.toml").read_bytes() == before
    assert not (run_dir / "status").exists()


def test_submit_all(tmp_path: Path) -> None:
    """--all submits only ready plans and skips every blocked plan."""
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
    blocked_created = survey_dir / "R20260327-0004"
    _create_run(blocked_created, run_id="R20260327-0004")
    for input_file in (blocked_created / "input").iterdir():
        input_file.unlink()
    blocked_plan = plan_submit(SubmitRequest(run_dir=blocked_created))

    with (
        patch("runops.cli.submit.Path.cwd", return_value=tmp_path),
        patch(
            "runops.slurm.submit.submit_command",
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
    assert "2 skipped" in result.output
    for check in blocked_plan.failed_preconditions:
        assert check.name in result.output
        assert check.message in result.output


def test_submit_all_confirmation_decline(tmp_path: Path) -> None:
    """--all should ask for confirmation before submitting created runs."""
    (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
    survey_dir = tmp_path / "runs" / "survey1"
    _create_run(survey_dir / "R20260327-0001", run_id="R20260327-0001")

    with (
        patch("runops.cli.submit.Path.cwd", return_value=tmp_path),
        patch("runops.slurm.submit.submit_command") as mock_submit,
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


def test_submit_all_passes_exact_confirmed_plan_to_application_mapper(
    tmp_path: Path,
) -> None:
    (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
    survey_dir = tmp_path / "runs" / "survey1"
    run_dir = survey_dir / "R20260327-0001"
    _create_run(run_dir, run_id=run_dir.name)
    confirmed_plan = plan_submit(SubmitRequest(run_dir=run_dir))
    mapped_plans: list[object] = []

    def map_plan(plan: object) -> ActionResult:
        mapped_plans.append(plan)
        return ActionResult(
            action="submit_run",
            status=ActionStatus.SUCCESS,
            message="Submitted job 22222",
            data={
                "job_id": "22222",
                "run_id": confirmed_plan.run_id,
                "warnings": [],
            },
        )

    with (
        patch("runops.cli.submit.Path.cwd", return_value=tmp_path),
        patch(
            "runops.cli.submit._build_submit_plan",
            return_value=confirmed_plan,
        ),
        patch(
            "runops.cli.submit.submit_planned_run_action",
            side_effect=map_plan,
            create=True,
        ),
        patch(
            "runops.cli.submit.submit_run_action",
            return_value=ActionResult(
                action="submit_run",
                status=ActionStatus.SUCCESS,
                message="legacy path",
                data={
                    "job_id": "legacy",
                    "run_id": confirmed_plan.run_id,
                    "warnings": [],
                },
            ),
            create=True,
        ) as legacy_action,
    ):
        result = runner.invoke(
            app,
            ["runs", "submit", "--all", str(survey_dir)],
            input="y\n",
        )

    assert result.exit_code == 0
    assert len(mapped_plans) == 1
    assert mapped_plans[0] is confirmed_plan
    legacy_action.assert_not_called()


def test_submit_all_rejects_confirmed_plan_after_identity_and_workdir_change(
    tmp_path: Path,
) -> None:
    (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
    survey_dir = tmp_path / "runs" / "survey1"
    run_dir = survey_dir / "R20260327-0001"
    _create_run(run_dir, run_id=run_dir.name)

    def confirm_after_mutation(prompt: str) -> bool:
        del prompt
        update_manifest(run_dir, {"run": {"id": "R20260327-replaced"}})
        (run_dir / "work").rmdir()
        return True

    with (
        patch("runops.cli.submit.Path.cwd", return_value=tmp_path),
        patch("runops.cli.submit.typer.confirm", side_effect=confirm_after_mutation),
        patch("runops.slurm.submit.submit_command") as scheduler,
    ):
        result = runner.invoke(
            app,
            ["runs", "submit", "--all", str(survey_dir)],
        )

    assert result.exit_code == 1
    assert "stale" in result.output.lower()
    scheduler.assert_not_called()


def test_submit_all_skips_plan_read_error_and_continues(tmp_path: Path) -> None:
    """A malformed run is reported and does not block other ready plans."""
    (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
    survey_dir = tmp_path / "runs" / "survey1"
    ready_run = survey_dir / "R20260327-0001"
    _create_run(ready_run, run_id=ready_run.name)
    malformed_run = survey_dir / "R20260327-0002"
    malformed_run.mkdir(parents=True)
    (malformed_run / "manifest.toml").write_text(
        "[run\nid = broken\n",
        encoding="utf-8",
    )

    with (
        patch("runops.cli.submit.Path.cwd", return_value=tmp_path),
        patch("runops.slurm.submit.submit_command", return_value="22222"),
    ):
        result = runner.invoke(
            app,
            ["runs", "submit", "--all", "--yes", str(survey_dir)],
        )

    assert result.exit_code == 0
    assert "R20260327-0002 (error) [skip]" in result.output
    assert "22222" in result.output
    assert "1 submitted" in result.output
    assert "1 skipped" in result.output


def test_submit_all_dry_run(tmp_path: Path) -> None:
    """Bulk dry-run renders ready and multiply-blocked shared plans."""
    (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
    survey_dir = tmp_path / "runs" / "survey1"
    _create_run(survey_dir / "R20260327-0001", run_id="R20260327-0001")
    blocked_run = survey_dir / "R20260327-0002"
    _create_run(
        blocked_run,
        run_id="R20260327-0002",
        status="running",
        job_id="11111",
    )
    (blocked_run / "submit" / "job.sh").unlink()
    for input_file in (blocked_run / "input").iterdir():
        input_file.unlink()
    blocked_plan = plan_submit(
        SubmitRequest(
            run_dir=blocked_run,
            queue_name="compute",
            qos="normal",
            afterok="123",
        )
    )
    manifests = {
        run_dir: (run_dir / "manifest.toml").read_bytes()
        for run_dir in (survey_dir / "R20260327-0001", blocked_run)
    }

    with patch("runops.cli.submit.Path.cwd", return_value=tmp_path):
        result = runner.invoke(
            app,
            [
                "runs",
                "submit",
                "--all",
                "--dry-run",
                "--queue-name",
                "compute",
                "--qos",
                "normal",
                "--afterok",
                "123",
                str(survey_dir),
            ],
        )

    assert result.exit_code == 0
    assert "would submit" in result.output
    assert "skip" in result.output
    for check in blocked_plan.failed_preconditions:
        assert check.name in result.output
        assert check.message in result.output
    for argument in blocked_plan.command:
        assert argument in result.output
    for run_dir, before in manifests.items():
        assert (run_dir / "manifest.toml").read_bytes() == before
        assert not (run_dir / "status").exists()


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
            "runops.slurm.submit.submit_command",
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
            "runops.slurm.submit.submit_command",
            side_effect=SlurmSubmitError("sbatch failed (exit 1):\nPermission denied"),
        ),
    ):
        result = runner.invoke(app, ["runs", "submit", str(run_dir)])

    assert result.exit_code != 0
    assert "sbatch failed" in result.output
