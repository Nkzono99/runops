"""Durable Experiment budget accounting tests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import Event

import pytest
import tomli as tomllib
import tomli_w

from runops.application import run_budget as run_budget_module
from runops.application.actions import ActionStatus, archive_run, retry_run
from runops.application.experiments import create_experiment
from runops.application.run_budget import (
    declared_job_core_hours,
    declared_manifest_core_hours,
    enforce_experiment_run_budget,
    reserve_experiment_retry_budget,
)
from runops.core.case import JobData
from runops.core.exceptions import SimctlError
from runops.core.experiment import (
    ExperimentBaseline,
    ExperimentBudget,
    ExperimentData,
)
from runops.core.manifest import read_manifest
from runops.core.project import ExperimentPolicy, ProjectConfig


def _project(root: Path, *, max_project_unreviewed: int = 3) -> ProjectConfig:
    return ProjectConfig(
        name="budget-test",
        description="",
        root_dir=root,
        experiment_policy=ExperimentPolicy(
            max_unreviewed_completed_runs=max_project_unreviewed
        ),
    )


def _experiment(
    root: Path,
    *,
    experiment_id: str = "E20260901-0001",
    max_active: int = 1,
    max_core_hours: float = 3.0,
    max_materialized: int = 1,
    max_unreviewed: int = 2,
) -> ExperimentData:
    return ExperimentData(
        id=experiment_id,
        title="Retry budget",
        question="Can this Run be retried within budget?",
        lifecycle="active",
        intent="validate",
        decision="expand",
        outcome="unknown",
        baseline=ExperimentBaseline(reason="No compatible baseline exists."),
        budget=ExperimentBudget(
            max_planned_points=2,
            max_materialized_runs=max_materialized,
            max_active_runs=max_active,
            max_core_hours=max_core_hours,
            max_unreviewed_runs=max_unreviewed,
            expires_at="2099-01-01T00:00:00+00:00",
        ),
        exit_criteria=("Resolve the failure.",),
        review_due="",
        experiment_file=root / "experiments" / f"{experiment_id}--retry.toml",
    )


def _run(
    root: Path,
    run_id: str,
    *,
    status: str,
    experiment_id: str = "E20260901-0001",
    curation: dict[str, object] | None = None,
) -> Path:
    run_dir = root / "runs" / "case" / run_id
    run_dir.mkdir(parents=True)
    with (run_dir / "manifest.toml").open("wb") as stream:
        data: dict[str, object] = {
            "run": {"id": run_id, "status": status},
            "job": {"walltime": "01:00:00", "ntasks": 1},
            "intent": {"experiment_id": experiment_id},
            "identity": {"budget_reservation": f"run:{run_id}"},
        }
        if curation is not None:
            data["curation"] = curation
        tomli_w.dump(data, stream)
    return run_dir


def test_retry_consumes_core_hours_but_not_materialized_slot_and_is_idempotent(
    tmp_path: Path,
) -> None:
    run_dir = _run(tmp_path, "R20260901-0001", status="failed")
    project = _project(tmp_path)
    experiment = _experiment(tmp_path)
    manifest = read_manifest(run_dir)

    reserve_experiment_retry_budget(
        project,
        experiment,
        manifest=manifest,
        next_attempt=2,
    )
    reserve_experiment_retry_budget(
        project,
        experiment,
        manifest=manifest,
        next_attempt=2,
    )

    with (tmp_path / ".runops" / "experiment-usage.toml").open("rb") as stream:
        ledger = tomllib.load(stream)
    reservations = ledger["experiments"][experiment.id]["reservations"]
    assert reservations == [
        {"token": "run:R20260901-0001", "core_hours": 1.0, "kind": "run"},
        {
            "token": "attempt:R20260901-0001:2",
            "core_hours": 1.0,
            "kind": "attempt",
        },
    ]

    with pytest.raises(SimctlError, match="core-hour budget exceeded by retry"):
        reserve_experiment_retry_budget(
            project,
            _experiment(tmp_path, max_core_hours=2.0),
            manifest=manifest,
            next_attempt=3,
        )


def test_retry_reactivation_obeys_active_run_wip_limit(tmp_path: Path) -> None:
    failed = _run(tmp_path, "R20260901-0001", status="failed")
    _run(tmp_path, "R20260901-0002", status="created")

    with pytest.raises(SimctlError, match="WIP limit exceeded by retry"):
        reserve_experiment_retry_budget(
            _project(tmp_path),
            _experiment(tmp_path, max_active=1, max_core_hours=10.0),
            manifest=read_manifest(failed),
            next_attempt=2,
        )


def test_retry_budget_rejects_hidden_symlink_run_namespace(tmp_path: Path) -> None:
    failed = _run(tmp_path, "R20260901-0001", status="failed")
    outside = tmp_path / "outside-runs"
    hidden = outside / "R20260901-0002"
    hidden.mkdir(parents=True)
    with (hidden / "manifest.toml").open("wb") as stream:
        tomli_w.dump(
            {
                "run": {"id": hidden.name, "status": "created"},
                "intent": {"experiment_id": "E20260901-0001"},
            },
            stream,
        )
    (tmp_path / "runs" / "hidden").symlink_to(outside, target_is_directory=True)

    with pytest.raises(SimctlError, match="symbolic link"):
        reserve_experiment_retry_budget(
            _project(tmp_path),
            _experiment(tmp_path, max_active=1, max_core_hours=10.0),
            manifest=read_manifest(failed),
            next_attempt=2,
        )

    assert not (tmp_path / ".runops" / "experiment-usage.toml").exists()


def test_corrupt_usage_ledger_fails_closed_without_replacement(tmp_path: Path) -> None:
    run_dir = _run(tmp_path, "R20260901-0001", status="failed")
    ledger = tmp_path / ".runops" / "experiment-usage.toml"
    ledger.parent.mkdir(parents=True)
    ledger.write_text("not = [valid", encoding="utf-8")

    with pytest.raises(SimctlError, match="cannot read Experiment usage ledger"):
        reserve_experiment_retry_budget(
            _project(tmp_path),
            _experiment(tmp_path),
            manifest=read_manifest(run_dir),
            next_attempt=2,
        )

    assert ledger.read_text(encoding="utf-8") == "not = [valid"


def test_budget_scan_serializes_with_individual_archive_move(tmp_path: Path) -> None:
    (tmp_path / "runops.toml").write_text(
        '[project]\nname = "namespace-test"\n',
        encoding="utf-8",
    )
    run_dir = _run(tmp_path, "R20260901-0001", status="completed")
    entered_scan = Event()
    release_scan = Event()
    archive_started = Event()
    real_collect = run_budget_module.collect_run_manifests_strict

    def blocked_collect(runs_root: Path):
        entered_scan.set()
        assert release_scan.wait(timeout=5)
        return real_collect(runs_root)

    def archive() -> object:
        archive_started.set()
        return archive_run(run_dir)

    with (
        pytest.MonkeyPatch.context() as monkeypatch,
        ThreadPoolExecutor(max_workers=2) as executor,
    ):
        monkeypatch.setattr(
            run_budget_module,
            "collect_run_manifests_strict",
            blocked_collect,
        )
        scanned = executor.submit(
            run_budget_module.collect_experiment_run_records,
            tmp_path,
            "E20260901-0001",
        )
        assert entered_scan.wait(timeout=5)
        archived = executor.submit(archive)
        assert archive_started.wait(timeout=5)
        assert not archived.done()
        release_scan.set()

        records = scanned.result(timeout=5)
        archive_result = archived.result(timeout=5)

    assert len(records) == 1
    assert archive_result.status is ActionStatus.SUCCESS


@pytest.mark.parametrize("status", ["completed", "archived", "purged"])
def test_storage_lifecycle_cannot_hide_unreviewed_backlog(
    tmp_path: Path,
    status: str,
) -> None:
    _run(tmp_path, "R20260901-0001", status=status)

    with pytest.raises(SimctlError, match="unreviewed completed Run backlog"):
        enforce_experiment_run_budget(
            _project(tmp_path),
            _experiment(
                tmp_path,
                max_active=3,
                max_core_hours=10.0,
                max_materialized=3,
                max_unreviewed=1,
            ),
            new_count=1,
            new_core_hours=1.0,
            reservation_tokens=("run:R20260901-0002",),
            persist=False,
        )


def test_project_unreviewed_cap_counts_other_experiment_runs(tmp_path: Path) -> None:
    _run(
        tmp_path,
        "R20260901-0001",
        status="completed",
        experiment_id="E20260901-0001",
    )

    with pytest.raises(
        SimctlError,
        match="project-wide unreviewed completed Run backlog",
    ):
        enforce_experiment_run_budget(
            _project(tmp_path, max_project_unreviewed=1),
            _experiment(
                tmp_path,
                experiment_id="E20260901-0002",
                max_active=3,
                max_core_hours=10.0,
                max_materialized=3,
                max_unreviewed=1,
            ),
            new_count=1,
            new_core_hours=1.0,
            reservation_tokens=("run:R20260901-0002",),
            persist=False,
        )


def test_experiment_unreviewed_cap_only_counts_current_owner(tmp_path: Path) -> None:
    _run(
        tmp_path,
        "R20260901-0001",
        status="completed",
        experiment_id="E20260901-0001",
    )

    enforce_experiment_run_budget(
        _project(tmp_path, max_project_unreviewed=2),
        _experiment(
            tmp_path,
            experiment_id="E20260901-0002",
            max_active=3,
            max_core_hours=10.0,
            max_materialized=3,
            max_unreviewed=1,
        ),
        new_count=1,
        new_core_hours=1.0,
        reservation_tokens=("run:R20260901-0002",),
        persist=False,
    )


@pytest.mark.parametrize(
    "curation",
    [
        {
            "review_status": "accepted",
            "reviewed_at": "2026-09-01T00:00:00+00:00",
            "reviewed_by": "human",
            "reason": "checked",
        },
        {
            "review_status": "reviewed",
            "reviewed_at": "2026-09-01T00:00:00+00:00",
            "reviewed_by": "human",
        },
        {
            "review_status": "reviewed",
            "reviewed_by": "human",
            "reason": "checked",
        },
        {
            "review_status": "reviewed",
            "reviewed_at": "not-a-timestamp",
            "reviewed_by": "human",
            "reason": "checked",
        },
    ],
    ids=("invalid-status", "missing-reason", "missing-timestamp", "bad-timestamp"),
)
def test_incomplete_review_record_cannot_bypass_experiment_backlog_cap(
    tmp_path: Path,
    curation: dict[str, object],
) -> None:
    _run(
        tmp_path,
        "R20260901-0001",
        status="completed",
        curation=curation,
    )

    with pytest.raises(SimctlError, match="Experiment unreviewed completed Run"):
        enforce_experiment_run_budget(
            _project(tmp_path, max_project_unreviewed=10),
            _experiment(
                tmp_path,
                max_active=3,
                max_core_hours=10.0,
                max_materialized=3,
                max_unreviewed=1,
            ),
            new_count=1,
            new_core_hours=1.0,
            reservation_tokens=("run:R20260901-0002",),
            persist=False,
        )


def test_incomplete_review_record_cannot_bypass_project_backlog_cap(
    tmp_path: Path,
) -> None:
    _run(
        tmp_path,
        "R20260901-0001",
        status="completed",
        experiment_id="E20260901-0001",
        curation={
            "review_status": "reviewed",
            "reviewed_at": "2026-09-01T00:00:00+00:00",
            "reviewed_by": "human",
            "reason": "",
        },
    )

    with pytest.raises(SimctlError, match="project-wide unreviewed completed Run"):
        enforce_experiment_run_budget(
            _project(tmp_path, max_project_unreviewed=1),
            _experiment(
                tmp_path,
                experiment_id="E20260901-0002",
                max_active=3,
                max_core_hours=10.0,
                max_materialized=3,
                max_unreviewed=1,
            ),
            new_count=1,
            new_core_hours=1.0,
            reservation_tokens=("run:R20260901-0002",),
            persist=False,
        )


def test_complete_review_record_releases_both_backlog_caps(tmp_path: Path) -> None:
    _run(
        tmp_path,
        "R20260901-0001",
        status="completed",
        curation={
            "review_status": "reviewed",
            "reviewed_at": "2026-09-01T00:00:00+00:00",
            "reviewed_by": "human",
            "reason": "The outcome and diagnostics were checked.",
        },
    )

    enforce_experiment_run_budget(
        _project(tmp_path, max_project_unreviewed=1),
        _experiment(
            tmp_path,
            max_active=3,
            max_core_hours=10.0,
            max_materialized=3,
            max_unreviewed=1,
        ),
        new_count=1,
        new_core_hours=1.0,
        reservation_tokens=("run:R20260901-0002",),
        persist=False,
    )


def test_project_unreviewed_cap_blocks_cross_experiment_retry(tmp_path: Path) -> None:
    (tmp_path / "runops.toml").write_text(
        "[project]\n"
        'name = "budget-test"\n\n'
        "[experiments.policy]\n"
        "max_active_experiments = 3\n"
        "max_unreviewed_completed_runs = 1\n",
        encoding="utf-8",
    )
    (tmp_path / "runs").mkdir()
    first = create_experiment(
        tmp_path,
        title="First question",
        question="Is the first hypothesis supported?",
        intent="validate",
        baseline_reason="No compatible baseline exists.",
        max_planned_points=2,
        max_materialized_runs=2,
        max_active_runs=2,
        max_core_hours=10.0,
        max_unreviewed_runs=2,
        expires_at="2099-01-01T00:00:00+00:00",
        exit_criteria=("Resolve the first hypothesis.",),
        now=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
    second = create_experiment(
        tmp_path,
        title="Second question",
        question="Can the failed second experiment be retried?",
        intent="validate",
        baseline_reason="No compatible baseline exists.",
        max_planned_points=2,
        max_materialized_runs=2,
        max_active_runs=2,
        max_core_hours=10.0,
        max_unreviewed_runs=2,
        expires_at="2099-01-01T00:00:00+00:00",
        exit_criteria=("Resolve the second failure.",),
        now=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
    _run(
        tmp_path,
        "R20260901-0001",
        status="completed",
        experiment_id=first.experiment.id,
    )
    failed = _run(
        tmp_path,
        "R20260901-0002",
        status="failed",
        experiment_id=second.experiment.id,
    )

    result = retry_run(failed)

    assert result.status is ActionStatus.PRECONDITION_FAILED
    assert "project-wide unreviewed completed Run backlog" in result.message
    assert read_manifest(failed).run["status"] == "failed"


def test_project_unreviewed_cap_blocks_ownerless_retry(tmp_path: Path) -> None:
    (tmp_path / "runops.toml").write_text(
        "[project]\n"
        'name = "budget-test"\n\n'
        "[experiments.policy]\n"
        "require_experiment = false\n"
        "max_unreviewed_completed_runs = 1\n",
        encoding="utf-8",
    )
    (tmp_path / "runs").mkdir()
    _run(
        tmp_path,
        "R20260901-0001",
        status="completed",
        experiment_id="",
    )
    failed = _run(
        tmp_path,
        "R20260901-0002",
        status="failed",
        experiment_id="",
    )

    result = retry_run(failed)

    assert result.status is ActionStatus.PRECONDITION_FAILED
    assert "project-wide unreviewed completed Run backlog" in result.message
    assert read_manifest(failed).run["status"] == "failed"


def test_ownerless_retry_cannot_bypass_required_experiment_policy(
    tmp_path: Path,
) -> None:
    (tmp_path / "runops.toml").write_text(
        "[project]\n"
        'name = "budget-test"\n\n'
        "[experiments.policy]\n"
        "require_experiment = true\n"
        "max_unreviewed_completed_runs = 10\n",
        encoding="utf-8",
    )
    (tmp_path / "runs").mkdir()
    failed = _run(
        tmp_path,
        "R20260901-0001",
        status="failed",
        experiment_id="",
    )
    failed_manifest = read_manifest(failed)
    failed_manifest.job["job_id"] = "old-job-id"
    with (failed / "manifest.toml").open("wb") as stream:
        tomli_w.dump(failed_manifest.to_dict(), stream)
    claim = failed / ".runops-submit.lock"
    claim.write_text("accepted:old-job-id\n", encoding="utf-8")
    manifest_before = (failed / "manifest.toml").read_bytes()
    claim_before = claim.read_bytes()

    result = retry_run(failed)

    assert result.status is ActionStatus.PRECONDITION_FAILED
    assert "requires --experiment" in result.message
    assert (failed / "manifest.toml").read_bytes() == manifest_before
    assert claim.read_bytes() == claim_before


def test_expired_owned_retry_preserves_manifest_claim_and_budget_ledger(
    tmp_path: Path,
) -> None:
    (tmp_path / "runops.toml").write_text(
        "[project]\n"
        'name = "budget-test"\n\n'
        "[experiments.policy]\n"
        "require_experiment = true\n"
        "max_unreviewed_completed_runs = 10\n",
        encoding="utf-8",
    )
    (tmp_path / "runs").mkdir()
    admitted = create_experiment(
        tmp_path,
        title="Expired retry",
        question="Can an expired Experiment retry a failed Run?",
        intent="validate",
        baseline_reason="No compatible baseline exists.",
        max_planned_points=2,
        max_materialized_runs=2,
        max_active_runs=2,
        max_core_hours=10.0,
        max_unreviewed_runs=2,
        expires_at="2099-01-01T00:00:00+00:00",
        exit_criteria=("Stop before retrying after expiry.",),
        now=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
    admitted.path.write_text(
        admitted.path.read_text(encoding="utf-8").replace(
            'expires_at = "2099-01-01T00:00:00+00:00"',
            'expires_at = "2000-01-01T00:00:00+00:00"',
        ),
        encoding="utf-8",
    )
    failed = _run(
        tmp_path,
        "R20260901-0001",
        status="failed",
        experiment_id=admitted.experiment.id,
    )
    manifest = read_manifest(failed)
    manifest.job["job_id"] = "old-job-id"
    with (failed / "manifest.toml").open("wb") as stream:
        tomli_w.dump(manifest.to_dict(), stream)
    claim = failed / ".runops-submit.lock"
    claim.write_text("accepted:old-job-id\n", encoding="utf-8")
    manifest_before = (failed / "manifest.toml").read_bytes()
    claim_before = claim.read_bytes()

    result = retry_run(failed)

    assert result.status is ActionStatus.PRECONDITION_FAILED
    assert "expired at" in result.message
    assert (failed / "manifest.toml").read_bytes() == manifest_before
    assert claim.read_bytes() == claim_before
    assert not (failed / "status" / "state.json").exists()
    assert not (tmp_path / ".runops" / "experiment-usage.toml").exists()


def test_ownerless_retry_fails_closed_on_incomplete_run_namespace(
    tmp_path: Path,
) -> None:
    (tmp_path / "runops.toml").write_text(
        "[project]\n"
        'name = "budget-test"\n\n'
        "[experiments.policy]\n"
        "require_experiment = false\n"
        "max_unreviewed_completed_runs = 10\n",
        encoding="utf-8",
    )
    (tmp_path / "runs").mkdir()
    failed = _run(
        tmp_path,
        "R20260901-0001",
        status="failed",
        experiment_id="",
    )
    outside = tmp_path / "outside-runs"
    outside.mkdir()
    (tmp_path / "runs" / "hidden").symlink_to(outside, target_is_directory=True)

    result = retry_run(failed)

    assert result.status is ActionStatus.PRECONDITION_FAILED
    assert "symbolic link" in result.message
    assert read_manifest(failed).run["status"] == "failed"


def test_ownerless_retry_rejects_non_positive_walltime(tmp_path: Path) -> None:
    (tmp_path / "runops.toml").write_text(
        "[project]\n"
        'name = "budget-test"\n\n'
        "[experiments.policy]\n"
        "require_experiment = false\n"
        "max_unreviewed_completed_runs = 10\n",
        encoding="utf-8",
    )
    (tmp_path / "runs").mkdir()
    failed = _run(
        tmp_path,
        "R20260901-0001",
        status="failed",
        experiment_id="",
    )
    manifest = read_manifest(failed)
    manifest.job["walltime"] = "00:00:00"
    with (failed / "manifest.toml").open("wb") as stream:
        tomli_w.dump(manifest.to_dict(), stream)

    result = retry_run(failed)

    assert result.status is ActionStatus.PRECONDITION_FAILED
    assert "invalid job.walltime" in result.message
    assert read_manifest(failed).run["status"] == "failed"


@pytest.mark.parametrize(
    "walltime",
    [
        "",
        "-01:00:00",
        "00:00:00",
        "01:60:00",
        "01:00:60",
        "1:00",
    ],
)
def test_declared_core_hours_reject_invalid_or_non_positive_walltime(
    tmp_path: Path,
    walltime: str,
) -> None:
    with pytest.raises(SimctlError, match=r"invalid job\.walltime"):
        declared_job_core_hours(JobData(walltime=walltime))

    manifest = read_manifest(
        _run(
            tmp_path,
            "R20260901-0999",
            status="created",
            experiment_id="",
        )
    )
    manifest.job["walltime"] = walltime
    with pytest.raises(SimctlError, match=r"invalid job\.walltime"):
        declared_manifest_core_hours(manifest)


def test_injected_owner_records_cannot_bypass_incomplete_run_namespace(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside-runs"
    outside.mkdir()
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / "hidden").symlink_to(outside, target_is_directory=True)

    with pytest.raises(SimctlError, match="symbolic link"):
        enforce_experiment_run_budget(
            _project(tmp_path),
            _experiment(
                tmp_path,
                max_active=3,
                max_core_hours=10.0,
                max_materialized=3,
            ),
            new_count=1,
            new_core_hours=1.0,
            reservation_tokens=("run:R20260901-0001",),
            records=(),
            persist=False,
        )
