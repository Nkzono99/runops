"""Application tests for the read-only experiment triage report."""

from __future__ import annotations

import json
import os
import shlex
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import tomli_w

from runops.application.triage import build_triage_report
from runops.core.discovery import RunDiscoveryError
from runops.core.manifest import ManifestData, write_manifest
from runops.core.test_attempt import build_test_attempt_cache_key, write_test_attempt

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


def _project(root: Path) -> Path:
    (root / "runops.toml").write_text(
        '[project]\nname = "triage-tests"\n',
        encoding="utf-8",
    )
    (root / "runs").mkdir()
    return root


def _write_experiment(
    root: Path,
    experiment_id: str,
    *,
    lifecycle: str = "active",
    decision: str = "pending",
    expires_at: str = "2099-10-01T00:00:00+00:00",
) -> None:
    experiments = root / "experiments"
    experiments.mkdir(exist_ok=True)
    path = experiments / f"{experiment_id}--question.toml"
    path.write_text(
        f"""
schema_version = 1

[experiment]
id = "{experiment_id}"
title = "Bounded question"
lifecycle = "{lifecycle}"
intent = "explore"
decision = "{decision}"
outcome = "unknown"
question = "Does the bounded intervention change the response?"

[baseline]
run_ids = []
reason = "No compatible baseline exists."

[budget]
max_planned_points = 4
max_materialized_runs = 3
max_active_runs = 2
max_core_hours = 20.0
max_unreviewed_runs = 2
expires_at = "{expires_at}"

[exit]
criteria = ["Stop after the response is resolved."]
review_due = "2026-09-15T00:00:00+00:00"
""".strip()
        + "\n",
        encoding="utf-8",
    )


def _write_run(
    root: Path,
    run_id: str,
    *,
    status: str,
    experiment_id: str = "",
    review_status: str = "unreviewed",
) -> Path:
    run_dir = root / "runs" / run_id
    write_manifest(
        run_dir,
        ManifestData(
            run={"id": run_id, "status": status},
            intent={"experiment_id": experiment_id, "purpose": "explore"},
            curation=(
                {
                    "review_status": "reviewed",
                    "reviewed_at": "2026-09-01T00:00:00+00:00",
                    "reviewed_by": "human",
                    "reason": "checked during triage",
                }
                if review_status == "reviewed"
                else {"review_status": review_status}
            ),
        ),
    )
    return run_dir


def _setup_adoption_bundle(root: Path) -> tuple[Path, Path]:
    source = root / "runs" / "scan"
    current = source / "R20260901-0002"
    write_manifest(
        current,
        ManifestData(run={"id": current.name, "status": "cancelled"}),
    )
    destination = root / "runs" / "_archive" / "scan"
    adopted = destination / "nested" / "R20260901-0001"
    write_manifest(
        adopted,
        ManifestData(
            run={"id": adopted.name, "status": "archived"},
            path={
                "run_dir": str(adopted),
                "archived_from": str(source / "nested" / adopted.name),
            },
        ),
    )
    return source, destination


def _write_attempt(
    root: Path,
    attempt_id: str,
    *,
    state: str,
    updated_at: datetime,
) -> None:
    attempt_dir = root / ".runops" / "test-runs" / attempt_id
    finished_at = (
        updated_at.isoformat() if state in {"passed", "failed", "skipped"} else ""
    )
    cache_key = build_test_attempt_cache_key(
        kind="smoke",
        case="base",
        profile="smoke",
        source_commit="abc123",
        executable_hash="sha256:" + "1" * 64,
        input_hash="sha256:" + "2" * 64,
        adapter="generic",
        adapter_version="1.0",
    )
    write_test_attempt(
        attempt_dir,
        {
            "schema_version": 1,
            "test": {
                "id": attempt_id,
                "kind": "smoke",
                "state": state,
                "case": "base",
                "profile": "smoke",
                "source_commit": "abc123",
                "executable_hash": "sha256:" + "1" * 64,
                "input_hash": "sha256:" + "2" * 64,
                "adapter": "generic",
                "adapter_version": "1.0",
                "cache_key": cache_key,
                "created_at": updated_at.isoformat(),
                "updated_at": updated_at.isoformat(),
                "started_at": "",
                "finished_at": finished_at,
                "observation": "",
                "cached_from": "",
            },
        },
    )


