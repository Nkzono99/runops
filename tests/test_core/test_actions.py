"""Tests for agent-facing action helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import tomli_w

from runops.core.actions import (
    ActionStatus,
    add_fact,
    collect_survey,
    create_survey,
    execute_action,
    export_publication,
    plan_retry,
    promote_fact,
    purge_work,
    retry_run,
    save_insight,
    submit_run,
    summarize_run,
)
from runops.core.actions import (
    create_run as create_run_action,
)
from runops.core.knowledge import list_insights, load_facts
from runops.core.state import RunState
from runops.slurm.query import JobStatus

ADAPTER_PATCH = "runops.core.analysis.workflow.get_adapter"


def _write_manifest(run_dir: Path, data: dict[str, Any]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    with open(run_dir / "manifest.toml", "wb") as f:
        tomli_w.dump(data, f)


def _create_project_with_case(project_root: Path) -> None:
    (project_root / "runops.toml").write_text(
        '[project]\nname = "test-project"\n',
        encoding="utf-8",
    )
    (project_root / "simulators.toml").write_text(
        "[simulators.test_sim]\n"
        'adapter = "generic"\n'
        'executable = "echo"\n'
        'resolver_mode = "package"\n',
        encoding="utf-8",
    )
    (project_root / "launchers.toml").write_text(
        "[launchers.slurm_srun]\n"
        'kind = "srun"\n'
        'command = "srun"\n'
        "use_slurm_ntasks = true\n",
        encoding="utf-8",
    )
    case_dir = project_root / "cases" / "my_case"
    case_dir.mkdir(parents=True)
    (project_root / "runs").mkdir()
    (case_dir / "case.toml").write_text(
        "[case]\n"
        'name = "my_case"\n'
        'simulator = "test_sim"\n'
        'launcher = "slurm_srun"\n'
        "\n"
        "[job]\n"
        'partition = "debug"\n'
        "nodes = 1\n"
        "ntasks = 2\n"
        'walltime = "00:10:00"\n'
        "\n"
        "[params]\n"
        "nx = 64\n"
        "ny = 64\n",
        encoding="utf-8",
    )


def test_collect_survey_requires_at_least_one_completed_run(tmp_path: Path) -> None:
    run_dir = tmp_path / "R20260330-0001"
    _write_manifest(
        run_dir,
        {
            "run": {
                "id": "R20260330-0001",
                "status": "failed",
            }
        },
    )

    result = collect_survey(tmp_path)

    assert result.status is ActionStatus.PRECONDITION_FAILED
    assert "No completed runs" in result.message


def test_create_run_action_generates_full_run_artifacts(tmp_path: Path) -> None:
    _create_project_with_case(tmp_path)

    result = create_run_action(
        tmp_path,
        "my_case",
        params={"nx": 128},
        display_name="custom-display",
    )

    assert result.status is ActionStatus.SUCCESS
    run_dir = Path(result.data["run_dir"])
    assert (run_dir / "manifest.toml").exists()
    assert (run_dir / "submit" / "job.sh").exists()
    assert (run_dir / "input" / "params.json").exists()

    with open(run_dir / "input" / "params.json", encoding="utf-8") as f:
        params = json.load(f)
    assert params["nx"] == 128
    assert params["ny"] == 64


def test_create_survey_action_expands_all_combinations(tmp_path: Path) -> None:
    _create_project_with_case(tmp_path)
    survey_dir = tmp_path / "runs" / "scan"
    survey_dir.mkdir(parents=True)
    (survey_dir / "survey.toml").write_text(
        "[survey]\n"
        'id = "S20260402-scan"\n'
        'name = "scan"\n'
        'base_case = "my_case"\n'
        'simulator = "test_sim"\n'
        'launcher = "slurm_srun"\n'
        "\n"
        "[axes]\n"
        "nx = [32, 64]\n"
        "ny = [16, 32]\n"
        "\n"
        "[naming]\n"
        'display_name = "nx{nx}_ny{ny}"\n',
        encoding="utf-8",
    )

    result = create_survey(tmp_path, survey_dir)

    assert result.status is ActionStatus.SUCCESS
    assert result.state_after == "created"
    assert result.data["created_count"] == 4
    assert len(result.data["runs"]) == 4


def test_collect_survey_writes_aggregate_artifacts(tmp_path: Path) -> None:
    run_dir = tmp_path / "R20260330-0001"
    _write_manifest(
        run_dir,
        {
            "run": {
                "id": "R20260330-0001",
                "status": "completed",
                "display_name": "baseline",
            }
        },
    )
    (run_dir / "analysis").mkdir(parents=True, exist_ok=True)
    with open(run_dir / "analysis" / "summary.json", "w", encoding="utf-8") as f:
        json.dump({"energy": 1.0}, f)

    result = collect_survey(tmp_path)

    assert result.status is ActionStatus.SUCCESS
    assert Path(result.data["csv_path"]).exists()
    assert Path(result.data["json_path"]).exists()
    assert Path(result.data["report_path"]).exists()


def test_collect_survey_does_not_auto_summarize_completed_runs(tmp_path: Path) -> None:
    run_dir = tmp_path / "R20260330-0001"
    _write_manifest(
        run_dir,
        {
            "run": {
                "id": "R20260330-0001",
                "status": "completed",
            },
            "simulator": {
                "name": "test_sim",
                "adapter": "test_adapter",
            },
        },
    )

    mock_adapter = MagicMock()
    mock_adapter.summarize.return_value = {"energy": 2.5}
    mock_adapter_cls = MagicMock(return_value=mock_adapter)

    with patch(ADAPTER_PATCH, return_value=mock_adapter_cls):
        result = collect_survey(tmp_path)

    assert result.status is ActionStatus.ERROR
    assert "No summaries found" in result.message
    assert not (run_dir / "analysis" / "summary.json").exists()
    mock_adapter.summarize.assert_not_called()


def test_summarize_run_writes_summary_json(tmp_path: Path) -> None:
    run_dir = tmp_path / "R20260330-0001"
    run_dir.mkdir(parents=True, exist_ok=True)
    _write_manifest(
        run_dir,
        {
            "run": {
                "id": "R20260330-0001",
                "status": "completed",
            },
            "simulator": {
                "name": "test_sim",
                "adapter": "test_adapter",
            },
        },
    )

    mock_adapter = MagicMock()
    mock_adapter.summarize.return_value = {"energy": 42.0}
    mock_adapter_cls = MagicMock(return_value=mock_adapter)

    with patch(ADAPTER_PATCH, return_value=mock_adapter_cls):
        result = summarize_run(run_dir)

    assert result.status is ActionStatus.SUCCESS
    assert (run_dir / "analysis" / "summary.json").exists()
    with open(run_dir / "analysis" / "summary.json", encoding="utf-8") as f:
        data = json.load(f)
    assert data["energy"] == 42.0


def test_export_publication_creates_bundle(tmp_path: Path) -> None:
    (tmp_path / "runops.toml").write_text(
        '[project]\nname = "test-project"\n',
        encoding="utf-8",
    )
    run_dir = tmp_path / "runs" / "R20260330-0001"
    _write_manifest(
        run_dir,
        {
            "run": {
                "id": "R20260330-0001",
                "status": "completed",
            },
            "simulator": {
                "name": "test_sim",
                "adapter": "test_adapter",
            },
        },
    )
    (run_dir / "analysis").mkdir(parents=True, exist_ok=True)
    with open(run_dir / "analysis" / "summary.json", "w", encoding="utf-8") as f:
        json.dump({"energy": 3.0}, f)

    result = export_publication(
        run_dir,
        "draft-a",
        export_name="baseline-export",
    )

    assert result.status is ActionStatus.SUCCESS
    assert Path(result.data["manifest_path"]).exists()
    assert result.data["target_kind"] == "run"
    assert result.data["source_run_ids"] == ["R20260330-0001"]
    with open(result.data["manifest_path"], encoding="utf-8") as f:
        manifest = json.load(f)
    assert manifest["export"]["id"] == "draft-a/baseline-export"


def test_retry_run_blocks_exit_error_without_log_review(tmp_path: Path) -> None:
    run_dir = tmp_path / "R20260330-0001"
    _write_manifest(
        run_dir,
        {
            "run": {
                "id": "R20260330-0001",
                "status": "failed",
                "failure_reason": "exit_error",
            },
            "job": {
                "attempt": 1,
            },
        },
    )

    result = retry_run(run_dir)

    assert result.status is ActionStatus.PRECONDITION_FAILED
    assert "requires log review" in result.message


def test_retry_run_accepts_cancelled_state(tmp_path: Path) -> None:
    """Cancelled runs (e.g. after a hang-cancel) can also be retried."""
    run_dir = tmp_path / "R20260418-0002"
    _write_manifest(
        run_dir,
        {
            "run": {
                "id": "R20260418-0002",
                "status": "cancelled",
                "failure_reason": "",
                "last_slurm_state": "CANCELLED",
            },
            "job": {
                "attempt": 1,
                "job_id": "12345",
                "submitted_at": "2026-04-18T00:00:00Z",
            },
        },
    )

    result = retry_run(run_dir)

    assert result.status is ActionStatus.SUCCESS
    assert result.state_before == "cancelled"
    assert result.state_after == "created"

    from runops.core.manifest import read_manifest

    updated = read_manifest(run_dir)
    assert updated.run["status"] == "created"
    assert updated.run["failure_reason"] == ""
    assert updated.run["last_slurm_state"] == ""
    assert updated.job["job_id"] == ""
    assert updated.job["submitted_at"] == ""

    state_file = run_dir / "status" / "state.json"
    assert state_file.exists()
    with open(state_file, encoding="utf-8") as f:
        state_data = json.load(f)
    assert state_data["state"] == "created"
    assert state_data["previous_state"] == "cancelled"
    assert state_data["reason"] == "retry"


def test_retry_run_respects_max_attempts(tmp_path: Path) -> None:
    run_dir = tmp_path / "R20260330-0001"
    _write_manifest(
        run_dir,
        {
            "run": {
                "id": "R20260330-0001",
                "status": "failed",
                "failure_reason": "timeout",
            },
            "job": {
                "attempts": [
                    {"attempt": "1"},
                    {"attempt": "2"},
                    {"attempt": "3"},
                ],
            },
        },
    )

    result = retry_run(run_dir, adjustments={"walltime_factor": 1.5})

    assert result.status is ActionStatus.PRECONDITION_FAILED
    assert "Max attempts" in result.message


def test_plan_retry_records_partial_outputs_without_reset(tmp_path: Path) -> None:
    run_dir = tmp_path / "R20260507-0001"
    _write_manifest(
        run_dir,
        {
            "run": {
                "id": "R20260507-0001",
                "status": "failed",
                "failure_reason": "timeout",
            },
            "job": {"job_id": "123", "attempt": 1},
            "simulator": {"name": "emses", "adapter": "emses"},
        },
    )
    (run_dir / "work").mkdir(exist_ok=True)
    (run_dir / "work" / "ex00_0000.h5").write_bytes(b"")

    result = plan_retry(run_dir, adjustments={"walltime": "24:00:00"}, note="timeout")

    assert result.status is ActionStatus.SUCCESS
    from runops.core.manifest import read_manifest

    updated = read_manifest(run_dir)
    assert updated.run["status"] == "failed"
    assert updated.run["retry_status"] == "retry_planned"
    assert updated.run["partial_outputs"] == {"hdf5_fields": 1}
    assert updated.job["next_attempt"] == 2


def test_add_fact_supports_superseding_fact(tmp_path: Path) -> None:
    first = add_fact(tmp_path, claim="initial fact")
    second = add_fact(tmp_path, claim="revised fact", supersedes="f001")

    assert first.status is ActionStatus.SUCCESS
    assert second.status is ActionStatus.SUCCESS

    facts = load_facts(tmp_path)
    assert [fact.id for fact in facts] == ["f001", "f002"]
    assert facts[1].supersedes == "f001"


def test_promote_fact_promotes_candidate_fact(tmp_path: Path) -> None:
    candidate_dir = tmp_path / ".runops" / "knowledge" / "candidates" / "facts"
    candidate_dir.mkdir(parents=True, exist_ok=True)
    (candidate_dir / "shared.toml").write_text(
        "[transport]\n"
        'source = "shared"\n'
        'kind = "project"\n'
        "\n"
        "[[facts]]\n"
        'id = "f004"\n'
        'claim = "keep dt below 1.0"\n'
        'fact_type = "constraint"\n'
        'confidence = "high"\n',
        encoding="utf-8",
    )

    result = promote_fact(tmp_path, "shared:f004")

    assert result.status is ActionStatus.SUCCESS
    facts = load_facts(tmp_path)
    assert [fact.id for fact in facts] == ["f001"]
    assert facts[0].evidence_ref == "fact:shared:f004"


def test_save_insight_writes_markdown_with_metadata(tmp_path: Path) -> None:
    result = save_insight(
        tmp_path,
        name="emses_cfl",
        content="dt must stay below the CFL limit",
        insight_type="constraint",
        simulator="emses",
        tags=["stability", "cfl"],
    )

    assert result.status is ActionStatus.SUCCESS
    saved_path = Path(result.data["path"])
    assert saved_path.exists()
    assert saved_path.name == "emses_cfl.md"

    insights = list_insights(tmp_path, simulator="emses", insight_type="constraint")
    assert len(insights) == 1
    assert insights[0].name == "emses_cfl"
    assert insights[0].tags == ["stability", "cfl"]
    assert insights[0].content == "dt must stay below the CFL limit"


def test_purge_work_removes_work_artifacts_and_updates_state(tmp_path: Path) -> None:
    run_dir = tmp_path / "R20260330-0001"
    _write_manifest(
        run_dir,
        {
            "run": {
                "id": "R20260330-0001",
                "status": "archived",
            }
        },
    )
    for dirname in ("outputs", "restart", "tmp"):
        target = run_dir / "work" / dirname
        target.mkdir(parents=True, exist_ok=True)
        (target / "data.bin").write_bytes(b"x" * 128)

    result = purge_work(run_dir)

    assert result.status is ActionStatus.SUCCESS
    assert result.state_before == "archived"
    assert result.state_after == "purged"
    assert sorted(result.data["removed_dirs"]) == ["outputs", "restart", "tmp"]
    assert result.data["bytes_removed"] == 384
    assert not (run_dir / "work" / "outputs").exists()
    assert (run_dir / "status" / "state.json").exists()


def test_submit_run_updates_manifest_and_state_file(tmp_path: Path) -> None:
    run_dir = tmp_path / "R20260330-0001"
    _write_manifest(
        run_dir,
        {
            "run": {
                "id": "R20260330-0001",
                "status": "created",
                "last_slurm_state": "COMPLETED",
            },
            "job": {
                "partition": "debug",
            },
        },
    )
    (run_dir / "submit").mkdir(parents=True, exist_ok=True)
    (run_dir / "submit" / "job.sh").write_text(
        "#!/bin/bash\n#SBATCH --job-name=test\necho hello\n",
        encoding="utf-8",
    )
    (run_dir / "input").mkdir(parents=True, exist_ok=True)
    (run_dir / "input" / "params.json").write_text("{}", encoding="utf-8")

    with patch("runops.slurm.submit.sbatch_submit", return_value="12345"):
        result = submit_run(run_dir)

    assert result.status is ActionStatus.SUCCESS
    assert result.data["job_id"] == "12345"
    assert (run_dir / "status" / "state.json").exists()

    from runops.core.manifest import read_manifest

    updated = read_manifest(run_dir)
    assert updated.run["last_slurm_state"] == ""


def test_submit_run_rejects_empty_input_dir(tmp_path: Path) -> None:
    run_dir = tmp_path / "R20260330-0001"
    _write_manifest(
        run_dir,
        {
            "run": {
                "id": "R20260330-0001",
                "status": "created",
            }
        },
    )
    (run_dir / "submit").mkdir(parents=True, exist_ok=True)
    (run_dir / "submit" / "job.sh").write_text(
        "#!/bin/bash\n#SBATCH --job-name=test\necho hello\n",
        encoding="utf-8",
    )
    (run_dir / "input").mkdir(parents=True, exist_ok=True)

    result = submit_run(run_dir)

    assert result.status is ActionStatus.PRECONDITION_FAILED
    assert "input/" in result.message


def test_execute_action_submit_run_updates_manifest_and_passes_options(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "R20260330-0001"
    _write_manifest(
        run_dir,
        {
            "run": {
                "id": "R20260330-0001",
                "status": "created",
            },
            "job": {
                "partition": "debug",
            },
        },
    )
    (run_dir / "submit").mkdir(parents=True, exist_ok=True)
    (run_dir / "submit" / "job.sh").write_text(
        "#!/bin/bash\n#SBATCH --job-name=test\necho hello\n",
        encoding="utf-8",
    )
    (run_dir / "input").mkdir(parents=True, exist_ok=True)
    (run_dir / "input" / "params.json").write_text("{}", encoding="utf-8")
    (run_dir / "work").mkdir(parents=True, exist_ok=True)

    with patch(
        "runops.slurm.submit.sbatch_submit", return_value="12345"
    ) as mock_submit:
        result = execute_action(
            "submit_run",
            run_dir=run_dir,
            queue_name="compute",
            qos="debugqos",
            afterok="67890",
        )

    assert result.status is ActionStatus.SUCCESS
    assert result.data["job_id"] == "12345"
    mock_submit.assert_called_once()
    assert mock_submit.call_args.args[0] == run_dir / "submit" / "job.sh"
    assert mock_submit.call_args.args[1] == run_dir / "work"
    assert mock_submit.call_args.kwargs["extra_args"] == [
        "--partition=compute",
        "--qos=debugqos",
    ]
    assert mock_submit.call_args.kwargs["afterok"] == "67890"

    from runops.core.manifest import read_manifest

    updated = read_manifest(run_dir)
    assert updated.run["status"] == "submitted"
    assert updated.job["job_id"] == "12345"
    assert updated.job["queue"] == "compute"
    assert updated.job["partition"] == "compute"
    assert updated.job["qos"] == "debugqos"
    assert updated.job["afterok"] == "67890"
    assert updated.job["attempts"][0]["partition"] == "compute"
    assert updated.job["attempts"][0]["qos"] == "debugqos"
    assert updated.job["attempts"][0]["afterok"] == "67890"
    assert (run_dir / "status" / "state.json").exists()


def test_execute_action_sync_run_updates_manifest_and_state_file(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "R20260330-0001"
    _write_manifest(
        run_dir,
        {
            "run": {
                "id": "R20260330-0001",
                "status": "submitted",
            },
            "job": {
                "job_id": "12345",
            },
        },
    )

    with patch(
        "runops.slurm.query.query_job_status",
        return_value=JobStatus(run_state=RunState.RUNNING, slurm_state="RUNNING"),
    ):
        result = execute_action("sync_run", run_dir=run_dir)

    assert result.status is ActionStatus.SUCCESS
    assert result.state_before == "submitted"
    assert result.state_after == "running"
    assert result.data["slurm_state"] == "RUNNING"

    from runops.core.manifest import read_manifest

    updated = read_manifest(run_dir)
    assert updated.run["status"] == "running"
    assert updated.run["last_slurm_state"] == "RUNNING"
    assert (run_dir / "status" / "state.json").exists()


def test_execute_action_sync_run_refreshes_slurm_state_when_state_unchanged(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "R20260330-0001"
    _write_manifest(
        run_dir,
        {
            "run": {
                "id": "R20260330-0001",
                "status": "submitted",
                "last_slurm_state": "COMPLETED",
            },
            "job": {
                "job_id": "67890",
            },
        },
    )

    with patch(
        "runops.slurm.query.query_job_status",
        return_value=JobStatus(run_state=RunState.SUBMITTED, slurm_state="PENDING"),
    ):
        result = execute_action("sync_run", run_dir=run_dir)

    assert result.status is ActionStatus.SUCCESS
    assert result.state_before == "submitted"
    assert result.state_after == "submitted"
    assert result.data["slurm_state"] == "PENDING"

    from runops.core.manifest import read_manifest

    updated = read_manifest(run_dir)
    assert updated.run["status"] == "submitted"
    assert updated.run["last_slurm_state"] == "PENDING"


def test_execute_action_cancel_run_scancels_and_syncs_manifest(tmp_path: Path) -> None:
    run_dir = tmp_path / "R20260330-0001"
    _write_manifest(
        run_dir,
        {
            "run": {
                "id": "R20260330-0001",
                "status": "running",
            },
            "job": {
                "job_id": "98765",
            },
        },
    )

    with (
        patch("runops.slurm.submit.scancel_job") as mock_scancel,
        patch(
            "runops.slurm.query.query_job_status",
            return_value=JobStatus(
                run_state=RunState.CANCELLED,
                slurm_state="CANCELLED",
            ),
        ),
    ):
        result = execute_action("cancel_run", run_dir=run_dir)

    assert result.status is ActionStatus.SUCCESS
    assert result.state_before == "running"
    assert result.state_after == "cancelled"
    mock_scancel.assert_called_once_with("98765")

    from runops.core.manifest import read_manifest

    updated = read_manifest(run_dir)
    assert updated.run["status"] == "cancelled"
    assert updated.run["last_slurm_state"] == "CANCELLED"
    assert (run_dir / "status" / "state.json").exists()


def test_execute_action_delete_run_removes_directory(tmp_path: Path) -> None:
    run_dir = tmp_path / "R20260330-0001"
    _write_manifest(
        run_dir,
        {
            "run": {
                "id": "R20260330-0001",
                "status": "failed",
            }
        },
    )
    artifact = run_dir / "work" / "outputs" / "data.bin"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(b"x" * 256)

    result = execute_action("delete_run", run_dir=run_dir)

    assert result.status is ActionStatus.SUCCESS
    assert result.data["run_id"] == "R20260330-0001"
    assert result.data["bytes_removed"] >= 256
    assert not run_dir.exists()
