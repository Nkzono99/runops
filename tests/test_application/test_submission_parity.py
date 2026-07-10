"""Cross-interface parity tests for shared submission plans."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import tomli_w
from typer.testing import CliRunner

from runops.application.execution.submission import (
    SubmitPlan,
    SubmitRequest,
    plan_submit,
)
from runops.cli.main import app
from runops.core.manifest import update_manifest
from runops.mcp import tools

runner = CliRunner()


def _write_manifest(run_dir: Path, *, run_id: str, status: str) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    with open(run_dir / "manifest.toml", "wb") as stream:
        tomli_w.dump(
            {
                "run": {"id": run_id, "status": status},
                "job": {"scheduler": "slurm", "job_id": ""},
            },
            stream,
        )


def _make_project(tmp_path: Path) -> tuple[Path, Path, Path]:
    project_root = tmp_path
    (project_root / "runops.toml").write_text(
        '[project]\nname = "submission-parity"\n',
        encoding="utf-8",
    )
    runs_dir = project_root / "runs"
    runs_dir.mkdir()

    ready_run = runs_dir / "R20260710-0001"
    _write_manifest(ready_run, run_id=ready_run.name, status="created")
    (ready_run / "submit").mkdir()
    (ready_run / "submit" / "job.sh").write_text(
        "#!/bin/bash\n#SBATCH --job-name=ready\n",
        encoding="utf-8",
    )
    (ready_run / "input").mkdir()
    (ready_run / "input" / "params.toml").write_text(
        "nx = 16\n",
        encoding="utf-8",
    )
    (ready_run / "work").mkdir()

    blocked_run = runs_dir / "R20260710-0002"
    _write_manifest(blocked_run, run_id=blocked_run.name, status="running")
    (blocked_run / "input").mkdir()

    return project_root, ready_run, blocked_run


def _serialized_preconditions(plan: SubmitPlan) -> list[dict[str, object]]:
    return [
        {"name": check.name, "ok": check.passed, "message": check.message}
        for check in plan.preconditions
    ]


def _mark_dirty_production(run_dir: Path) -> None:
    update_manifest(
        run_dir,
        {
            "classification": {"tags": ["production"]},
            "simulator_source": {"git_dirty": True},
        },
    )


def test_ready_plan_matches_mcp_and_cli_exactly_without_mutation(
    tmp_path: Path,
) -> None:
    project_root, ready_run, _ = _make_project(tmp_path)
    request = SubmitRequest(
        run_dir=ready_run,
        queue_name="debug",
        qos="normal",
        afterok="111",
    )
    plan = plan_submit(request)
    manifest_path = ready_run / "manifest.toml"
    before = manifest_path.read_bytes()
    state_path = ready_run / "status" / "state.json"
    state_path.parent.mkdir()
    state_path.write_bytes(b'{"source":"existing"}\n')
    state_before = state_path.read_bytes()

    mcp_result = tools.job_plan_submit(
        ready_run.name,
        project_root=str(project_root),
        queue_name="debug",
        qos="normal",
        afterok="111",
    )
    with patch("runops.cli.submit.Path.cwd", return_value=project_root):
        cli_result = runner.invoke(
            app,
            [
                "runs",
                "submit",
                "--dry-run",
                "--queue-name",
                "debug",
                "--qos",
                "normal",
                "--afterok",
                "111",
                str(ready_run),
            ],
        )

    assert mcp_result["status"] == "ok"
    assert mcp_result["data"]["command"] == list(plan.command)
    assert mcp_result["data"]["preconditions"] == _serialized_preconditions(plan)
    assert mcp_result["data"]["will_submit"] is plan.ready
    assert cli_result.exit_code == 0
    for argument in plan.command:
        assert argument in cli_result.output
    for check in plan.preconditions:
        assert check.name in cli_result.output
        assert check.message in cli_result.output
    assert manifest_path.read_bytes() == before
    assert state_path.read_bytes() == state_before


def test_multiply_blocked_plan_exposes_every_failure_without_mutation(
    tmp_path: Path,
) -> None:
    project_root, _, blocked_run = _make_project(tmp_path)
    request = SubmitRequest(
        run_dir=blocked_run,
        queue_name="debug",
        qos="normal",
        afterok="111",
    )
    plan = plan_submit(request)
    manifest_path = blocked_run / "manifest.toml"
    before = manifest_path.read_bytes()
    state_path = blocked_run / "status" / "state.json"
    state_path.parent.mkdir()
    state_path.write_bytes(b'{"source":"existing"}\n')
    state_before = state_path.read_bytes()

    assert len(plan.failed_preconditions) == 5
    mcp_result = tools.job_plan_submit(
        blocked_run.name,
        project_root=str(project_root),
        queue_name="debug",
        qos="normal",
        afterok="111",
    )
    with patch("runops.cli.submit.Path.cwd", return_value=project_root):
        cli_result = runner.invoke(
            app,
            [
                "runs",
                "submit",
                "--dry-run",
                "--queue-name",
                "debug",
                "--qos",
                "normal",
                "--afterok",
                "111",
                str(blocked_run),
            ],
        )

    assert mcp_result["status"] == "blocked"
    assert mcp_result["data"]["command"] == list(plan.command)
    assert mcp_result["data"]["preconditions"] == _serialized_preconditions(plan)
    assert mcp_result["data"]["will_submit"] is plan.ready
    assert [item["code"] for item in mcp_result["errors"]] == [
        "precondition_failed"
    ] * len(plan.failed_preconditions)
    assert cli_result.exit_code == 0
    for argument in plan.command:
        assert argument in cli_result.output
    for check in plan.failed_preconditions:
        assert check.name in cli_result.output
        assert check.message in cli_result.output
    assert manifest_path.read_bytes() == before
    assert state_path.read_bytes() == state_before


def test_ready_plan_warning_matches_shared_plan_in_mcp_and_cli(
    tmp_path: Path,
) -> None:
    project_root, ready_run, _ = _make_project(tmp_path)
    _mark_dirty_production(ready_run)
    plan = plan_submit(SubmitRequest(run_dir=ready_run))

    mcp_result = tools.job_plan_submit(
        ready_run.name,
        project_root=str(project_root),
    )
    with patch("runops.cli.submit.Path.cwd", return_value=project_root):
        cli_result = runner.invoke(
            app,
            ["runs", "submit", "--dry-run", str(ready_run)],
        )

    assert plan.ready is True
    assert plan.warnings
    assert mcp_result["status"] == "warning"
    assert mcp_result["data"]["warnings"] == list(plan.warnings)
    assert [item["message"] for item in mcp_result["warnings"]] == list(plan.warnings)
    assert all(
        item["code"] == "submission_plan_warning" for item in mcp_result["warnings"]
    )
    assert cli_result.exit_code == 0
    for message in plan.warnings:
        assert f"Warning: {message}" in cli_result.output


def test_blocked_plan_preserves_shared_warning_in_mcp_and_cli(
    tmp_path: Path,
) -> None:
    project_root, _, blocked_run = _make_project(tmp_path)
    _mark_dirty_production(blocked_run)
    plan = plan_submit(SubmitRequest(run_dir=blocked_run))

    mcp_result = tools.job_plan_submit(
        blocked_run.name,
        project_root=str(project_root),
    )
    with patch("runops.cli.submit.Path.cwd", return_value=project_root):
        cli_result = runner.invoke(
            app,
            ["runs", "submit", "--dry-run", str(blocked_run)],
        )

    assert plan.ready is False
    assert plan.warnings
    assert mcp_result["status"] == "blocked"
    assert mcp_result["data"]["warnings"] == list(plan.warnings)
    assert [item["message"] for item in mcp_result["warnings"]] == list(plan.warnings)
    assert cli_result.exit_code == 0
    for message in plan.warnings:
        assert f"Warning: {message}" in cli_result.output