def _write_result(root: Path, result_id: str, *, archived: bool = False) -> None:
    result_root = (
        root / "research" / "archive" / "results"
        if archived
        else root / "research" / "results"
    )
    result_dir = result_root / result_id
    result_dir.mkdir(parents=True)
    with (result_dir / "manifest.toml").open("wb") as stream:
        tomli_w.dump(
            {
                "result": {
                    "schema_version": 1,
                    "id": result_id,
                    "status": "draft",
                    "title": "A result",
                    "claim": "",
                    "outcome": "",
                }
            },
            stream,
        )


def _file_snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_report_counts_active_work_without_mixing_test_attempts_into_runs(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    experiment_id = "E20260901-0001"
    _write_experiment(project, experiment_id)
    _write_experiment(
        project,
        "E20260901-0002",
        lifecycle="closed",
        decision="accept",
    )
    _write_run(
        project,
        "R20260901-0001",
        status="completed",
        experiment_id=experiment_id,
    )
    _write_run(
        project,
        "R20260901-0002",
        status="running",
        experiment_id=experiment_id,
    )
    _write_run(
        project,
        "R20260901-0003",
        status="archived",
        experiment_id=experiment_id,
    )
    _write_attempt(
        project,
        "T20260801-0001",
        state="passed",
        updated_at=NOW - timedelta(days=31),
    )
    _write_attempt(
        project,
        "T20260901-0001",
        state="prepared",
        updated_at=NOW - timedelta(hours=1),
    )
    _write_result(project, "R0001-active")
    _write_result(project, "R0002-archived", archived=True)
    before = _file_snapshot(project)

    report = build_triage_report(project, now=NOW)

    assert report.active_experiment_count == 1
    assert report.pending_decision_count == 1
    assert report.active_experiments[0].experiment_id == experiment_id
    assert report.active_experiments[0].run_status_counts == {
        "completed": 1,
        "running": 1,
    }
    assert report.active_formal_run_count == 2
    assert report.run_status_counts == {"completed": 1, "running": 1}
    assert report.run_experiment_counts == {experiment_id: 2}
    assert report.unreviewed_completed_count == 2
    assert report.test_attempt_count == 2
    assert report.old_test_attempt_count == 1
    assert report.old_terminal_test_attempt_count == 1
    assert report.old_active_test_attempt_count == 0
    assert report.active_result_count == 1
    assert report.archived_result_count == 1
    assert any("experiments review" in action for action in report.suggested_actions)
    assert any("runs review" in action for action in report.suggested_actions)
    assert any("test clean" in action for action in report.suggested_actions)
    assert _file_snapshot(project) == before


def test_expired_active_experiment_is_reported_and_prioritized_for_closure(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    experiment_id = "E20260901-0001"
    _write_experiment(
        project,
        experiment_id,
        expires_at="2026-09-01T11:59:59+00:00",
    )

    report = build_triage_report(project, now=NOW)

    experiment = report.active_experiments[0]
    assert experiment.expires_at == "2026-09-01T11:59:59+00:00"
    assert experiment.expired is True
    assert any(item.code == "experiment.expired" for item in report.diagnostics)
    assert report.suggested_actions[0].startswith(
        f"Close or supersede expired Experiment {experiment_id}"
    )
    assert not any(
        "invalid project record" in item for item in report.suggested_actions
    )


def test_triage_counts_incomplete_review_record_as_unreviewed(tmp_path: Path) -> None:
    project = _project(tmp_path)
    experiment_id = "E20260901-0001"
    _write_experiment(project, experiment_id)
    write_manifest(
        project / "runs" / "R20260901-0001",
        ManifestData(
            run={"id": "R20260901-0001", "status": "completed"},
            intent={"experiment_id": experiment_id, "purpose": "explore"},
            curation={
                "review_status": "reviewed",
                "reviewed_at": "2026-09-01T00:00:00+00:00",
                "reviewed_by": "human",
            },
        ),
    )

    report = build_triage_report(project, now=NOW)

    assert report.unreviewed_completed_count == 1


def test_invalid_records_are_reported_while_valid_records_remain_visible(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    experiment_id = "E20260901-0001"
    _write_experiment(project, experiment_id)
    invalid_experiment = project / "experiments" / "E20260901-0002--broken.toml"
    invalid_experiment.write_text("not = [valid\n", encoding="utf-8")
    _write_run(
        project,
        "R20260901-0001",
        status="completed",
        experiment_id=experiment_id,
        review_status="reviewed",
    )
    broken_run = project / "runs" / "broken"
    broken_run.mkdir()
    (broken_run / "manifest.toml").write_text("[run\n", encoding="utf-8")
    _write_attempt(
        project,
        "T20260801-0001",
        state="passed",
        updated_at=NOW - timedelta(days=31),
    )
    broken_attempt = project / ".runops" / "test-runs" / "T20260801-0002"
    broken_attempt.mkdir()
    (broken_attempt / "test-receipt.toml").write_text("[test\n", encoding="utf-8")
    _write_result(project, "R0001-valid")
    broken_result = project / "research" / "results" / "R0002-broken"
    broken_result.mkdir()
    (broken_result / "manifest.toml").write_text("[result\n", encoding="utf-8")

    report = build_triage_report(project, now=NOW)

    assert report.active_experiment_count == 1
    assert report.run_namespace_available is False
    assert report.active_formal_run_count is None
    assert report.run_status_counts is None
    assert report.run_experiment_counts is None
    assert report.unreviewed_completed_count is None
    assert report.test_attempt_count == 1
    assert report.old_test_attempt_count == 1
    assert report.active_result_count == 1
    sections = {diagnostic.section for diagnostic in report.diagnostics}
    assert {"experiments", "runs", "test_attempts", "results"} <= sections
    assert any("Resolve 4 invalid" in action for action in report.suggested_actions)


def test_archived_malformed_manifest_makes_all_run_counts_unavailable(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    _write_run(project, "R20260901-0001", status="running")
    broken = project / "runs" / "_archive" / "old" / "broken"
    broken.mkdir(parents=True)
    (broken / "manifest.toml").write_text("[run\n", encoding="utf-8")

    report = build_triage_report(project, now=NOW)

    assert report.run_namespace_available is False
    assert report.active_formal_run_count is None
    assert report.run_status_counts is None
    assert report.run_experiment_counts is None
    assert report.run_experiment_status_counts is None
    assert report.unreviewed_completed_count is None
    assert any(
        item.code == "run.namespace_unreadable"
        and "runs/_archive/old/broken" in item.message
        for item in report.diagnostics
    )


def test_duplicate_run_id_makes_all_triage_counts_unavailable(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    run_id = "R20260901-0001"
    _write_run(project, run_id, status="running")
    write_manifest(
        project / "runs" / "_archive" / "old" / run_id,
        ManifestData(run={"id": run_id, "status": "archived"}),
    )

    report = build_triage_report(project, now=NOW)

    assert report.run_namespace_available is False
    assert report.active_formal_run_count is None
    assert report.run_status_counts is None
    assert report.run_experiment_counts is None
    assert report.run_experiment_status_counts is None
    assert report.unreviewed_completed_count is None
    assert any(
        item.code == "run.namespace_unreadable"
        and run_id in item.message
        and "duplicated" in item.message
        for item in report.diagnostics
    )


def test_run_namespace_symlink_is_reported_instead_of_silently_omitted(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (project / "runs" / "hidden").symlink_to(
        outside,
        target_is_directory=True,
    )

    report = build_triage_report(project, now=NOW)

    assert report.run_namespace_available is False
    assert report.active_formal_run_count is None
    assert report.to_dict()["runs"]["active_formal_count"] is None
    diagnostic = next(
        item for item in report.diagnostics if item.code == "run.namespace_unreadable"
    )
    assert diagnostic.path.endswith("runs")
    assert "symbolic link" in diagnostic.message


def test_run_namespace_walk_error_makes_triage_counts_explicitly_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from runops.application import run_query as run_query_module

    project = _project(tmp_path)

    def fail_discovery(_runs_dir: Path) -> list[Path]:
        raise RunDiscoveryError("unreadable subtree")

    monkeypatch.setattr(
        run_query_module,
        "discover_runs_checked",
        fail_discovery,
    )

    report = build_triage_report(project, now=NOW)

    assert report.run_namespace_available is False
    assert report.active_formal_run_count is None
    assert any(
        item.code == "run.namespace_unreadable" and "unreadable subtree" in item.message
        for item in report.diagnostics
    )


def test_corrupt_bundle_marker_cannot_hide_runs_from_triage(tmp_path: Path) -> None:
    project = _project(tmp_path)
    bundle = project / "runs" / "bundle"
    run_dir = bundle / "R20260901-0001"
    write_manifest(
        run_dir,
        ManifestData(run={"id": run_dir.name, "status": "running"}),
    )
    (bundle / ".runops-archive.toml").write_text("[bundle\n", encoding="utf-8")

    report = build_triage_report(project, now=NOW)

    assert report.run_namespace_available is False
    assert report.active_formal_run_count is None
    assert any(
        item.code == "run.namespace_unreadable"
        and "Invalid archive marker" in item.message
        for item in report.diagnostics
    )


def test_default_old_test_attempt_boundary_is_fourteen_days(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _write_attempt(
        project,
        "T20260818-0001",
        state="failed",
        updated_at=NOW - timedelta(days=14),
    )
    _write_attempt(
        project,
        "T20260818-0002",
        state="failed",
        updated_at=NOW - timedelta(days=14) + timedelta(seconds=1),
    )

    report = build_triage_report(project, now=NOW)

    assert report.test_attempt_age_days == 14
    assert report.old_test_attempt_count == 1


@pytest.mark.parametrize(
    "staging_name",
    [".tmp-R20260901-0001", ".delete-R20260901-0001-deadbeef"],
)
def test_old_hidden_staging_is_reported_without_becoming_a_run(
    tmp_path: Path,
    staging_name: str,
) -> None:
    project = _project(tmp_path)
    staging = project / "runs" / "scan" / staging_name
    staging.mkdir(parents=True)
    (staging / "manifest.toml").write_text(
        '[run]\nid = "R20260901-0001"\nstatus = "created"\n',
        encoding="utf-8",
    )
    old = (NOW - timedelta(hours=25)).timestamp()
    os.utime(staging, (old, old))

    report = build_triage_report(project, now=NOW)

    assert report.active_formal_run_count == 0
    assert any(
        item.code == "staging.orphan_candidate" and item.path.endswith(staging.name)
        for item in report.diagnostics
    )
    assert any("stale unpublished" in item for item in report.suggested_actions)


def test_pending_bundle_adoption_is_reported_immediately_with_retry_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from runops.application.actions import archive_bundle
    from runops.application.actions import bundle_archive as bundle_module

    project = _project(tmp_path)
    source, destination = _setup_adoption_bundle(project)
    real_move = bundle_module.move_directory_noreplace

    def interrupt_first_move(current: Path, target: Path) -> None:
        real_move(current, target)
        raise KeyboardInterrupt("simulated process death after durable move")

    monkeypatch.setattr(
        bundle_module,
        "move_directory_noreplace",
        interrupt_first_move,
    )
    with pytest.raises(KeyboardInterrupt):
        archive_bundle(source, adopt_archived=True)

    transaction = next(destination.parent.glob(".tmp-adopt-scan-*"))
    assert (transaction / "receipt.toml").is_file()

    report = build_triage_report(project, now=NOW)

    diagnostic = next(
        item for item in report.diagnostics if item.code == "bundle.adoption_pending"
    )
    assert diagnostic.path.endswith("receipt.toml")
    assert f"runo runs archive {source} --bundle --adopt-archived" in diagnostic.message
    assert report.active_formal_run_count == 1


def test_receiptless_bundle_adoption_cleanup_is_reported_immediately(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from runops.application.actions import archive_bundle
    from runops.application.actions import bundle_archive as bundle_module

    project = _project(tmp_path)
    source, destination = _setup_adoption_bundle(project)
    real_unlink = bundle_module._unlink_file_durable

    def interrupt_after_receipt_unlink(path: Path) -> None:
        real_unlink(path)
        if path.name == "receipt.toml":
            raise KeyboardInterrupt("simulated process death after receipt cleanup")

    monkeypatch.setattr(
        bundle_module,
        "_unlink_file_durable",
        interrupt_after_receipt_unlink,
    )
    with pytest.raises(KeyboardInterrupt):
        archive_bundle(source, adopt_archived=True)

    transaction = next(destination.parent.glob(".tmp-adopt-scan-*"))

    report = build_triage_report(project, now=NOW)

    diagnostic = next(
        item for item in report.diagnostics if item.code == "bundle.adoption_pending"
    )
    assert diagnostic.path.endswith(transaction.name)
    assert f"runo runs archive {source} --bundle --adopt-archived" in diagnostic.message


def test_pending_purge_receipt_is_reported_inside_formal_run(tmp_path: Path) -> None:
    project = _project(tmp_path)
    run_dir = _write_run(project, "R20260901-0001", status="archived")
    receipt = run_dir / "status" / ".purge-pending.json"
    receipt.parent.mkdir()
    receipt.write_text('{"schema_version": 1}\n', encoding="utf-8")

    report = build_triage_report(project, now=NOW)

    diagnostic = next(
        item for item in report.diagnostics if item.code == "purge.transaction_pending"
    )
    assert diagnostic.path.endswith("status/.purge-pending.json")
    assert "runo runs purge" in diagnostic.message


def test_pending_purge_retry_command_shell_quotes_the_run_path(tmp_path: Path) -> None:
    project = _project(tmp_path)
    original = _write_run(project, "R20260901-0001", status="archived")
    run_dir = project / "runs" / "scan ; echo unsafe" / original.name
    run_dir.parent.mkdir()
    original.rename(run_dir)
    receipt = run_dir / "status" / ".purge-pending.json"
    receipt.parent.mkdir()
    receipt.write_text('{"schema_version": 1}\n', encoding="utf-8")

    report = build_triage_report(project, now=NOW)

    diagnostic = next(
        item for item in report.diagnostics if item.code == "purge.transaction_pending"
    )
    assert f"runo runs purge-work {shlex.quote(str(run_dir))}" in diagnostic.message


@pytest.mark.parametrize(
    ("action", "source_relative", "destination_relative", "code", "command"),
    [
        (
            "archive_run",
            "runs/scan/R20260901-0001",
            "runs/_archive/scan/R20260901-0001",
            "run.archive_pending",
            "runo runs archive",
        ),
        (
            "restore_run",
            "runs/_archive/scan/R20260901-0001",
            "runs/scan/R20260901-0001",
            "run.restore_pending",
            "runo runs restore",
        ),
    ],
)
def test_pending_run_lifecycle_receipt_is_reported_with_retry_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    source_relative: str,
    destination_relative: str,
    code: str,
    command: str,
) -> None:
    from runops.application.actions import ActionStatus, archive_run, restore_run
    from runops.application.actions import admin as admin_module

    project = _project(tmp_path)
    active = _write_run(project, "R20260901-0001", status="completed")
    expected_source = project / source_relative
    expected_destination = project / destination_relative
    if action == "archive_run":
        source = active
        destination = expected_destination
    else:
        archive_result = archive_run(active, move_to=expected_source)
        assert archive_result.status is ActionStatus.SUCCESS
        source = expected_source
        destination = expected_destination

    real_write_receipt = admin_module._write_lifecycle_receipt

    def interrupt_after_receipt(**kwargs: object) -> None:
        real_write_receipt(**kwargs)
        raise KeyboardInterrupt("simulated process death after lifecycle receipt")

    monkeypatch.setattr(
        admin_module,
        "_write_lifecycle_receipt",
        interrupt_after_receipt,
    )
    with pytest.raises(KeyboardInterrupt):
        if action == "archive_run":
            archive_run(source, move_to=destination)
        else:
            restore_run(source)

    receipt = next((project / ".runops" / "lifecycle").glob(f"{action}-*.json"))

    report = build_triage_report(project, now=NOW)

    diagnostic = next(item for item in report.diagnostics if item.code == code)
    assert diagnostic.path.endswith(receipt.name)
    assert command in diagnostic.message
    assert str(source) in diagnostic.message


def test_tampered_lifecycle_receipt_is_not_presented_as_recoverable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from runops.application.actions import admin as admin_module
    from runops.application.actions import archive_run

    project = _project(tmp_path)
    source = _write_run(project, "R20260901-0001", status="completed")
    destination = project / "runs" / "_archive" / source.name
    real_write_receipt = admin_module._write_lifecycle_receipt

    def interrupt_after_receipt(**kwargs: object) -> None:
        real_write_receipt(**kwargs)
        raise KeyboardInterrupt("simulated process death after lifecycle receipt")

    monkeypatch.setattr(
        admin_module,
        "_write_lifecycle_receipt",
        interrupt_after_receipt,
    )
    with pytest.raises(KeyboardInterrupt):
        archive_run(source, move_to=destination)

    receipt = next((project / ".runops" / "lifecycle").glob("archive_run-*.json"))
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    payload["manifest_sha256"] = "0" * 64
    receipt.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    report = build_triage_report(project, now=NOW)

    assert not any(item.code == "run.archive_pending" for item in report.diagnostics)
    assert any(
        item.code == "lifecycle.receipt_invalid" and "digest mismatch" in item.message
        for item in report.diagnostics
    )
