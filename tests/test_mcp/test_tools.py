"""Tests for runops MCP tool implementations."""

from __future__ import annotations

from pathlib import Path

from runops.core.manifest import ManifestData, write_manifest
from runops.mcp import tools


def _make_project(tmp_path: Path) -> Path:
    (tmp_path / "runops.toml").write_text(
        '[project]\nname = "mcp-demo"\ndescription = "demo"\n',
        encoding="utf-8",
    )
    (tmp_path / "simulators.toml").write_text("[simulators]\n", encoding="utf-8")
    (tmp_path / "launchers.toml").write_text("[launchers]\n", encoding="utf-8")
    (tmp_path / "runs").mkdir()
    return tmp_path


def _make_run(project_root: Path, *, status: str = "created") -> Path:
    run_dir = project_root / "runs" / "R20260512-0001"
    (run_dir / "submit").mkdir(parents=True)
    (run_dir / "input").mkdir()
    (run_dir / "input" / "params.toml").write_text("x = 1\n", encoding="utf-8")
    (run_dir / "work").mkdir()
    (run_dir / "submit" / "job.sh").write_text(
        "#!/bin/bash\n#SBATCH -t 00:10:00\npython simulate.py\n",
        encoding="utf-8",
    )
    write_manifest(
        run_dir,
        ManifestData(
            run={
                "id": "R20260512-0001",
                "display_name": "demo-run",
                "status": status,
            },
            origin={"case": "demo_case", "survey": ""},
            simulator={"name": "generic", "adapter": "generic"},
            job={
                "scheduler": "slurm",
                "job_id": "12345",
                "partition": "debug",
                "walltime": "00:10:00",
            },
            classification={"tags": ["smoke"]},
        ),
        log_event=False,
    )
    return run_dir


def test_health_returns_contract_envelope() -> None:
    result = tools.health()

    assert result["contract_version"] == "0.1"
    assert result["provider"] == "runops"
    assert result["tool"] == "runops.health"
    assert result["status"] == "ok"
    assert result["data"]["healthy"] is True


def test_project_status_summarizes_project(tmp_path: Path) -> None:
    project_root = _make_project(tmp_path)
    _make_run(project_root)

    result = tools.project_status(project_root=str(project_root))

    assert result["status"] == "ok"
    assert result["project"]["id"] == "mcp-demo"
    assert result["data"]["runs"]["total"] == 1


def test_run_list_filters_by_status_and_tag(tmp_path: Path) -> None:
    project_root = _make_project(tmp_path)
    _make_run(project_root)

    result = tools.run_list(
        project_root=str(project_root),
        status_filter="created",
        tag="smoke",
    )

    assert result["status"] == "ok"
    assert result["data"]["matched_count"] == 1
    assert result["data"]["runs"][0]["run_id"] == "R20260512-0001"


def test_run_logs_returns_latest_log_tail(tmp_path: Path) -> None:
    project_root = _make_project(tmp_path)
    run_dir = _make_run(project_root)
    (run_dir / "work" / "12345.out").write_text(
        "line 1\nline 2\nline 3\n",
        encoding="utf-8",
    )

    result = tools.run_logs(
        "R20260512-0001",
        project_root=str(project_root),
        lines=2,
    )

    assert result["status"] == "ok"
    assert result["data"]["lines"] == ["line 2", "line 3"]


def test_job_plan_submit_reports_sbatch_command(tmp_path: Path) -> None:
    project_root = _make_project(tmp_path)
    _make_run(project_root)

    result = tools.job_plan_submit(
        "R20260512-0001",
        project_root=str(project_root),
        queue_name="debug",
        qos="normal",
        afterok="111",
    )

    assert result["status"] == "ok"
    assert result["data"]["will_submit"] is True
    assert result["data"]["command"][:2] == [
        "sbatch",
        f"--chdir={project_root / 'runs' / 'R20260512-0001' / 'work'}",
    ]
    assert "--dependency=afterok:111" in result["data"]["command"]
    assert "--partition=debug" in result["data"]["command"]
    assert "--qos=normal" in result["data"]["command"]


def test_job_plan_submit_blocks_non_created_run(tmp_path: Path) -> None:
    project_root = _make_project(tmp_path)
    _make_run(project_root, status="running")

    result = tools.job_plan_submit("R20260512-0001", project_root=str(project_root))

    assert result["status"] == "blocked"
    assert result["data"]["will_submit"] is False
    assert result["errors"][0]["code"] == "precondition_failed"
