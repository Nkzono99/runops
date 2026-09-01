"""Tests for agent-facing action helpers."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from pathlib import Path
from threading import Event
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import tomli as tomllib
import tomli_w

from runops.application.actions import (
    ActionStatus,
    add_fact,
    archive_bundle,
    archive_run,
    collect_survey,
    create_survey,
    execute_action,
    export_publication,
    plan_bundle_archive,
    plan_retry,
    plan_survey,
    promote_fact,
    purge_work,
    restore_bundle,
    restore_run,
    retry_run,
    save_insight,
    submit_run,
    summarize_run,
)
from runops.application.actions import (
    create_run as create_run_action,
)
from runops.application.execution.readiness import (
    probe_run_readiness,
    write_readiness_cache,
)
from runops.application.experiments import create_experiment
from runops.application.research import (
    EvidenceRequest,
    create_result,
    result_mutation_guard,
    seal_result,
)
from runops.application.run_creation.workflow import directory_content_hash
from runops.core.exceptions import ManifestError, SimctlError
from runops.core.knowledge import list_insights, load_facts
from runops.core.manifest import read_manifest, update_manifest
from runops.core.state import RunState
from runops.slurm.query import JobStatus

ADAPTER_PATCH = "runops.application.analysis.workflow.get_adapter"


def test_application_actions_expose_registered_actions() -> None:
    from runops.application import actions

    assert set(actions.ACTION_SPECS) == set(actions._DISPATCH)
    assert callable(actions.submit_run)


def _write_manifest(run_dir: Path, data: dict[str, Any]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    with open(run_dir / "manifest.toml", "wb") as f:
        tomli_w.dump(data, f)


def _write_sealable_archived_run(root: Path, run_id: str) -> Path:
    """Create reviewed, reproducible Run evidence for purge protection tests."""
    run_dir = root / "runs" / run_id
    input_dir = run_dir / "input"
    input_dir.mkdir(parents=True)
    (input_dir / "params.toml").write_text("nx = 64\n", encoding="utf-8")
    _write_manifest(
        run_dir,
        {
            "run": {"id": run_id, "status": "archived"},
            "origin": {"case": "base"},
            "simulator": {"name": "generic"},
            "launcher": {"name": "srun"},
            "simulator_source": {
                "git_commit": "abc123",
                "git_dirty": False,
                "git_state_observed": True,
                "exe_hash": "sha256:" + "a" * 64,
                "package_version": "1.0.0",
            },
            "job": {"scheduler": "slurm"},
            "params_snapshot": {},
            "files": {"input_dir": "input"},
            "intent": {
                "experiment_id": "E20260901-0001",
                "baseline_reason": "standalone purge protection fixture",
            },
            "identity": {
                "condition_hash": "sha256:" + "b" * 64,
                "input_hash": directory_content_hash(input_dir),
                "execution_hash": "sha256:" + "c" * 64,
                "provenance_hash": "sha256:" + "d" * 64,
            },
            "curation": {
                "review_status": "reviewed",
                "reviewed_at": "2026-09-01T00:00:00+00:00",
                "reviewed_by": "human",
                "reason": "accepted for Result evidence",
            },
            "storage": {"tier": "cold", "form": "full"},
        },
    )
    return run_dir


def _seal_run_output_result(root: Path, output: Path) -> Path:
    created = create_result(root, "Protected output")
    seal_result(
        root,
        created.result_id,
        claim="The selected output supports the claim.",
        outcome="supported",
        evidence=(
            EvidenceRequest.path(
                output.relative_to(root).as_posix(),
                role="evidence",
                reason="Selected quantitative evidence.",
            ),
        ),
    )
    return created.path


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


def test_create_run_action_reports_completed_duplicate_as_reused(
    tmp_path: Path,
) -> None:
    _create_project_with_case(tmp_path)
    first = create_run_action(tmp_path, "my_case")
    update_manifest(Path(first.data["run_dir"]), {"run": {"status": "completed"}})
    ledger = tmp_path / ".runops" / "run-id-sequence.toml"
    sequence_before = ledger.read_bytes()

    second = create_run_action(tmp_path, "my_case")

    assert second.status is ActionStatus.SUCCESS
    assert second.data["reused"] is True
    assert second.data["run_id"] == first.data["run_id"]
    assert second.state_after == ""
    assert second.message.startswith("Reused equivalent Run")
    assert ledger.read_bytes() == sequence_before


def test_plan_survey_is_read_only_and_create_survey_requires_selection(
    tmp_path: Path,
) -> None:
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
        'phase = "pilot"\n'
        "\n"
        "[intent]\n"
        'purpose = "explore"\n'
        "\n"
        "[budget]\n"
        "max_materialized_runs = 2\n"
        "max_core_hours = 10.0\n"
        "\n"
        "[axes]\n"
        "nx = [32, 64]\n"
        "ny = [16, 32]\n"
        "\n"
        "[naming]\n"
        'display_name = "nx{nx}_ny{ny}"\n',
        encoding="utf-8",
    )

    planned = plan_survey(tmp_path, survey_dir, limit=2)

    assert planned.status is ActionStatus.SUCCESS
    assert planned.data["candidate_count"] == 4
    assert len(planned.data["points"]) == 2
    assert list(survey_dir.glob("*/manifest.toml")) == []
    assert not (tmp_path / ".runops" / "run-id-sequence.toml").exists()

    result = create_survey(
        tmp_path,
        survey_dir,
        expected_plan_hash=str(planned.data["plan_hash"]),
        point_refs=("p0002",),
    )

    assert result.status is ActionStatus.SUCCESS
    assert result.state_after == "created"
    assert result.data["created_count"] == 1
    assert result.data["reused_count"] == 0
    assert [run["ref"] for run in result.data["runs"]] == ["p0002"]


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
    (run_dir / "submit").mkdir()
    (run_dir / "submit" / "job.sh").write_text(
        "#!/bin/bash\n#SBATCH --job-name=retry\n",
        encoding="utf-8",
    )
    (run_dir / "input").mkdir()
    (run_dir / "input" / "params.toml").write_text(
        "nx = 16\n",
        encoding="utf-8",
    )
    (run_dir / ".runops-submit.lock").write_text(
        "accepted:12345\n",
        encoding="utf-8",
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

    from runops.application.execution.submission import SubmitRequest, plan_submit

    retry_plan = plan_submit(SubmitRequest(run_dir=run_dir))
    assert retry_plan.ready is True
    assert retry_plan.job_id_before == ""
    assert retry_plan.claim_before == ""
    assert (run_dir / ".runops-submit.lock").read_text(encoding="utf-8") == ""

    state_file = run_dir / "status" / "state.json"
    assert state_file.exists()
    with open(state_file, encoding="utf-8") as f:
        state_data = json.load(f)
    assert state_data["state"] == "created"
    assert state_data["previous_state"] == "cancelled"
    assert state_data["reason"] == "retry"


def test_retry_run_claim_clear_failure_remains_fail_closed(tmp_path: Path) -> None:
    run_dir = tmp_path / "R20260418-0002"
    _write_manifest(
        run_dir,
        {
            "run": {"id": run_dir.name, "status": "cancelled"},
            "job": {"attempt": 1, "job_id": "12345"},
        },
    )
    (run_dir / ".runops-submit.lock").write_text(
        "accepted:12345\n",
        encoding="utf-8",
    )

    with patch(
        "runops.application.execution.submission.os.fsync",
        side_effect=OSError("claim clear failed"),
    ):
        result = retry_run(run_dir)

    assert result.status is ActionStatus.ERROR
    assert "claim clear failed" in result.message
    assert (run_dir / ".runops-submit.lock").read_text(encoding="utf-8") == (
        "accepted:12345\n"
    )

    from runops.core.manifest import read_manifest

    unchanged = read_manifest(run_dir)
    assert unchanged.run["status"] == "cancelled"
    assert unchanged.job["job_id"] == "12345"

    from runops.application.execution.submission import SubmitRequest, plan_submit

    plan = plan_submit(SubmitRequest(run_dir=run_dir))
    claim_check = next(
        check for check in plan.preconditions if check.name == "submission_claim_empty"
    )
    assert claim_check.passed is False


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

    blocked = purge_work(run_dir)

    assert blocked.status is ActionStatus.PRECONDITION_FAILED
    assert blocked.data["readiness"] is None
    assert blocked.data["recommended_action"] == "analyze_outputs"
    assert (run_dir / "work" / "outputs").is_dir()

    result = purge_work(
        run_dir,
        discard_incomplete=True,
        review_reason="No readiness record exists; outputs are disposable scratch.",
    )

    assert result.status is ActionStatus.SUCCESS
    assert result.state_before == "archived"
    assert result.state_after == "purged"
    assert sorted(result.data["removed_dirs"]) == ["outputs", "restart", "tmp"]
    assert result.data["bytes_removed"] == 384
    assert not (run_dir / "work" / "outputs").exists()
    assert (run_dir / "status" / "state.json").exists()
    updated = read_manifest(run_dir)
    assert updated.run["readiness_disposition"] == "discarded_incomplete"


@pytest.mark.parametrize("failure_phase", ["staging", "metadata"])
def test_purge_discard_review_rolls_back_with_data_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_phase: str,
) -> None:
    from runops.application.actions import admin as admin_module

    run_dir = tmp_path / "R20260330-0009"
    _write_manifest(
        run_dir,
        {"run": {"id": run_dir.name, "status": "archived"}},
    )
    output = run_dir / "work" / "outputs" / "data.bin"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"evidence")
    manifest_before = (run_dir / "manifest.toml").read_bytes()

    if failure_phase == "staging":
        monkeypatch.setattr(
            admin_module,
            "move_directory_noreplace",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                OSError("injected staging failure")
            ),
        )
    else:
        from runops.core import manifest as manifest_module

        real_write_manifest = manifest_module.write_manifest
        write_calls = 0

        def fail_metadata_once(path: Path, manifest: Any, **kwargs: Any) -> Any:
            nonlocal write_calls
            write_calls += 1
            if write_calls == 1:
                raise OSError("injected metadata failure")
            return real_write_manifest(path, manifest, **kwargs)

        monkeypatch.setattr(
            manifest_module,
            "write_manifest",
            fail_metadata_once,
        )

    result = purge_work(
        run_dir,
        discard_incomplete=True,
        review_reason="Explicitly discard unknown readiness for test.",
    )

    assert result.status is ActionStatus.ERROR
    assert output.read_bytes() == b"evidence"
    assert (run_dir / "manifest.toml").read_bytes() == manifest_before


def test_purge_work_gates_known_incomplete_readiness(tmp_path: Path) -> None:
    run_dir = tmp_path / "R20260330-0002"
    _write_manifest(
        run_dir,
        {
            "run": {"id": "R20260330-0002", "status": "completed"},
            "job": {"job_id": "12345", "attempt": 1},
            "simulator": {"name": "emses", "adapter": "emses"},
        },
    )
    (run_dir / "input").mkdir()
    with (run_dir / "input" / "plasma.toml").open("wb") as stream:
        tomli_w.dump({"jobcon": {"nstep": 100}}, stream)
    (run_dir / "work").mkdir()
    (run_dir / "work" / "energy").write_text("100 1.0 2.0\n", encoding="utf-8")
    manifest = read_manifest(run_dir)
    write_readiness_cache(
        run_dir,
        probe_run_readiness(run_dir, manifest=manifest),
        manifest=manifest,
    )
    update_manifest(run_dir, {"run": {"status": "archived"}})
    (run_dir / "work" / "outputs").mkdir()

    blocked = purge_work(run_dir)

    assert blocked.status is ActionStatus.PRECONDITION_FAILED
    assert blocked.data["recommended_action"] == "review_outputs"
    assert (run_dir / "work" / "outputs").exists()

    accepted = purge_work(
        run_dir,
        discard_incomplete=True,
        review_reason="outputs are unusable and will be regenerated",
    )

    assert accepted.status is ActionStatus.SUCCESS
    updated = read_manifest(run_dir)
    assert updated.run["readiness_disposition"] == "discarded_incomplete"
    assert updated.run["readiness_review_reason"] == (
        "outputs are unusable and will be regenerated"
    )


def test_purge_work_blocks_run_paths_included_by_a_sealed_result(
    tmp_path: Path,
) -> None:
    (tmp_path / "runops.toml").write_text(
        '[project]\nname = "result-protection"\n',
        encoding="utf-8",
    )
    run_id = "R20260330-0003"
    run_dir = _write_sealable_archived_run(tmp_path, run_id)
    output = run_dir / "work" / "outputs" / "summary.csv"
    output.parent.mkdir(parents=True)
    output.write_text("value\n1\n", encoding="utf-8")
    result_dir = _seal_run_output_result(tmp_path, output)

    blocked = purge_work(run_dir)

    assert blocked.status is ActionStatus.PRECONDITION_FAILED
    assert blocked.data["protected_by_results"] == [result_dir.name]
    assert output.is_file()
    assert read_manifest(run_dir).storage["protected_by_results"] == [result_dir.name]


def test_purge_work_fails_closed_when_sealed_result_selection_is_tampered(
    tmp_path: Path,
) -> None:
    (tmp_path / "runops.toml").write_text(
        '[project]\nname = "tampered-result-protection"\n',
        encoding="utf-8",
    )
    run_id = "R20260330-0005"
    run_dir = _write_sealable_archived_run(tmp_path, run_id)
    output = run_dir / "work" / "outputs" / "summary.csv"
    output.parent.mkdir(parents=True)
    output.write_text("value\n1\n", encoding="utf-8")
    result_dir = _seal_run_output_result(tmp_path, output)
    manifest_path = result_dir / "manifest.toml"
    sealed = manifest_path.read_text(encoding="utf-8")
    tampered = sealed.replace('disposition = "include"', 'disposition = "exclude"')
    assert tampered != sealed
    manifest_path.write_text(tampered, encoding="utf-8")

    blocked = purge_work(
        run_dir,
        discard_incomplete=True,
        review_reason="Tampered Result must not permit deletion.",
    )

    assert blocked.status is ActionStatus.PRECONDITION_FAILED
    assert "cannot verify sealed Result protections" in blocked.message
    assert "sealed_content_changed" in blocked.message
    assert output.is_file()
    assert read_manifest(run_dir).run["status"] == "archived"


def test_purge_work_serializes_with_result_sealing(tmp_path: Path) -> None:
    (tmp_path / "runops.toml").write_text(
        '[project]\nname = "result-race"\n',
        encoding="utf-8",
    )
    run_dir = tmp_path / "runs" / "R20260330-0004"
    _write_manifest(
        run_dir,
        {"run": {"id": "R20260330-0004", "status": "archived"}},
    )
    output = run_dir / "work" / "outputs" / "summary.csv"
    output.parent.mkdir(parents=True)
    output.write_text("value\n1\n", encoding="utf-8")
    entered = Event()

    from runops.application.actions import admin as admin_module

    real_find_project = admin_module._find_project_root_or_none

    def signalled_find_project(path: Path) -> Path | None:
        entered.set()
        return real_find_project(path)

    with patch.object(  # noqa: SIM117 - Result guard must release before future.result
        admin_module,
        "_find_project_root_or_none",
        side_effect=signalled_find_project,
    ):
        with ThreadPoolExecutor(max_workers=1) as pool:
            with result_mutation_guard(tmp_path):
                future = pool.submit(
                    purge_work,
                    run_dir,
                    discard_incomplete=True,
                    review_reason="Result-lock serialization test.",
                )
                assert entered.wait(timeout=2)
                with pytest.raises(FutureTimeoutError):
                    future.result(timeout=0.1)
                assert output.is_file()

            purged = future.result(timeout=2)

    assert purged.status is ActionStatus.SUCCESS
    assert not output.exists()


@pytest.mark.parametrize("unsafe_kind", ["symlink", "hardlink"])
def test_purge_work_fails_closed_on_unsafe_result_registry_manifest(
    tmp_path: Path,
    unsafe_kind: str,
) -> None:
    (tmp_path / "runops.toml").write_text(
        '[project]\nname = "unsafe-result-registry"\n',
        encoding="utf-8",
    )
    run_dir = tmp_path / "runs" / "R20260330-0006"
    _write_manifest(
        run_dir,
        {"run": {"id": run_dir.name, "status": "archived"}},
    )
    output = run_dir / "work" / "outputs" / "summary.csv"
    output.parent.mkdir(parents=True)
    output.write_text("value\n1\n", encoding="utf-8")
    external = tmp_path / "external-result.toml"
    external.write_text("[result]\nid = 'R0001-unsafe'\n", encoding="utf-8")
    result_dir = tmp_path / "research" / "results" / "R0001-unsafe"
    result_dir.mkdir(parents=True)
    manifest_path = result_dir / "manifest.toml"
    if unsafe_kind == "symlink":
        manifest_path.symlink_to(external)
    else:
        os.link(external, manifest_path)

    result = purge_work(run_dir)

    assert result.status is ActionStatus.PRECONDITION_FAILED
    assert "cannot verify sealed Result protections" in result.message
    assert output.is_file()


def test_purge_work_fails_closed_on_result_directory_without_manifest(
    tmp_path: Path,
) -> None:
    (tmp_path / "runops.toml").write_text(
        '[project]\nname = "missing-result-manifest"\n',
        encoding="utf-8",
    )
    run_dir = tmp_path / "runs" / "R20260330-0007"
    _write_manifest(
        run_dir,
        {"run": {"id": run_dir.name, "status": "archived"}},
    )
    output = run_dir / "work" / "outputs" / "summary.csv"
    output.parent.mkdir(parents=True)
    output.write_text("value\n1\n", encoding="utf-8")
    (tmp_path / "research" / "results" / "R0001-missing").mkdir(parents=True)

    result = purge_work(run_dir)

    assert result.status is ActionStatus.PRECONDITION_FAILED
    assert "cannot verify sealed Result protections" in result.message
    assert "missing or unreadable" in result.message
    assert output.is_file()


def test_purge_work_rolls_back_all_targets_when_staging_fails(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "R20260330-0007"
    _write_manifest(
        run_dir,
        {"run": {"id": run_dir.name, "status": "archived"}},
    )
    for dirname in ("outputs", "restart"):
        target = run_dir / "work" / dirname
        target.mkdir(parents=True)
        (target / "data.bin").write_bytes(dirname.encode())

    from runops.application.actions import admin as admin_module

    real_move = admin_module.move_directory_noreplace
    calls = 0

    def fail_second_move(source: Path, destination: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected staging failure")
        real_move(source, destination)

    with patch.object(
        admin_module,
        "move_directory_noreplace",
        side_effect=fail_second_move,
    ):
        result = purge_work(
            run_dir,
            discard_incomplete=True,
            review_reason="Injected staging failure test.",
        )

    assert result.status is ActionStatus.ERROR
    assert "injected staging failure" in result.message
    assert read_manifest(run_dir).run["status"] == "archived"
    assert (run_dir / "work" / "outputs" / "data.bin").read_bytes() == b"outputs"
    assert (run_dir / "work" / "restart" / "data.bin").read_bytes() == b"restart"
    assert not list((run_dir / "work").glob(".delete-purge-*"))


def test_purge_work_rolls_back_data_and_metadata_when_commit_fails(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "R20260330-0008"
    _write_manifest(
        run_dir,
        {
            "run": {"id": run_dir.name, "status": "archived"},
            "storage": {"tier": "cold", "form": "full"},
        },
    )
    output = run_dir / "work" / "outputs" / "data.bin"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"preserve")

    from runops.core import manifest as manifest_module

    real_write = manifest_module.write_manifest
    calls = 0

    def fail_commit_once(path: Path, manifest: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ManifestError("injected metadata failure")
        return real_write(path, manifest, **kwargs)

    with patch.object(
        manifest_module,
        "write_manifest",
        side_effect=fail_commit_once,
    ):
        result = purge_work(
            run_dir,
            discard_incomplete=True,
            review_reason="Injected metadata failure test.",
        )

    assert result.status is ActionStatus.ERROR
    assert "injected metadata failure" in result.message
    assert output.read_bytes() == b"preserve"
    manifest = read_manifest(run_dir)
    assert manifest.run["status"] == "archived"
    assert manifest.storage == {"tier": "cold", "form": "full"}
    assert not (run_dir / "status" / "state.json").exists()
    assert not list((run_dir / "work").glob(".delete-purge-*"))


def test_purge_work_refuses_synchronous_rollback_after_staged_tree_drift(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "R20260330-0026"
    _write_manifest(
        run_dir,
        {"run": {"id": run_dir.name, "status": "archived"}},
    )
    for dirname in ("outputs", "restart"):
        target = run_dir / "work" / dirname
        target.mkdir(parents=True)
        (target / "data.bin").write_bytes(dirname.encode())

    from runops.application.actions import admin as admin_module

    real_move = admin_module.move_directory_noreplace
    calls = 0

    def drift_then_fail(source: Path, destination: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            staged = destination.parent / "outputs" / "data.bin"
            staged.write_bytes(b"replacement after receipt")
            raise OSError("injected staging failure after drift")
        real_move(source, destination)

    with patch.object(
        admin_module,
        "move_directory_noreplace",
        side_effect=drift_then_fail,
    ):
        result = purge_work(
            run_dir,
            discard_incomplete=True,
            review_reason="Exercise synchronous staged digest gate.",
        )

    assert result.status is ActionStatus.ERROR
    assert "rollback failed" in result.message
    assert "digest" in result.message
    tombstone = next((run_dir / "work").glob(".delete-purge-*"))
    assert (tombstone / "outputs" / "data.bin").read_bytes() == (
        b"replacement after receipt"
    )
    assert (run_dir / "work" / "restart" / "data.bin").read_bytes() == b"restart"
    assert (run_dir / "status" / ".purge-pending.json").is_file()


def test_purge_work_refuses_synchronous_rollback_after_manifest_drift(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "R20260330-0027"
    _write_manifest(
        run_dir,
        {"run": {"id": run_dir.name, "status": "archived"}},
    )
    output = run_dir / "work" / "outputs" / "data.bin"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"preserve in tombstone")

    from runops.core import manifest as manifest_module

    real_write = manifest_module.write_manifest

    def drift_then_fail(path: Path, manifest: Any, **kwargs: Any) -> Any:
        current = read_manifest(path)
        current.run["display_name"] = "changed after purge receipt"
        real_write(path, current, **kwargs)
        raise ManifestError("injected commit failure after manifest drift")

    with patch.object(
        manifest_module,
        "write_manifest",
        side_effect=drift_then_fail,
    ):
        result = purge_work(
            run_dir,
            discard_incomplete=True,
            review_reason="Exercise synchronous manifest digest gate.",
        )

    assert result.status is ActionStatus.ERROR
    assert "automatic rollback was not completed" in result.message
    assert "manifest digest" in result.message
    manifest = read_manifest(run_dir)
    assert manifest.run["status"] == "archived"
    assert manifest.run["display_name"] == "changed after purge receipt"
    tombstone = next((run_dir / "work").glob(".delete-purge-*"))
    assert (tombstone / "outputs" / "data.bin").read_bytes() == (
        b"preserve in tombstone"
    )
    assert (run_dir / "status" / ".purge-pending.json").is_file()


def test_purge_work_commits_when_tombstone_cleanup_fails(tmp_path: Path) -> None:
    run_dir = tmp_path / "R20260330-0009"
    _write_manifest(
        run_dir,
        {"run": {"id": run_dir.name, "status": "archived"}},
    )
    output = run_dir / "work" / "outputs" / "data.bin"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"staged")

    from runops.application.actions import admin as admin_module

    with patch.object(
        admin_module.shutil,
        "rmtree",
        side_effect=OSError("injected cleanup failure"),
    ):
        result = purge_work(
            run_dir,
            discard_incomplete=True,
            review_reason="Injected cleanup failure test.",
        )

    assert result.status is ActionStatus.SUCCESS
    assert result.state_after == "purged"
    assert result.data["bytes_removed"] == 0
    assert result.data["cleanup_pending"]
    assert not output.exists()
    tombstone = Path(str(result.data["cleanup_pending"]))
    assert (tombstone / "outputs" / "data.bin").read_bytes() == b"staged"
    manifest = read_manifest(run_dir)
    assert manifest.run["status"] == "purged"
    assert manifest.storage["form"] == "compacted"


def test_purge_work_resumes_after_partial_tombstone_cleanup_failure(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "R20260330-0028"
    _write_manifest(
        run_dir,
        {"run": {"id": run_dir.name, "status": "archived"}},
    )
    output_dir = run_dir / "work" / "outputs"
    output_dir.mkdir(parents=True)
    (output_dir / "removed-before-error.bin").write_bytes(b"first")
    (output_dir / "retained-after-error.bin").write_bytes(b"second")

    from runops.application.actions import admin as admin_module

    def partially_remove_then_fail(path: Path, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        tombstone = Path(path)
        (tombstone / "outputs" / "removed-before-error.bin").unlink()
        raise OSError("injected failure after partial cleanup")

    with patch.object(
        admin_module.shutil,
        "rmtree",
        side_effect=partially_remove_then_fail,
    ):
        first = purge_work(
            run_dir,
            discard_incomplete=True,
            review_reason="Exercise partial cleanup recovery.",
        )

    assert first.status is ActionStatus.SUCCESS
    assert first.data["cleanup_pending"]
    receipt = run_dir / "status" / ".purge-pending.json"
    tombstone = next((run_dir / "work").glob(".delete-purge-*"))
    assert not (tombstone / "outputs" / "removed-before-error.bin").exists()
    assert (tombstone / "outputs" / "retained-after-error.bin").is_file()

    resumed = purge_work(run_dir)

    assert resumed.status is ActionStatus.SUCCESS
    assert resumed.state_after == "purged"
    assert not receipt.exists()
    assert not tombstone.exists()


def test_purge_work_rejects_replaced_target_after_partial_cleanup(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "R20260330-0029"
    _write_manifest(
        run_dir,
        {"run": {"id": run_dir.name, "status": "archived"}},
    )
    output_dir = run_dir / "work" / "outputs"
    output_dir.mkdir(parents=True)
    (output_dir / "removed-before-error.bin").write_bytes(b"first")
    (output_dir / "retained-after-error.bin").write_bytes(b"second")

    from runops.application.actions import admin as admin_module

    def partially_remove_then_fail(path: Path, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        tombstone = Path(path)
        (tombstone / "outputs" / "removed-before-error.bin").unlink()
        raise OSError("injected failure after partial cleanup")

    with patch.object(
        admin_module.shutil,
        "rmtree",
        side_effect=partially_remove_then_fail,
    ):
        first = purge_work(
            run_dir,
            discard_incomplete=True,
            review_reason="Exercise replacement-safe cleanup recovery.",
        )

    assert first.status is ActionStatus.SUCCESS
    tombstone = next((run_dir / "work").glob(".delete-purge-*"))
    original = tombstone / "outputs"
    preserved = tmp_path / "preserved-original-output"
    original.rename(preserved)
    original.mkdir()
    (original / "retained-after-error.bin").write_bytes(b"second")

    blocked = purge_work(run_dir)

    assert blocked.status is ActionStatus.ERROR
    assert "target identity" in blocked.message
    assert (run_dir / "status" / ".purge-pending.json").is_file()
    assert original.is_dir()
    assert (preserved / "retained-after-error.bin").is_file()


def test_purge_work_continues_from_committed_move_after_fsync_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from runops.application.run_creation import staging as staging_module

    run_dir = tmp_path / "R20260330-0010"
    _write_manifest(
        run_dir,
        {"run": {"id": run_dir.name, "status": "archived"}},
    )
    output = run_dir / "work" / "outputs" / "data.bin"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"staged")
    real_rename = staging_module._rename_noreplace
    rename_calls = 0

    def fail_fsync(_path: Path) -> None:
        raise OSError("injected parent fsync failure")

    def fail_rollback(source: Path, destination: Path) -> None:
        nonlocal rename_calls
        rename_calls += 1
        if rename_calls == 2:
            raise OSError("injected rollback failure")
        real_rename(source, destination)

    monkeypatch.setattr(staging_module, "_fsync_directory", fail_fsync)
    monkeypatch.setattr(staging_module, "_rename_noreplace", fail_rollback)

    with pytest.warns(staging_module.MoveDurabilityWarning):
        result = purge_work(
            run_dir,
            discard_incomplete=True,
            review_reason="Injected fsync recovery test.",
        )

    assert result.status is ActionStatus.SUCCESS
    assert result.state_after == "purged"
    assert not output.exists()
    assert not list((run_dir / "work").glob(".delete-purge-*"))
    assert read_manifest(run_dir).run["status"] == "purged"


@pytest.mark.parametrize("interrupt_phase", ["move", "manifest", "cleanup"])
def test_purge_work_resumes_after_process_interruption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interrupt_phase: str,
) -> None:
    from runops.application.actions import admin as admin_module
    from runops.core import manifest as manifest_module

    suffix = {"move": "0011", "manifest": "0012", "cleanup": "0013"}[interrupt_phase]
    run_dir = tmp_path / f"R20260330-{suffix}"
    _write_manifest(
        run_dir,
        {"run": {"id": run_dir.name, "status": "archived"}},
    )
    output = run_dir / "work" / "outputs" / "data.bin"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"durable purge")
    interrupted = False

    if interrupt_phase == "move":
        real_move = admin_module.move_directory_noreplace

        def interrupt_after_move(source: Path, destination: Path) -> None:
            nonlocal interrupted
            real_move(source, destination)
            if not interrupted and source.name == "outputs":
                interrupted = True
                raise KeyboardInterrupt("injected after purge move")

        monkeypatch.setattr(
            admin_module,
            "move_directory_noreplace",
            interrupt_after_move,
        )
    elif interrupt_phase == "manifest":
        real_write = manifest_module.write_manifest

        def interrupt_after_manifest(path: Path, manifest: Any, **kwargs: Any) -> Any:
            nonlocal interrupted
            result = real_write(path, manifest, **kwargs)
            if not interrupted and manifest.run.get("status") == RunState.PURGED.value:
                interrupted = True
                raise KeyboardInterrupt("injected after purge manifest")
            return result

        monkeypatch.setattr(
            manifest_module,
            "write_manifest",
            interrupt_after_manifest,
        )
    else:
        real_rmtree = admin_module.shutil.rmtree

        def interrupt_before_cleanup(path: Path, *args: Any, **kwargs: Any) -> None:
            nonlocal interrupted
            if not interrupted and Path(path).name.startswith(".delete-purge-"):
                interrupted = True
                raise KeyboardInterrupt("injected before purge cleanup")
            real_rmtree(path, *args, **kwargs)

        monkeypatch.setattr(admin_module.shutil, "rmtree", interrupt_before_cleanup)

    with pytest.raises(KeyboardInterrupt, match="injected"):
        purge_work(
            run_dir,
            discard_incomplete=True,
            review_reason="Exercise durable purge recovery.",
        )

    receipt = run_dir / "status" / ".purge-pending.json"
    assert receipt.is_file()

    resumed = purge_work(
        run_dir,
        discard_incomplete=True,
        review_reason="Exercise durable purge recovery.",
    )

    assert resumed.status is ActionStatus.SUCCESS
    assert read_manifest(run_dir).run["status"] == "purged"
    assert not output.exists()
    assert not receipt.exists()
    assert not list((run_dir / "work").glob(".delete-purge-*"))


def test_purge_work_rejects_staged_data_changed_before_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from runops.application.actions import admin as admin_module

    run_dir = tmp_path / "R20260330-0018"
    _write_manifest(
        run_dir,
        {"run": {"id": run_dir.name, "status": "archived"}},
    )
    output = run_dir / "work" / "outputs" / "data.bin"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"original staged bytes")
    real_move = admin_module.move_directory_noreplace
    interrupted = False

    def interrupt_after_move(source: Path, destination: Path) -> None:
        nonlocal interrupted
        real_move(source, destination)
        if not interrupted and source.name == "outputs":
            interrupted = True
            raise KeyboardInterrupt("injected after purge move")

    monkeypatch.setattr(
        admin_module,
        "move_directory_noreplace",
        interrupt_after_move,
    )
    with pytest.raises(KeyboardInterrupt, match="injected"):
        purge_work(
            run_dir,
            discard_incomplete=True,
            review_reason="Exercise staged digest validation.",
        )
    monkeypatch.setattr(admin_module, "move_directory_noreplace", real_move)
    tombstone = next((run_dir / "work").glob(".delete-purge-*"))
    staged = tombstone / "outputs" / "data.bin"
    staged.write_bytes(b"replacement with same transaction topology")

    blocked = purge_work(run_dir)

    assert blocked.status is ActionStatus.ERROR
    assert "digest" in blocked.message
    assert read_manifest(run_dir).run["status"] == "archived"
    assert staged.is_file()
    assert (run_dir / "status" / ".purge-pending.json").is_file()


def test_purge_work_rejects_live_manifest_changed_after_commit_before_retry(
    tmp_path: Path,
) -> None:
    from runops.core import manifest as manifest_module

    run_dir = tmp_path / "R20260330-0019"
    _write_manifest(
        run_dir,
        {"run": {"id": run_dir.name, "status": "archived"}},
    )
    output = run_dir / "work" / "outputs" / "data.bin"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"committed staged bytes")
    real_write = manifest_module.write_manifest
    interrupted = False

    def interrupt_after_manifest(path: Path, manifest: Any, **kwargs: Any) -> Any:
        nonlocal interrupted
        result = real_write(path, manifest, **kwargs)
        if not interrupted and manifest.run.get("status") == RunState.PURGED.value:
            interrupted = True
            raise KeyboardInterrupt("injected after purge manifest")
        return result

    with (
        patch.object(
            manifest_module,
            "write_manifest",
            side_effect=interrupt_after_manifest,
        ),
        pytest.raises(KeyboardInterrupt, match="injected"),
    ):
        purge_work(
            run_dir,
            discard_incomplete=True,
            review_reason="Exercise live manifest digest validation.",
        )
    update_manifest(run_dir, {"run": {"display_name": "tampered after commit"}})

    blocked = purge_work(run_dir)

    assert blocked.status is ActionStatus.ERROR
    assert "manifest digest" in blocked.message
    assert read_manifest(run_dir).run["status"] == "purged"
    assert (run_dir / "status" / ".purge-pending.json").is_file()
    assert list((run_dir / "work").glob(".delete-purge-*"))


@pytest.mark.parametrize("parent_name", ["work", "status"])
def test_purge_work_rejects_redirected_parent_directories(
    tmp_path: Path,
    parent_name: str,
) -> None:
    run_dir = tmp_path / "R20260330-0014"
    _write_manifest(
        run_dir,
        {"run": {"id": run_dir.name, "status": "archived"}},
    )
    outside = tmp_path / f"outside-{parent_name}"
    outside.mkdir()
    (run_dir / parent_name).symlink_to(outside, target_is_directory=True)
    if parent_name == "work":
        output = outside / "outputs" / "data.bin"
        output.parent.mkdir()
        output.write_bytes(b"must survive")

    result = purge_work(
        run_dir,
        discard_incomplete=True,
        review_reason="Unsafe parent must be rejected.",
    )

    assert result.status is ActionStatus.PRECONDITION_FAILED
    assert "Purge parent must be a real directory" in result.message
    if parent_name == "work":
        assert (outside / "outputs" / "data.bin").read_bytes() == b"must survive"
    else:
        assert list(outside.iterdir()) == []


def test_purge_work_rejects_receipt_with_missing_tombstone_identity(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "R20260330-0015"
    _write_manifest(
        run_dir,
        {"run": {"id": run_dir.name, "status": "archived"}},
    )
    status_dir = run_dir / "status"
    status_dir.mkdir()
    receipt = status_dir / ".purge-pending.json"
    receipt.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "run_id": run_dir.name,
                "tombstone": "",
                "targets": ["outputs"],
                "bytes_staged": 1,
                "compacted_at": "2026-09-01T00:00:00+00:00",
                "review_updates": {},
                "manifest_before_sha256": "a" * 64,
                "manifest_after_sha256": "b" * 64,
                "target_sha256": {"outputs": "sha256:" + "c" * 64},
                "tombstone_identity": None,
                "target_identity": {"outputs": [1, 2]},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = purge_work(run_dir)

    assert result.status is ActionStatus.ERROR
    assert "receipt topology" in result.message
    assert receipt.is_file()


def test_purge_work_rejects_symlinked_pending_tombstone(tmp_path: Path) -> None:
    run_dir = tmp_path / "R20260330-0017"
    _write_manifest(
        run_dir,
        {"run": {"id": run_dir.name, "status": "archived"}},
    )
    output = run_dir / "work" / "outputs" / "data.bin"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"preserve")
    outside = tmp_path / "outside-tombstone"
    outside.mkdir()
    (outside / "unrelated.bin").write_bytes(b"keep")
    tombstone_name = ".delete-purge-deadbeef"
    (run_dir / "work" / tombstone_name).symlink_to(
        outside,
        target_is_directory=True,
    )
    status_dir = run_dir / "status"
    status_dir.mkdir()
    (status_dir / ".purge-pending.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "run_id": run_dir.name,
                "tombstone": tombstone_name,
                "targets": ["outputs"],
                "bytes_staged": output.stat().st_size,
                "compacted_at": "2026-09-01T00:00:00+00:00",
                "review_updates": {},
                "manifest_before_sha256": "a" * 64,
                "manifest_after_sha256": "b" * 64,
                "target_sha256": {"outputs": "sha256:" + "c" * 64},
                "tombstone_identity": [1, 2],
                "target_identity": {"outputs": [3, 4]},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = purge_work(run_dir)

    assert result.status is ActionStatus.ERROR
    assert "tombstone must be a real directory" in result.message
    assert output.read_bytes() == b"preserve"
    assert (outside / "unrelated.bin").read_bytes() == b"keep"


def test_purge_work_is_idempotent_after_receipt_unlink_interruption(
    tmp_path: Path,
) -> None:
    from runops.application.actions import admin as admin_module

    run_dir = tmp_path / "R20260330-0016"
    _write_manifest(
        run_dir,
        {"run": {"id": run_dir.name, "status": "archived"}},
    )
    output = run_dir / "work" / "outputs" / "data.bin"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"remove")
    interrupted = False

    def interrupt_after_receipt_unlink(target: Path) -> None:
        nonlocal interrupted
        receipt = target / "status" / ".purge-pending.json"
        receipt.unlink()
        interrupted = True
        raise KeyboardInterrupt("injected after receipt unlink")

    with (
        patch.object(
            admin_module,
            "_remove_purge_receipt",
            side_effect=interrupt_after_receipt_unlink,
        ),
        pytest.raises(KeyboardInterrupt, match="receipt unlink"),
    ):
        purge_work(
            run_dir,
            discard_incomplete=True,
            review_reason="Exercise post-unlink idempotence.",
        )

    assert interrupted
    assert read_manifest(run_dir).run["status"] == "purged"
    assert not output.exists()
    assert not (run_dir / "status" / ".purge-pending.json").exists()

    resumed = purge_work(run_dir)

    assert resumed.status is ActionStatus.SUCCESS
    assert resumed.state_before == "purged"
    assert resumed.state_after == "purged"


def test_archive_run_moves_directory_and_updates_manifest_path(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "scan" / "R20260330-0001"
    _write_manifest(
        run_dir,
        {
            "run": {
                "id": "R20260330-0001",
                "status": "completed",
            },
            "path": {
                "run_dir": str(run_dir),
            },
        },
    )
    destination = tmp_path / "runs" / "_archive" / "scan" / "R20260330-0001"

    result = archive_run(run_dir, move_to=destination)

    assert result.status is ActionStatus.SUCCESS
    assert result.state_before == "completed"
    assert result.state_after == "archived"
    assert result.data["moved"] is True
    assert result.data["source_path"] == str(run_dir.resolve())
    assert result.data["archive_path"] == str(destination.resolve())
    assert not run_dir.exists()
    assert (destination / "manifest.toml").exists()

    from runops.core.manifest import read_manifest

    manifest = read_manifest(destination)
    assert manifest.run["status"] == "archived"
    assert manifest.path["created_at_path"] == str(run_dir)
    assert manifest.path["run_dir"] == str(destination.resolve())
    assert manifest.path["archived_from"] == str(run_dir.resolve())
    assert "archived_at" in manifest.path


def test_archive_run_rejects_destination_outside_managed_project_namespace(
    tmp_path: Path,
) -> None:
    (tmp_path / "runops.toml").write_text(
        '[project]\nname = "managed"\n',
        encoding="utf-8",
    )
    run_dir = tmp_path / "runs" / "R20260330-0005"
    _write_manifest(
        run_dir,
        {"run": {"id": run_dir.name, "status": "completed"}},
    )
    destination = tmp_path / "external-cold" / run_dir.name

    result = archive_run(run_dir, move_to=destination)

    assert result.status is ActionStatus.PRECONDITION_FAILED
    assert "external --move-to would bypass Result and budget gates" in result.message
    assert run_dir.is_dir()
    assert not destination.exists()
    assert read_manifest(run_dir).run["status"] == "completed"


def test_archive_run_rejects_symlinked_managed_archive_root(
    tmp_path: Path,
) -> None:
    (tmp_path / "runops.toml").write_text(
        '[project]\nname = "managed"\n',
        encoding="utf-8",
    )
    run_dir = tmp_path / "runs" / "R20260330-0006"
    _write_manifest(
        run_dir,
        {"run": {"id": run_dir.name, "status": "completed"}},
    )
    outside = tmp_path / "external-cold"
    outside.mkdir()
    archive_entry = tmp_path / "runs" / "_archive"
    archive_entry.symlink_to(outside, target_is_directory=True)

    result = archive_run(run_dir, move_to=archive_entry / run_dir.name)

    assert result.status is ActionStatus.PRECONDITION_FAILED
    assert "archive root must not be a symlink" in result.message
    assert run_dir.is_dir()
    assert not (outside / run_dir.name).exists()
    assert read_manifest(run_dir).run["status"] == "completed"


def test_archive_bundle_moves_parent_and_preserves_run_states(tmp_path: Path) -> None:
    (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
    bundle = tmp_path / "runs" / "scan"
    bundle.mkdir(parents=True)
    (bundle / "survey.toml").write_text('[survey]\ncase = "scan"\n')
    completed = bundle / "R20260330-0001"
    cancelled = bundle / "R20260330-0002"
    _write_manifest(
        completed,
        {"run": {"id": "R20260330-0001", "status": "completed"}},
    )
    _write_manifest(
        cancelled,
        {
            "run": {"id": "R20260330-0002", "status": "cancelled"},
            "extensions": {"preserved": True},
        },
    )
    (cancelled / "work" / "outputs").mkdir(parents=True)
    (cancelled / "work" / "outputs" / "partial.dat").write_text("partial\n")

    result = archive_bundle(bundle)

    archived = tmp_path / "runs" / "_archive" / "scan"
    assert result.status is ActionStatus.SUCCESS
    assert result.data["run_count"] == 2
    assert result.data["archive_path"] == str(archived.resolve())
    assert not bundle.exists()
    assert (archived / "survey.toml").is_file()
    assert (archived / "R20260330-0002/work/outputs/partial.dat").is_file()
    completed_manifest = read_manifest(archived / completed.name)
    cancelled_manifest = read_manifest(archived / cancelled.name)
    assert completed_manifest.run["status"] == "completed"
    assert cancelled_manifest.run["status"] == "cancelled"
    assert cancelled_manifest.extra_sections["extensions"] == {"preserved": True}
    assert cancelled_manifest.path["run_dir"] == str(
        (archived / cancelled.name).resolve()
    )
    assert cancelled_manifest.path["bundle_archived_from"] == str(cancelled.resolve())
    assert (archived / ".runops-archive.toml").is_file()


def test_archive_bundle_rejects_active_run_without_mutation(tmp_path: Path) -> None:
    bundle = tmp_path / "runs" / "scan"
    (bundle / "survey.toml").parent.mkdir(parents=True)
    (bundle / "survey.toml").write_text("[survey]\n")
    running = bundle / "R20260330-0001"
    _write_manifest(
        running,
        {"run": {"id": "R20260330-0001", "status": "running"}},
    )

    result = archive_bundle(bundle)

    assert result.status is ActionStatus.PRECONDITION_FAILED
    assert "running" in result.message
    assert bundle.is_dir()
    assert not (bundle / ".runops-archive.toml").exists()
    assert read_manifest(running).run["status"] == "running"


def test_archive_bundle_rejects_existing_destination_without_mutation(
    tmp_path: Path,
) -> None:
    (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
    bundle = tmp_path / "runs" / "scan"
    run_dir = bundle / "R20260330-0001"
    _write_manifest(
        run_dir,
        {"run": {"id": "R20260330-0001", "status": "cancelled"}},
    )
    destination = tmp_path / "runs" / "_archive" / "scan"
    destination.mkdir(parents=True)
    (destination / "existing.txt").write_text("keep\n")

    result = archive_bundle(bundle)

    assert result.status is ActionStatus.PRECONDITION_FAILED
    assert "already exists" in result.message
    assert run_dir.is_dir()
    assert not (bundle / ".runops-archive.toml").exists()
    assert (destination / "existing.txt").read_text() == "keep\n"


def test_restore_bundle_moves_parent_back_and_preserves_states(tmp_path: Path) -> None:
    (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
    bundle = tmp_path / "runs" / "scan"
    (bundle / "survey.toml").parent.mkdir(parents=True)
    (bundle / "survey.toml").write_text("[survey]\n")
    cancelled = bundle / "R20260330-0001"
    _write_manifest(
        cancelled,
        {"run": {"id": "R20260330-0001", "status": "cancelled"}},
    )
    archived_result = archive_bundle(bundle)
    archived = Path(str(archived_result.data["archive_path"]))

    result = restore_bundle(archived)

    assert result.status is ActionStatus.SUCCESS
    assert result.data["restore_path"] == str(bundle.resolve())
    assert bundle.is_dir()
    assert not archived.exists()
    assert (bundle / "survey.toml").is_file()
    assert not (bundle / ".runops-archive.toml").exists()
    manifest = read_manifest(bundle / cancelled.name)
    assert manifest.run["status"] == "cancelled"
    assert manifest.path["run_dir"] == str((bundle / cancelled.name).resolve())
    assert manifest.path["bundle_restored_from"] == str(
        (archived / cancelled.name).resolve()
    )


def test_restore_bundle_rejects_existing_destination_without_mutation(
    tmp_path: Path,
) -> None:
    (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
    bundle = tmp_path / "runs" / "scan"
    run_dir = bundle / "R20260330-0001"
    _write_manifest(
        run_dir,
        {"run": {"id": "R20260330-0001", "status": "failed"}},
    )
    archived_result = archive_bundle(bundle)
    archived = Path(str(archived_result.data["archive_path"]))
    bundle.mkdir(parents=True)
    (bundle / "existing.txt").write_text("keep\n")

    result = restore_bundle(archived)

    assert result.status is ActionStatus.PRECONDITION_FAILED
    assert "already exists" in result.message
    assert archived.is_dir()
    assert (archived / ".runops-archive.toml").is_file()
    assert (bundle / "existing.txt").read_text() == "keep\n"
    assert read_manifest(archived / run_dir.name).run["status"] == "failed"


def test_archive_bundle_adopts_individually_archived_and_purged_runs(
    tmp_path: Path,
) -> None:
    (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
    bundle = tmp_path / "runs" / "scan"
    bundle.mkdir(parents=True)
    (bundle / "survey.toml").write_text("[survey]\n")
    cancelled = bundle / "R20260330-0003"
    _write_manifest(
        cancelled,
        {"run": {"id": "R20260330-0003", "status": "cancelled"}},
    )

    archive_root = tmp_path / "runs" / "_archive" / "scan"
    archived = archive_root / "R20260330-0001"
    purged = archive_root / "nested" / "R20260330-0002"
    _write_manifest(
        archived,
        {
            "run": {"id": "R20260330-0001", "status": "archived"},
            "path": {
                "run_dir": str(archived),
                "archived_from": str(bundle / archived.name),
            },
        },
    )
    _write_manifest(
        purged,
        {
            "run": {"id": "R20260330-0002", "status": "purged"},
            "path": {
                "run_dir": str(purged),
                "archived_from": str(bundle / "nested" / purged.name),
            },
        },
    )

    planned = plan_bundle_archive(bundle, adopt_archived=True)
    result = archive_bundle(bundle, adopt_archived=True)

    assert planned.status is ActionStatus.SUCCESS
    assert planned.data["adopted_run_count"] == 2
    assert planned.data["adopted_runs"] == [
        {"run_id": "R20260330-0001", "status": "archived"},
        {"run_id": "R20260330-0002", "status": "purged"},
    ]
    assert result.status is ActionStatus.SUCCESS
    assert result.data["run_count"] == 3
    assert result.data["adopted_run_count"] == 2
    assert not bundle.exists()
    assert (archive_root / "survey.toml").is_file()
    assert read_manifest(archived).run["status"] == "archived"
    assert read_manifest(purged).run["status"] == "purged"
    assert read_manifest(archive_root / cancelled.name).run["status"] == "cancelled"
    with open(archive_root / ".runops-archive.toml", "rb") as stream:
        metadata = tomllib.load(stream)
    assert metadata["bundle"]["adopted_run_ids"] == [
        "R20260330-0001",
        "R20260330-0002",
    ]

    restored = restore_bundle(archive_root)

    assert restored.status is ActionStatus.SUCCESS
    assert read_manifest(bundle / archived.name).run["status"] == "archived"
    assert read_manifest(bundle / "nested" / purged.name).run["status"] == "purged"
    assert read_manifest(bundle / cancelled.name).run["status"] == "cancelled"


def test_archive_bundle_adoption_rejects_foreign_archived_run(
    tmp_path: Path,
) -> None:
    (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
    bundle = tmp_path / "runs" / "scan"
    current = bundle / "R20260330-0002"
    _write_manifest(
        current,
        {"run": {"id": "R20260330-0002", "status": "cancelled"}},
    )
    archive_root = tmp_path / "runs" / "_archive" / "scan"
    foreign = archive_root / "R20260330-0001"
    _write_manifest(
        foreign,
        {
            "run": {"id": "R20260330-0001", "status": "archived"},
            "path": {"archived_from": str(tmp_path / "runs" / "other" / foreign.name)},
        },
    )

    result = archive_bundle(bundle, adopt_archived=True)

    assert result.status is ActionStatus.PRECONDITION_FAILED
    assert "does not belong to bundle" in result.message
    assert bundle.is_dir()
    assert foreign.is_dir()
    assert not (bundle / ".runops-archive.toml").exists()


def test_archive_bundle_adoption_rejects_unowned_archive_file(
    tmp_path: Path,
) -> None:
    (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
    bundle = tmp_path / "runs" / "scan"
    current = bundle / "R20260330-0002"
    _write_manifest(
        current,
        {"run": {"id": "R20260330-0002", "status": "cancelled"}},
    )
    archive_root = tmp_path / "runs" / "_archive" / "scan"
    archived = archive_root / "R20260330-0001"
    _write_manifest(
        archived,
        {
            "run": {"id": "R20260330-0001", "status": "archived"},
            "path": {"archived_from": str(bundle / archived.name)},
        },
    )
    (archive_root / "notes.md").write_text("unexpected\n")

    result = archive_bundle(bundle, adopt_archived=True)

    assert result.status is ActionStatus.PRECONDITION_FAILED
    assert "unowned path" in result.message
    assert bundle.is_dir()
    assert archived.is_dir()
    assert (archive_root / "notes.md").is_file()


def test_archive_bundle_adoption_rolls_back_topology_on_manifest_failure(
    tmp_path: Path,
) -> None:
    (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
    bundle = tmp_path / "runs" / "scan"
    current = bundle / "R20260330-0002"
    _write_manifest(
        current,
        {"run": {"id": "R20260330-0002", "status": "cancelled"}},
    )
    archive_root = tmp_path / "runs" / "_archive" / "scan"
    archived = archive_root / "R20260330-0001"
    _write_manifest(
        archived,
        {
            "run": {"id": "R20260330-0001", "status": "archived"},
            "path": {"archived_from": str(bundle / archived.name)},
        },
    )

    with patch(
        "runops.application.actions.bundle_archive.write_manifest",
        side_effect=ManifestError("injected failure"),
    ):
        result = archive_bundle(bundle, adopt_archived=True)

    assert result.status is ActionStatus.ERROR
    assert "injected failure" in result.message
    assert current.is_dir()
    assert archived.is_dir()
    assert read_manifest(current).run["status"] == "cancelled"
    assert read_manifest(archived).run["status"] == "archived"
    assert not (bundle / ".runops-archive.toml").exists()


def test_archive_run_rejects_existing_destination_before_state_change(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "runs" / "R20260330-0001"
    _write_manifest(
        run_dir,
        {
            "run": {
                "id": "R20260330-0001",
                "status": "completed",
            },
        },
    )
    destination = tmp_path / "runs" / "_archive" / "R20260330-0001"
    destination.mkdir(parents=True)

    result = archive_run(run_dir, move_to=destination)

    assert result.status is ActionStatus.PRECONDITION_FAILED
    assert "already exists" in result.message
    assert run_dir.exists()

    from runops.core.manifest import read_manifest

    manifest = read_manifest(run_dir)
    assert manifest.run["status"] == "completed"


def test_restore_run_moves_directory_back_without_deleting_outputs(
    tmp_path: Path,
) -> None:
    original = tmp_path / "runs" / "scan" / "R20260330-0001"
    archived = tmp_path / "runs" / "_archive" / "scan" / "R20260330-0001"
    output = archived / "work" / "outputs" / "result.dat"
    output.parent.mkdir(parents=True)
    output.write_text("preserved\n")
    _write_manifest(
        archived,
        {
            "run": {"id": "R20260330-0001", "status": "archived"},
            "path": {
                "run_dir": str(archived),
                "created_at_path": str(original),
                "archived_from": str(original),
            },
            "extensions": {"example": {"preserved": True}},
        },
    )

    result = restore_run(archived)

    assert result.status is ActionStatus.SUCCESS
    assert result.state_before == "archived"
    assert result.state_after == "completed"
    assert not archived.exists()
    assert (original / "work" / "outputs" / "result.dat").read_text() == "preserved\n"

    from runops.core.manifest import read_manifest

    manifest = read_manifest(original)
    assert manifest.run["status"] == "completed"
    assert manifest.path["run_dir"] == str(original.resolve())
    assert manifest.path["restored_from"] == str(archived.resolve())
    assert "restored_at" in manifest.path
    assert manifest.extra_sections["extensions"] == {"example": {"preserved": True}}


def test_restore_run_rolls_back_state_when_second_metadata_write_fails(
    tmp_path: Path,
) -> None:
    original = tmp_path / "runs" / "scan" / "R20260330-0010"
    archived = tmp_path / "runs" / "_archive" / "scan" / original.name
    output = archived / "work" / "outputs" / "result.dat"
    output.parent.mkdir(parents=True)
    output.write_text("preserved\n")
    _write_manifest(
        archived,
        {
            "run": {"id": original.name, "status": "archived"},
            "path": {
                "run_dir": str(archived),
                "created_at_path": str(original),
                "archived_from": str(original),
            },
            "storage": {"tier": "cold", "form": "full"},
        },
    )

    from runops.core import manifest as manifest_module

    real_update = manifest_module.update_manifest
    calls = 0

    def fail_second_update(path: Path, updates: dict[str, Any]) -> Any:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ManifestError("injected restore metadata failure")
        return real_update(path, updates)

    with patch.object(
        manifest_module,
        "update_manifest",
        side_effect=fail_second_update,
    ):
        failed = restore_run(archived)

    assert failed.status is ActionStatus.ERROR
    assert "injected restore metadata failure" in failed.message
    assert archived.is_dir()
    assert not original.exists()
    rolled_back = read_manifest(archived)
    assert rolled_back.run["status"] == "archived"
    assert rolled_back.storage == {"tier": "cold", "form": "full"}
    assert (archived / "work" / "outputs" / "result.dat").is_file()

    restored = restore_run(archived)

    assert restored.status is ActionStatus.SUCCESS
    assert read_manifest(original).run["status"] == "completed"
    assert (original / "work" / "outputs" / "result.dat").is_file()


def test_restore_run_rejects_symlink_ancestor_escape_from_managed_runs(
    tmp_path: Path,
) -> None:
    (tmp_path / "runops.toml").write_text('[project]\nname = "restore-safe"\n')
    archived = tmp_path / "runs" / "_archive" / "R20260330-0011"
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "runs" / "link").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "runs" / "link").symlink_to(outside, target_is_directory=True)
    escaped = tmp_path / "runs" / "link" / archived.name
    _write_manifest(
        archived,
        {
            "run": {"id": archived.name, "status": "archived"},
            "path": {
                "run_dir": str(archived),
                "archived_from": str(escaped),
            },
        },
    )

    result = restore_run(archived)

    assert result.status is ActionStatus.PRECONDITION_FAILED
    assert "restored inside" in result.message
    assert archived.is_dir()
    assert not (outside / archived.name).exists()


def test_restore_run_in_place_changes_state_without_moving(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "R20260330-0001"
    _write_manifest(
        run_dir,
        {"run": {"id": "R20260330-0001", "status": "archived"}},
    )

    result = restore_run(run_dir)

    assert result.status is ActionStatus.SUCCESS
    assert result.data["moved"] is False
    assert run_dir.exists()

    from runops.core.manifest import read_manifest

    assert read_manifest(run_dir).run["status"] == "completed"


def test_restore_run_rejects_existing_destination_before_mutation(
    tmp_path: Path,
) -> None:
    original = tmp_path / "runs" / "R20260330-0001"
    archived = tmp_path / "runs" / "_archive" / "R20260330-0001"
    original.mkdir(parents=True)
    _write_manifest(
        archived,
        {
            "run": {"id": "R20260330-0001", "status": "archived"},
            "path": {"archived_from": str(original)},
        },
    )

    result = restore_run(archived)

    assert result.status is ActionStatus.PRECONDITION_FAILED
    assert "already exists" in result.message
    assert archived.exists()

    from runops.core.manifest import read_manifest

    assert read_manifest(archived).run["status"] == "archived"


def test_restore_run_rejects_dangling_symlink_destination(tmp_path: Path) -> None:
    original = tmp_path / "runs" / "R20260330-0001"
    archived = tmp_path / "runs" / "_archive" / "R20260330-0001"
    original.parent.mkdir(parents=True)
    original.symlink_to(tmp_path / "missing-run")
    _write_manifest(
        archived,
        {
            "run": {"id": "R20260330-0001", "status": "archived"},
            "path": {"archived_from": str(original)},
        },
    )

    result = restore_run(archived)

    assert result.status is ActionStatus.PRECONDITION_FAILED
    assert original.is_symlink()
    assert archived.exists()


@pytest.mark.parametrize("interrupt_phase", ["move", "manifest", "cleanup"])
def test_archive_run_resumes_durable_transaction_after_process_interruption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interrupt_phase: str,
) -> None:
    from runops.application.actions import admin as admin_module
    from runops.core import manifest as manifest_module

    source = tmp_path / "runs" / "scan" / "R20260330-0020"
    destination = tmp_path / "runs" / "_archive" / "scan" / source.name
    _write_manifest(
        source,
        {
            "run": {"id": source.name, "status": "completed"},
            "path": {"run_dir": str(source)},
            "extensions": {"exact": {"preserved": True}},
        },
    )
    interrupted = False

    if interrupt_phase == "move":
        real_move = admin_module.move_directory_noreplace

        def interrupt_after_move(move_source: Path, move_destination: Path) -> Any:
            nonlocal interrupted
            outcome = real_move(move_source, move_destination)
            if move_source == source and move_destination == destination:
                interrupted = True
                raise KeyboardInterrupt("injected after archive move")
            return outcome

        monkeypatch.setattr(
            admin_module,
            "move_directory_noreplace",
            interrupt_after_move,
        )
    elif interrupt_phase == "manifest":
        real_write = manifest_module.write_manifest
        write_calls = 0

        def interrupt_after_manifest(*args: Any, **kwargs: Any) -> Any:
            nonlocal interrupted, write_calls
            write_calls += 1
            result = real_write(*args, **kwargs)
            if write_calls == 2:
                interrupted = True
                raise KeyboardInterrupt("injected after archive manifest")
            return result

        monkeypatch.setattr(
            manifest_module,
            "write_manifest",
            interrupt_after_manifest,
        )
    else:
        real_remove = admin_module._remove_lifecycle_receipt

        def interrupt_after_cleanup(receipt: Any) -> None:
            nonlocal interrupted
            real_remove(receipt)
            interrupted = True
            raise KeyboardInterrupt("injected after archive receipt cleanup")

        monkeypatch.setattr(
            admin_module,
            "_remove_lifecycle_receipt",
            interrupt_after_cleanup,
        )

    with pytest.raises(KeyboardInterrupt, match="injected after archive"):
        archive_run(source, move_to=destination)

    assert interrupted
    receipt_dir = tmp_path / ".runops" / "lifecycle"
    receipts = list(receipt_dir.glob("archive_run-*.json"))
    assert len(receipts) == (0 if interrupt_phase == "cleanup" else 1)
    monkeypatch.undo()

    resumed = archive_run(source, move_to=destination)

    assert resumed.status is ActionStatus.SUCCESS
    assert not source.exists()
    assert destination.is_dir()
    assert not list(receipt_dir.glob("archive_run-*.json"))
    manifest = read_manifest(destination)
    assert manifest.run["status"] == "archived"
    assert manifest.path["archived_from"] == str(source)
    assert manifest.extra_sections["extensions"] == {"exact": {"preserved": True}}


@pytest.mark.parametrize("interrupt_phase", ["move", "manifest", "cleanup"])
def test_restore_run_resumes_durable_transaction_after_process_interruption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interrupt_phase: str,
) -> None:
    from runops.application.actions import admin as admin_module
    from runops.core import manifest as manifest_module

    destination = tmp_path / "runs" / "scan" / "R20260330-0021"
    source = tmp_path / "runs" / "_archive" / "scan" / destination.name
    _write_manifest(
        source,
        {
            "run": {"id": source.name, "status": "archived"},
            "path": {
                "run_dir": str(source),
                "archived_from": str(destination),
            },
            "storage": {"tier": "cold", "form": "full"},
            "extensions": {"exact": {"preserved": True}},
        },
    )
    interrupted = False

    if interrupt_phase == "move":
        real_move = admin_module.move_directory_noreplace

        def interrupt_after_move(move_source: Path, move_destination: Path) -> Any:
            nonlocal interrupted
            outcome = real_move(move_source, move_destination)
            if move_source == source and move_destination == destination:
                interrupted = True
                raise KeyboardInterrupt("injected after restore move")
            return outcome

        monkeypatch.setattr(
            admin_module,
            "move_directory_noreplace",
            interrupt_after_move,
        )
    elif interrupt_phase == "manifest":
        real_write = manifest_module.write_manifest
        write_calls = 0

        def interrupt_after_manifest(*args: Any, **kwargs: Any) -> Any:
            nonlocal interrupted, write_calls
            write_calls += 1
            result = real_write(*args, **kwargs)
            if write_calls == 2:
                interrupted = True
                raise KeyboardInterrupt("injected after restore manifest")
            return result

        monkeypatch.setattr(
            manifest_module,
            "write_manifest",
            interrupt_after_manifest,
        )
    else:
        real_remove = admin_module._remove_lifecycle_receipt

        def interrupt_after_cleanup(receipt: Any) -> None:
            nonlocal interrupted
            real_remove(receipt)
            interrupted = True
            raise KeyboardInterrupt("injected after restore receipt cleanup")

        monkeypatch.setattr(
            admin_module,
            "_remove_lifecycle_receipt",
            interrupt_after_cleanup,
        )

    with pytest.raises(KeyboardInterrupt, match="injected after restore"):
        restore_run(source)

    assert interrupted
    receipt_dir = tmp_path / ".runops" / "lifecycle"
    receipts = list(receipt_dir.glob("restore_run-*.json"))
    assert len(receipts) == (0 if interrupt_phase == "cleanup" else 1)
    monkeypatch.undo()

    resumed = restore_run(source)

    assert resumed.status is ActionStatus.SUCCESS
    assert not source.exists()
    assert destination.is_dir()
    assert not list(receipt_dir.glob("restore_run-*.json"))
    manifest = read_manifest(destination)
    assert manifest.run["status"] == "completed"
    assert manifest.path["restored_from"] == str(source)
    assert manifest.extra_sections["extensions"] == {"exact": {"preserved": True}}


def test_archive_run_resumes_after_manifest_transition_before_state_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from runops.core import state as state_module

    source = tmp_path / "runs" / "scan" / "R20260330-0028"
    destination = tmp_path / "runs" / "_archive" / "scan" / source.name
    _write_manifest(source, {"run": {"id": source.name, "status": "completed"}})

    def interrupt_before_state(*args: Any, **kwargs: Any) -> None:
        raise KeyboardInterrupt("injected before archive state write")

    monkeypatch.setattr(state_module, "_write_state_json", interrupt_before_state)
    with pytest.raises(KeyboardInterrupt, match="archive state write"):
        archive_run(source, move_to=destination)
    monkeypatch.undo()

    assert read_manifest(source).run["status"] == "archived"
    assert not (source / "status" / "state.json").exists()
    resumed = archive_run(source, move_to=destination)

    assert resumed.status is ActionStatus.SUCCESS
    assert not source.exists()
    assert read_manifest(destination).run["status"] == "archived"
    assert not list((tmp_path / ".runops" / "lifecycle").glob("archive_run-*.json"))


def test_restore_run_resumes_after_manifest_transition_before_state_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from runops.core import state as state_module

    destination = tmp_path / "runs" / "scan" / "R20260330-0029"
    source = tmp_path / "runs" / "_archive" / "scan" / destination.name
    _write_manifest(
        source,
        {
            "run": {"id": source.name, "status": "archived"},
            "path": {
                "run_dir": str(source),
                "archived_from": str(destination),
            },
            "storage": {"tier": "cold", "form": "full"},
        },
    )

    def interrupt_before_state(*args: Any, **kwargs: Any) -> None:
        raise KeyboardInterrupt("injected before restore state write")

    monkeypatch.setattr(state_module, "_write_state_json", interrupt_before_state)
    with pytest.raises(KeyboardInterrupt, match="restore state write"):
        restore_run(source)
    monkeypatch.undo()

    assert not source.exists()
    assert read_manifest(destination).run["status"] == "completed"
    assert not (destination / "status" / "state.json").exists()
    resumed = restore_run(source)

    assert resumed.status is ActionStatus.SUCCESS
    assert read_manifest(destination).run["status"] == "completed"
    assert not list((tmp_path / ".runops" / "lifecycle").glob("restore_run-*.json"))


@pytest.mark.parametrize(
    ("action", "before_state", "after_state"),
    [
        ("archive", RunState.COMPLETED, RunState.ARCHIVED),
        ("restore", RunState.ARCHIVED, RunState.COMPLETED),
    ],
)
def test_lifecycle_retry_recovers_after_rollback_manifest_restore_interruption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    before_state: RunState,
    after_state: RunState,
) -> None:
    from runops.application.actions import admin as admin_module

    suffix = "1" if action == "restore" else "0"
    active = tmp_path / "runs" / "scan" / f"R20260330-004{suffix}"
    cold = tmp_path / "runs" / "_archive" / "scan" / active.name
    source = cold if action == "restore" else active
    destination = active if action == "restore" else cold
    manifest_data: dict[str, Any] = {
        "run": {"id": source.name, "status": before_state.value},
        "path": {"run_dir": str(source)},
        "extensions": {"rollback_boundary": "preserve"},
    }
    if action == "restore":
        manifest_data["path"]["archived_from"] = str(destination)
        manifest_data["storage"] = {"tier": "cold", "form": "full"}
    _write_manifest(source, manifest_data)
    state_path = source / "status" / "state.json"
    state_path.parent.mkdir()
    state_path.write_text(
        json.dumps(
            {
                "state": before_state.value,
                "previous_state": "running",
                "changed_at": "2026-03-30T00:00:00+00:00",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    manifest_preimage = (source / "manifest.toml").read_bytes()
    state_preimage = state_path.read_bytes()

    if action == "archive":
        real_completed = admin_module._completed_archive_matches
        completed_checks = 0

        def fail_after_archive_commit(*args: Any, **kwargs: Any) -> bool:
            nonlocal completed_checks
            completed_checks += 1
            if completed_checks == 2:
                raise OSError("injected archive commit verification failure")
            return real_completed(*args, **kwargs)

        monkeypatch.setattr(
            admin_module,
            "_completed_archive_matches",
            fail_after_archive_commit,
        )
    else:

        def fail_after_restore_commit(*args: Any, **kwargs: Any) -> bool:
            raise OSError("injected restore commit verification failure")

        monkeypatch.setattr(
            admin_module,
            "_completed_restore_matches",
            fail_after_restore_commit,
        )

    real_restore = admin_module._restore_file_snapshot
    manifest_restored = False

    def interrupt_between_rollback_snapshots(
        path: Path,
        payload: bytes | None,
    ) -> None:
        nonlocal manifest_restored
        if path == destination / "manifest.toml" and payload == manifest_preimage:
            real_restore(path, payload)
            manifest_restored = True
            return
        if (
            manifest_restored
            and path == destination / "status" / "state.json"
            and payload == state_preimage
        ):
            raise KeyboardInterrupt("injected between rollback snapshots")
        real_restore(path, payload)

    monkeypatch.setattr(
        admin_module,
        "_restore_file_snapshot",
        interrupt_between_rollback_snapshots,
    )

    with pytest.raises(KeyboardInterrupt, match="between rollback snapshots"):
        if action == "archive":
            archive_run(source, move_to=destination)
        else:
            restore_run(source)

    assert manifest_restored
    assert not source.exists()
    assert (destination / "manifest.toml").read_bytes() == manifest_preimage
    assert (destination / "status" / "state.json").read_bytes() != state_preimage
    receipt_dir = tmp_path / ".runops" / "lifecycle"
    assert list(receipt_dir.glob(f"{action}_run-*.json"))
    monkeypatch.undo()

    resumed = (
        archive_run(source, move_to=destination)
        if action == "archive"
        else restore_run(source)
    )

    assert resumed.status is ActionStatus.SUCCESS
    assert not source.exists()
    assert read_manifest(destination).run["status"] == after_state.value
    assert read_manifest(destination).extra_sections["extensions"] == {
        "rollback_boundary": "preserve"
    }
    assert not list(receipt_dir.glob(f"{action}_run-*.json"))


def test_archive_retry_recovers_after_interrupted_rollback_move(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from runops.application.actions import admin as admin_module

    source = tmp_path / "runs" / "scan" / "R20260330-0042"
    destination = tmp_path / "runs" / "_archive" / "scan" / source.name
    _write_manifest(
        source,
        {
            "run": {"id": source.name, "status": "completed"},
            "extensions": {"rollback_move": "preserve"},
        },
    )
    manifest_preimage = (source / "manifest.toml").read_bytes()
    real_move = admin_module.move_directory_noreplace

    def interrupt_after_rollback_move(
        move_source: Path,
        move_destination: Path,
    ) -> None:
        real_move(move_source, move_destination)
        if move_source == source and move_destination == destination:
            raise OSError("injected forward archive failure")
        if move_source == destination and move_destination == source:
            raise KeyboardInterrupt("injected after rollback move")

    monkeypatch.setattr(
        admin_module,
        "move_directory_noreplace",
        interrupt_after_rollback_move,
    )

    with pytest.raises(KeyboardInterrupt, match="after rollback move"):
        archive_run(source, move_to=destination)

    assert source.is_dir()
    assert not destination.exists()
    assert (source / "manifest.toml").read_bytes() == manifest_preimage
    receipt_dir = tmp_path / ".runops" / "lifecycle"
    assert list(receipt_dir.glob("archive_run-*.json"))
    monkeypatch.undo()

    resumed = archive_run(source, move_to=destination)

    assert resumed.status is ActionStatus.SUCCESS
    assert not source.exists()
    assert read_manifest(destination).run["status"] == "archived"
    assert read_manifest(destination).extra_sections["extensions"] == {
        "rollback_move": "preserve"
    }
    assert not list(receipt_dir.glob("archive_run-*.json"))


def test_archive_run_resumes_in_place_pending_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from runops.application.actions import admin as admin_module

    run_dir = tmp_path / "runs" / "R20260330-0043"
    _write_manifest(
        run_dir,
        {
            "run": {"id": run_dir.name, "status": "completed"},
            "extensions": {"in_place": "preserve"},
        },
    )
    real_write_receipt = admin_module._write_lifecycle_receipt

    def interrupt_after_receipt(**kwargs: Any) -> Any:
        real_write_receipt(**kwargs)
        raise KeyboardInterrupt("injected after in-place archive receipt")

    monkeypatch.setattr(
        admin_module,
        "_write_lifecycle_receipt",
        interrupt_after_receipt,
    )
    with pytest.raises(KeyboardInterrupt, match="in-place archive receipt"):
        archive_run(run_dir)
    receipt_dir = tmp_path / ".runops" / "lifecycle"
    assert list(receipt_dir.glob("archive_run-*.json"))
    assert read_manifest(run_dir).run["status"] == "completed"
    monkeypatch.undo()

    resumed = archive_run(run_dir)

    assert resumed.status is ActionStatus.SUCCESS
    assert resumed.data["moved"] is False
    assert read_manifest(run_dir).run["status"] == "archived"
    assert read_manifest(run_dir).extra_sections["extensions"] == {
        "in_place": "preserve"
    }
    assert not list(receipt_dir.glob("archive_run-*.json"))


def test_archive_run_refuses_changed_live_manifest_after_receipt_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from runops.application.actions import admin as admin_module

    source = tmp_path / "runs" / "scan" / "R20260330-0030"
    destination = tmp_path / "runs" / "_archive" / "scan" / source.name
    _write_manifest(
        source,
        {
            "run": {"id": source.name, "status": "completed"},
            "params_snapshot": {"nx": 64},
        },
    )
    real_write_receipt = admin_module._write_lifecycle_receipt

    def interrupt_after_receipt(**kwargs: Any) -> Any:
        real_write_receipt(**kwargs)
        raise KeyboardInterrupt("injected after archive receipt")

    monkeypatch.setattr(
        admin_module,
        "_write_lifecycle_receipt",
        interrupt_after_receipt,
    )
    with pytest.raises(KeyboardInterrupt, match="archive receipt"):
        archive_run(source, move_to=destination)
    monkeypatch.undo()
    update_manifest(source, {"params_snapshot": {"nx": 128}})
    changed = (source / "manifest.toml").read_bytes()
    receipt = next((tmp_path / ".runops" / "lifecycle").glob("archive_run-*.json"))

    resumed = archive_run(source, move_to=destination)

    assert resumed.status is ActionStatus.PRECONDITION_FAILED
    assert "live manifest digest mismatch" in resumed.message
    assert (source / "manifest.toml").read_bytes() == changed
    assert source.is_dir()
    assert not destination.exists()
    assert receipt.is_file()


def test_restore_run_refuses_changed_live_manifest_after_receipt_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from runops.application.actions import admin as admin_module

    destination = tmp_path / "runs" / "scan" / "R20260330-0031"
    source = tmp_path / "runs" / "_archive" / "scan" / destination.name
    _write_manifest(
        source,
        {
            "run": {"id": source.name, "status": "archived"},
            "path": {
                "run_dir": str(source),
                "archived_from": str(destination),
            },
            "params_snapshot": {"nx": 64},
            "storage": {"tier": "cold", "form": "full"},
        },
    )
    real_write_receipt = admin_module._write_lifecycle_receipt

    def interrupt_after_receipt(**kwargs: Any) -> Any:
        real_write_receipt(**kwargs)
        raise KeyboardInterrupt("injected after restore receipt")

    monkeypatch.setattr(
        admin_module,
        "_write_lifecycle_receipt",
        interrupt_after_receipt,
    )
    with pytest.raises(KeyboardInterrupt, match="restore receipt"):
        restore_run(source)
    monkeypatch.undo()
    update_manifest(source, {"params_snapshot": {"nx": 128}})
    changed = (source / "manifest.toml").read_bytes()
    receipt = next((tmp_path / ".runops" / "lifecycle").glob("restore_run-*.json"))

    resumed = restore_run(source)

    assert resumed.status is ActionStatus.PRECONDITION_FAILED
    assert "live manifest digest mismatch" in resumed.message
    assert (source / "manifest.toml").read_bytes() == changed
    assert source.is_dir()
    assert not destination.exists()
    assert receipt.is_file()


def test_archive_run_refuses_changed_live_state_after_receipt_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from runops.application.actions import admin as admin_module

    source = tmp_path / "runs" / "scan" / "R20260330-0033"
    destination = tmp_path / "runs" / "_archive" / "scan" / source.name
    _write_manifest(source, {"run": {"id": source.name, "status": "completed"}})
    state_file = source / "status" / "state.json"
    state_file.parent.mkdir()
    state_file.write_text(
        json.dumps(
            {
                "state": "completed",
                "previous_state": "running",
                "changed_at": "2026-03-30T00:00:00+00:00",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    real_write_receipt = admin_module._write_lifecycle_receipt

    def interrupt_after_receipt(**kwargs: Any) -> Any:
        real_write_receipt(**kwargs)
        raise KeyboardInterrupt("injected after archive state receipt")

    monkeypatch.setattr(
        admin_module,
        "_write_lifecycle_receipt",
        interrupt_after_receipt,
    )
    with pytest.raises(KeyboardInterrupt, match="archive state receipt"):
        archive_run(source, move_to=destination)
    monkeypatch.undo()
    changed_state = json.loads(state_file.read_text(encoding="utf-8"))
    changed_state["unexpected"] = "replacement"
    state_file.write_text(
        json.dumps(changed_state, indent=2) + "\n",
        encoding="utf-8",
    )
    changed = state_file.read_bytes()
    receipt = next((tmp_path / ".runops" / "lifecycle").glob("archive_run-*.json"))

    resumed = archive_run(source, move_to=destination)

    assert resumed.status is ActionStatus.PRECONDITION_FAILED
    assert "live state digest mismatch" in resumed.message
    assert state_file.read_bytes() == changed
    assert source.is_dir()
    assert not destination.exists()
    assert receipt.is_file()


def test_archive_run_refuses_rollback_over_changed_live_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from runops.application.actions import admin as admin_module

    source = tmp_path / "runs" / "scan" / "R20260330-0032"
    destination = tmp_path / "runs" / "_archive" / "scan" / source.name
    _write_manifest(
        source,
        {
            "run": {"id": source.name, "status": "completed"},
            "params_snapshot": {"nx": 64},
        },
    )
    real_move = admin_module.move_directory_noreplace

    def change_after_move(move_source: Path, move_destination: Path) -> Any:
        real_move(move_source, move_destination)
        update_manifest(move_destination, {"params_snapshot": {"nx": 128}})
        raise OSError("injected after changed archive move")

    monkeypatch.setattr(
        admin_module,
        "move_directory_noreplace",
        change_after_move,
    )

    failed = archive_run(source, move_to=destination)

    assert failed.status is ActionStatus.ERROR
    assert "rollback refused without an exact trusted live image" in failed.message
    assert not source.exists()
    assert destination.is_dir()
    assert read_manifest(destination).params_snapshot == {"nx": 128}
    assert list((tmp_path / ".runops" / "lifecycle").glob("archive_run-*.json"))


def test_archive_run_keeps_receipt_when_live_image_changes_before_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from runops.application.actions import admin as admin_module

    source = tmp_path / "runs" / "scan" / "R20260330-0034"
    destination = tmp_path / "runs" / "_archive" / "scan" / source.name
    _write_manifest(
        source,
        {
            "run": {"id": source.name, "status": "completed"},
            "params_snapshot": {"nx": 64},
        },
    )
    real_completed = admin_module._completed_archive_matches
    changed = False

    def change_after_completed_check(*args: Any, **kwargs: Any) -> bool:
        nonlocal changed
        matches = real_completed(*args, **kwargs)
        run_dir = args[0]
        if matches and not changed:
            changed = True
            update_manifest(run_dir, {"params_snapshot": {"nx": 128}})
        return matches

    monkeypatch.setattr(
        admin_module,
        "_completed_archive_matches",
        change_after_completed_check,
    )

    result = archive_run(source, move_to=destination)

    assert result.status is ActionStatus.SUCCESS
    assert result.data["cleanup_pending"]
    assert read_manifest(destination).params_snapshot == {"nx": 128}
    assert list((tmp_path / ".runops" / "lifecycle").glob("archive_run-*.json"))


def test_archive_run_fails_closed_on_tampered_lifecycle_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from runops.application.actions import admin as admin_module

    source = tmp_path / "runs" / "scan" / "R20260330-0022"
    destination = tmp_path / "runs" / "_archive" / "scan" / source.name
    _write_manifest(source, {"run": {"id": source.name, "status": "completed"}})
    real_move = admin_module.move_directory_noreplace

    def interrupt_after_move(move_source: Path, move_destination: Path) -> Any:
        real_move(move_source, move_destination)
        raise KeyboardInterrupt("injected after archive move")

    monkeypatch.setattr(
        admin_module,
        "move_directory_noreplace",
        interrupt_after_move,
    )
    with pytest.raises(KeyboardInterrupt, match="archive move"):
        archive_run(source, move_to=destination)
    monkeypatch.undo()
    receipt = next((tmp_path / ".runops" / "lifecycle").glob("archive_run-*.json"))
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    payload["run_id"] = "R20260330-9999"
    receipt.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    resumed = archive_run(source, move_to=destination)

    assert resumed.status is ActionStatus.PRECONDITION_FAILED
    assert "manifest snapshot does not match" in resumed.message
    assert destination.is_dir()
    assert not source.exists()
    assert receipt.is_file()


def test_archive_run_fails_closed_on_symlinked_lifecycle_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from runops.application.actions import admin as admin_module

    source = tmp_path / "runs" / "scan" / "R20260330-0023"
    destination = tmp_path / "runs" / "_archive" / "scan" / source.name
    _write_manifest(source, {"run": {"id": source.name, "status": "completed"}})
    real_move = admin_module.move_directory_noreplace

    def interrupt_after_move(move_source: Path, move_destination: Path) -> Any:
        real_move(move_source, move_destination)
        raise KeyboardInterrupt("injected after archive move")

    monkeypatch.setattr(
        admin_module,
        "move_directory_noreplace",
        interrupt_after_move,
    )
    with pytest.raises(KeyboardInterrupt, match="archive move"):
        archive_run(source, move_to=destination)
    monkeypatch.undo()
    receipt = next((tmp_path / ".runops" / "lifecycle").glob("archive_run-*.json"))
    outside = tmp_path / "outside-receipt.json"
    receipt.replace(outside)
    receipt.symlink_to(outside)

    resumed = archive_run(source, move_to=destination)

    assert resumed.status is ActionStatus.PRECONDITION_FAILED
    assert "single-link regular file" in resumed.message
    assert destination.is_dir()
    assert not source.exists()
    assert outside.is_file()


def test_archive_run_revalidates_pending_receipt_managed_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from runops.application.actions import admin as admin_module

    (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
    source = tmp_path / "runs" / "scan" / "R20260330-0024"
    destination = tmp_path / "runs" / "_archive" / "scan" / source.name
    _write_manifest(source, {"run": {"id": source.name, "status": "completed"}})
    real_move = admin_module.move_directory_noreplace

    def interrupt_after_move(move_source: Path, move_destination: Path) -> Any:
        real_move(move_source, move_destination)
        raise KeyboardInterrupt("injected after archive move")

    monkeypatch.setattr(
        admin_module,
        "move_directory_noreplace",
        interrupt_after_move,
    )
    with pytest.raises(KeyboardInterrupt, match="archive move"):
        archive_run(source, move_to=destination)
    monkeypatch.undo()
    receipt = next((tmp_path / ".runops" / "lifecycle").glob("archive_run-*.json"))
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    outside = tmp_path / "outside" / source.name
    payload["destination"] = str(outside)
    receipt.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    resumed = archive_run(source, move_to=outside)

    assert resumed.status is ActionStatus.PRECONDITION_FAILED
    assert "archived inside" in resumed.message
    assert destination.is_dir()
    assert not outside.exists()


def test_restore_run_revalidates_pending_receipt_managed_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from runops.application.actions import admin as admin_module

    (tmp_path / "runops.toml").write_text('[project]\nname = "test"\n')
    destination = tmp_path / "runs" / "scan" / "R20260330-0025"
    source = tmp_path / "runs" / "_archive" / "scan" / destination.name
    _write_manifest(
        source,
        {
            "run": {"id": source.name, "status": "archived"},
            "path": {"archived_from": str(destination)},
        },
    )
    real_move = admin_module.move_directory_noreplace

    def interrupt_after_move(move_source: Path, move_destination: Path) -> Any:
        real_move(move_source, move_destination)
        raise KeyboardInterrupt("injected after restore move")

    monkeypatch.setattr(
        admin_module,
        "move_directory_noreplace",
        interrupt_after_move,
    )
    with pytest.raises(KeyboardInterrupt, match="restore move"):
        restore_run(source)
    monkeypatch.undo()
    receipt = next((tmp_path / ".runops" / "lifecycle").glob("restore_run-*.json"))
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    outside = tmp_path / "outside" / destination.name
    payload["destination"] = str(outside)
    receipt.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    resumed = restore_run(source)

    assert resumed.status is ActionStatus.PRECONDITION_FAILED
    assert "restored inside" in resumed.message
    assert destination.is_dir()
    assert not outside.exists()


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

    with patch(
        "runops.slurm.submit.submit_command",
        return_value="12345",
    ) as submit:
        result = submit_run(run_dir)

    assert result.status is ActionStatus.SUCCESS
    assert result.data["job_id"] == "12345"
    submit.assert_called_once_with(
        (
            "sbatch",
            f"--chdir={run_dir}",
            str(run_dir / "submit" / "job.sh"),
        )
    )
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
        "runops.slurm.submit.submit_command",
        return_value="12345",
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
    mock_submit.assert_called_once_with(
        (
            "sbatch",
            f"--chdir={run_dir / 'work'}",
            "--dependency=afterok:67890",
            "--partition=compute",
            "--qos=debugqos",
            str(run_dir / "submit" / "job.sh"),
        )
    )

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


@pytest.mark.parametrize(
    ("phase", "target"),
    [
        ("manifest", "runops.application.execution.submission.update_manifest"),
        ("state", "runops.application.execution.submission.update_state"),
    ],
)
def test_submit_run_reports_accepted_job_when_persistence_fails(
    tmp_path: Path,
    phase: str,
    target: str,
) -> None:
    from runops.core.exceptions import ManifestError

    run_dir = tmp_path / "R20260330-0001"
    _write_manifest(
        run_dir,
        {
            "run": {"id": "R20260330-0001", "status": "created"},
            "job": {},
        },
    )
    (run_dir / "submit").mkdir(parents=True)
    (run_dir / "submit" / "job.sh").write_text(
        "#!/bin/bash\n#SBATCH --job-name=test\n",
        encoding="utf-8",
    )
    (run_dir / "input").mkdir()
    (run_dir / "input" / "params.json").write_text("{}", encoding="utf-8")

    with (
        patch("runops.slurm.submit.submit_command", return_value="98765"),
        patch(target, side_effect=ManifestError(f"{phase} write failed")),
    ):
        result = submit_run(run_dir)

    assert result.status is ActionStatus.ERROR
    message = result.message.lower()
    assert "scheduler accepted job 98765" in message
    assert "persistence failed" in message
    assert "do not resubmit" in message
    assert "reconcile" in message
    assert result.data["job_id"] == "98765"
    assert result.data["attempt"] == 1
    assert result.data["phase"] == phase


def test_submit_run_reports_unknown_outcome_and_retains_claim(tmp_path: Path) -> None:
    from runops.slurm.submit import SlurmSubmissionOutcomeUnknownError

    run_dir = tmp_path / "R20260330-0001"
    _write_manifest(
        run_dir,
        {
            "run": {"id": run_dir.name, "status": "created"},
            "job": {},
        },
    )
    (run_dir / "submit").mkdir(parents=True)
    (run_dir / "submit" / "job.sh").write_text(
        "#!/bin/bash\n#SBATCH --job-name=test\n",
        encoding="utf-8",
    )
    (run_dir / "input").mkdir()
    (run_dir / "input" / "params.json").write_text("{}", encoding="utf-8")

    with patch(
        "runops.slurm.submit.submit_command",
        side_effect=SlurmSubmissionOutcomeUnknownError("job id response lost"),
    ):
        result = submit_run(run_dir)

    assert result.status is ActionStatus.ERROR
    assert "outcome is unknown" in result.message.lower()
    assert "do not resubmit" in result.message.lower()
    assert result.data["claim"] == "pending"
    assert (run_dir / ".runops-submit.lock").read_text(encoding="utf-8") == (
        "pending\n"
    )


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


def test_execute_action_sync_completed_returns_and_caches_readiness(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "R20260330-0002"
    _write_manifest(
        run_dir,
        {
            "run": {"id": "R20260330-0002", "status": "running"},
            "job": {
                "job_id": "24680",
                "submitted_at": "2026-07-16T12:00:00+09:00",
                "attempt": 1,
            },
            "simulator": {"name": "emses", "adapter": "emses"},
        },
    )
    write_toml = tomli_w.dump
    (run_dir / "input").mkdir()
    with (run_dir / "input" / "plasma.toml").open("wb") as stream:
        write_toml({"jobcon": {"nstep": 100}}, stream)
    (run_dir / "work").mkdir()
    (run_dir / "work" / "energy").write_text("100 1.0 2.0\n", encoding="utf-8")

    with patch(
        "runops.slurm.query.query_job_status",
        return_value=JobStatus(
            run_state=RunState.COMPLETED,
            slurm_state="COMPLETED",
        ),
    ):
        result = execute_action("sync_run", run_dir=run_dir)

    assert result.status is ActionStatus.SUCCESS
    assert result.data["readiness"]["analysis_status"] == "incomplete"
    assert result.data["readiness"]["reason_codes"] == [
        "missing_required_output:hdf5_fields"
    ]
    assert result.data["recommended_action"] == "review_outputs"
    assert result.data["readiness"]["recommended_command"] == (
        "runo runs log R20260330-0002"
    )
    assert (run_dir / "status" / "readiness.json").is_file()


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


@pytest.mark.parametrize("status", ["created", "failed"])
def test_delete_durably_backfills_run_and_retry_budget_charges(
    tmp_path: Path,
    status: str,
) -> None:
    _create_project_with_case(tmp_path)
    experiment = create_experiment(
        tmp_path,
        title="Deletion accounting",
        question="Does deletion preserve consumed capacity?",
        intent="explore",
        baseline_reason="No compatible baseline exists.",
        max_planned_points=2,
        max_materialized_runs=1,
        max_active_runs=1,
        max_core_hours=4.0,
        max_unreviewed_runs=1,
        expires_at="2099-01-01T00:00:00+00:00",
        exit_criteria=("Account for every materialized Run.",),
    )
    run_id = "R20260901-0001"
    run_dir = tmp_path / "runs" / "case" / run_id
    _write_manifest(
        run_dir,
        {
            "run": {"id": run_id, "status": status},
            "job": {
                "walltime": "01:00:00",
                "ntasks": 1,
                "budget_attempts": [2],
            },
            "intent": {"experiment_id": experiment.experiment.id},
            "identity": {"budget_reservation": f"run:{run_id}"},
        },
    )

    result = execute_action("delete_run", run_dir=run_dir)

    assert result.status is ActionStatus.SUCCESS
    with (tmp_path / ".runops/experiment-usage.toml").open("rb") as stream:
        usage = tomllib.load(stream)
    reservations = usage["experiments"][experiment.experiment.id]["reservations"]
    assert reservations == [
        {"token": f"run:{run_id}", "core_hours": 1.0, "kind": "run"},
        {"token": f"attempt:{run_id}:2", "core_hours": 1.0, "kind": "attempt"},
    ]
    assert not run_dir.exists()


def test_delete_fails_before_rename_when_budget_backfill_cannot_commit(
    tmp_path: Path,
) -> None:
    _create_project_with_case(tmp_path)
    experiment = create_experiment(
        tmp_path,
        title="Deletion failure",
        question="Does accounting failure preserve the Run?",
        intent="explore",
        baseline_reason="No compatible baseline exists.",
        max_planned_points=2,
        max_materialized_runs=1,
        max_active_runs=1,
        max_core_hours=2.0,
        max_unreviewed_runs=1,
        expires_at="2099-01-01T00:00:00+00:00",
        exit_criteria=("Preserve the Run until accounting commits.",),
    )
    run_id = "R20260901-0001"
    run_dir = tmp_path / "runs" / "case" / run_id
    _write_manifest(
        run_dir,
        {
            "run": {"id": run_id, "status": "failed"},
            "job": {"walltime": "01:00:00", "ntasks": 1},
            "intent": {"experiment_id": experiment.experiment.id},
            "identity": {"budget_reservation": f"run:{run_id}"},
        },
    )

    with patch(
        "runops.application.run_budget._write_usage_ledger",
        side_effect=SimctlError("injected ledger failure"),
    ):
        result = execute_action("delete_run", run_dir=run_dir)

    assert result.status is ActionStatus.PRECONDITION_FAILED
    assert "injected ledger failure" in result.message
    assert run_dir.is_dir()
    assert not list(run_dir.parent.glob(".delete-*"))


def test_delete_cleanup_failure_retains_hidden_discoverable_tombstone(
    tmp_path: Path,
) -> None:
    from runops.core.discovery import discover_runs

    run_dir = tmp_path / "runs" / "R20260330-0007"
    _write_manifest(
        run_dir,
        {"run": {"id": run_dir.name, "status": "failed"}},
    )

    with patch(
        "runops.application.actions.admin.shutil.rmtree",
        side_effect=OSError("injected cleanup failure"),
    ):
        result = execute_action("delete_run", run_dir=run_dir)

    assert result.status is ActionStatus.ERROR
    tombstones = list((tmp_path / "runs").glob(".delete-*"))
    assert len(tombstones) == 1
    assert "staged path retained" in result.message
    assert discover_runs(tmp_path / "runs") == []


def test_delete_run_rejects_nonempty_submission_claim(tmp_path: Path) -> None:
    run_dir = tmp_path / "R20260330-0001"
    _write_manifest(
        run_dir,
        {"run": {"id": run_dir.name, "status": "created"}},
    )
    (run_dir / ".runops-submit.lock").write_text(
        "accepted:98765\n",
        encoding="utf-8",
    )

    result = execute_action("delete_run", run_dir=run_dir)

    assert result.status is ActionStatus.PRECONDITION_FAILED
    assert "submission claim" in result.message.lower()
    assert "accepted:98765" in result.message
    assert run_dir.exists()


def test_delete_run_rejects_top_level_symlink_without_deleting_target(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "real" / "R20260330-0001"
    _write_manifest(
        run_dir,
        {"run": {"id": run_dir.name, "status": "created"}},
    )
    link = tmp_path / "linked-run"
    link.symlink_to(run_dir, target_is_directory=True)

    result = execute_action("delete_run", run_dir=link)

    assert result.status is ActionStatus.PRECONDITION_FAILED
    assert "symlink" in result.message.lower()
    assert link.is_symlink()
    assert run_dir.exists()


def test_delete_run_normalizes_parent_symlink_before_atomic_deletion(
    tmp_path: Path,
) -> None:
    real_parent = tmp_path / "real"
    run_dir = real_parent / "R20260330-0001"
    _write_manifest(
        run_dir,
        {"run": {"id": run_dir.name, "status": "created"}},
    )
    alias = tmp_path / "alias"
    alias.symlink_to(real_parent, target_is_directory=True)

    result = execute_action("delete_run", run_dir=alias / run_dir.name)

    assert result.status is ActionStatus.SUCCESS
    assert alias.is_symlink()
    assert not run_dir.exists()


def test_delete_run_waits_for_submit_then_rejects_submitted_run(
    tmp_path: Path,
) -> None:
    from runops.application.execution.submission import (
        SubmitRequest,
        apply_submit,
        plan_submit,
    )

    run_dir = tmp_path / "R20260330-0001"
    _write_manifest(
        run_dir,
        {
            "run": {"id": run_dir.name, "status": "created"},
            "job": {},
        },
    )
    (run_dir / "submit").mkdir(parents=True)
    (run_dir / "submit" / "job.sh").write_text(
        "#!/bin/bash\n#SBATCH --job-name=test\n",
        encoding="utf-8",
    )
    (run_dir / "input").mkdir()
    (run_dir / "input" / "params.json").write_text("{}", encoding="utf-8")
    plan = plan_submit(SubmitRequest(run_dir=run_dir))
    scheduler_entered = Event()
    release_scheduler = Event()
    delete_started = Event()

    def submitter(command: tuple[str, ...]) -> str:
        scheduler_entered.set()
        assert release_scheduler.wait(timeout=5)
        return "98765"

    def delete() -> Any:
        delete_started.set()
        return execute_action("delete_run", run_dir=run_dir)

    with ThreadPoolExecutor(max_workers=2) as executor:
        submitted = executor.submit(apply_submit, plan, submitter)
        assert scheduler_entered.wait(timeout=5)
        deleted = executor.submit(delete)
        assert delete_started.wait(timeout=5)
        assert not deleted.done()
        release_scheduler.set()

        assert submitted.result(timeout=5).job_id == "98765"
        delete_result = deleted.result(timeout=5)

    assert delete_result.status is ActionStatus.PRECONDITION_FAILED
    assert "submitted" in delete_result.message
    assert run_dir.exists()


def test_submit_cannot_enter_after_delete_atomically_removes_run_path(
    tmp_path: Path,
) -> None:
    from runops.application.execution.submission import (
        SubmissionLockError,
        SubmitRequest,
        apply_submit,
        plan_submit,
    )

    run_dir = tmp_path / "R20260330-0001"
    _write_manifest(
        run_dir,
        {
            "run": {"id": run_dir.name, "status": "created"},
            "job": {},
        },
    )
    (run_dir / "submit").mkdir(parents=True)
    (run_dir / "submit" / "job.sh").write_text(
        "#!/bin/bash\n#SBATCH --job-name=test\n",
        encoding="utf-8",
    )
    (run_dir / "input").mkdir()
    (run_dir / "input" / "params.json").write_text("{}", encoding="utf-8")
    plan = plan_submit(SubmitRequest(run_dir=run_dir))
    deletion_entered = Event()
    release_deletion = Event()
    scheduler_calls: list[tuple[str, ...]] = []
    real_rmtree = __import__("shutil").rmtree

    def blocking_rmtree(path: Path) -> None:
        assert path != run_dir
        assert not run_dir.exists()
        deletion_entered.set()
        assert release_deletion.wait(timeout=5)
        real_rmtree(path)

    with (
        patch(
            "runops.application.actions.admin.shutil.rmtree",
            side_effect=blocking_rmtree,
        ),
        ThreadPoolExecutor(max_workers=2) as executor,
    ):
        deleted = executor.submit(execute_action, "delete_run", run_dir=run_dir)
        assert deletion_entered.wait(timeout=5)
        submitted = executor.submit(
            apply_submit,
            plan,
            lambda command: scheduler_calls.append(command) or "98765",
        )
        with pytest.raises(SubmissionLockError):
            submitted.result(timeout=5)
        release_deletion.set()
        delete_result = deleted.result(timeout=5)

    assert delete_result.status is ActionStatus.SUCCESS
    assert scheduler_calls == []
    assert not run_dir.exists()
