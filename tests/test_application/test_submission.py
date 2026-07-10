"""Tests for the shared submission plan/apply use case."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import tomli_w

from runops.application.execution.submission import (
    SubmissionBlockedError,
    SubmissionResult,
    SubmissionStaleError,
    SubmitPlan,
    SubmitPrecondition,
    SubmitRequest,
    apply_submit,
    plan_submit,
)
from runops.core.manifest import read_manifest

EXPECTED_PRECONDITIONS = (
    "state_created",
    "job_script_exists",
    "job_script_readable",
    "job_script_has_sbatch",
    "input_ready",
)


def _write_manifest(run_dir: Path, data: dict[str, Any]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    with open(run_dir / "manifest.toml", "wb") as stream:
        tomli_w.dump(data, stream)


def _create_ready_run(
    run_dir: Path,
    *,
    status: str = "created",
    job: dict[str, Any] | None = None,
    production_dirty: bool = False,
    create_work: bool = True,
) -> None:
    manifest: dict[str, Any] = {
        "run": {
            "id": "R20260710-0001",
            "status": status,
            "last_slurm_state": "COMPLETED",
        },
        "job": job or {},
    }
    if production_dirty:
        manifest["classification"] = {"tags": ["production"]}
        manifest["simulator_source"] = {"git_dirty": True}
    _write_manifest(run_dir, manifest)

    submit_dir = run_dir / "submit"
    submit_dir.mkdir(parents=True, exist_ok=True)
    (submit_dir / "job.sh").write_text(
        "#!/bin/bash\n#SBATCH --job-name=test\necho hello\n",
        encoding="utf-8",
    )
    input_dir = run_dir / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    (input_dir / "params.toml").write_text("nx = 16\n", encoding="utf-8")
    if create_work:
        (run_dir / "work").mkdir(parents=True, exist_ok=True)


def _checks(plan: SubmitPlan) -> dict[str, SubmitPrecondition]:
    return {check.name: check for check in plan.preconditions}


def test_plan_submit_builds_ready_exact_command_in_stable_order(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "R20260710-0001"
    _create_ready_run(run_dir)

    plan = plan_submit(
        SubmitRequest(
            run_dir=run_dir,
            queue_name="debug",
            qos="normal",
            afterok="123",
        )
    )

    assert plan.run_id == "R20260710-0001"
    assert plan.run_dir == run_dir
    assert plan.job_script == run_dir / "submit" / "job.sh"
    assert plan.work_dir == run_dir / "work"
    assert plan.queue_name == "debug"
    assert plan.qos == "normal"
    assert plan.afterok == "123"
    assert tuple(check.name for check in plan.preconditions) == EXPECTED_PRECONDITIONS
    assert all(check.passed and check.message for check in plan.preconditions)
    assert plan.failed_preconditions == ()
    assert plan.ready is True
    assert plan.command == (
        "sbatch",
        f"--chdir={run_dir / 'work'}",
        "--dependency=afterok:123",
        "--partition=debug",
        "--qos=normal",
        str(run_dir / "submit" / "job.sh"),
    )


def test_plan_submit_falls_back_to_run_dir_when_work_is_absent(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "R20260710-0001"
    _create_ready_run(run_dir, create_work=False)

    plan = plan_submit(SubmitRequest(run_dir=run_dir))

    assert plan.work_dir == run_dir
    assert plan.command == (
        "sbatch",
        f"--chdir={run_dir}",
        str(run_dir / "submit" / "job.sh"),
    )


def test_plan_submit_reports_non_created_state_without_omitting_checks(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "R20260710-0001"
    _create_ready_run(run_dir, status="running")

    plan = plan_submit(SubmitRequest(run_dir=run_dir))

    assert tuple(check.name for check in plan.preconditions) == EXPECTED_PRECONDITIONS
    assert _checks(plan)["state_created"].passed is False
    assert tuple(check.name for check in plan.failed_preconditions) == (
        "state_created",
    )
    assert plan.ready is False


def test_plan_submit_reports_all_script_checks_when_script_is_missing(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "R20260710-0001"
    _create_ready_run(run_dir)
    (run_dir / "submit" / "job.sh").unlink()

    plan = plan_submit(SubmitRequest(run_dir=run_dir))

    checks = _checks(plan)
    assert tuple(checks) == EXPECTED_PRECONDITIONS
    assert checks["job_script_exists"].passed is False
    assert checks["job_script_readable"].passed is False
    assert checks["job_script_has_sbatch"].passed is False
    assert all(check.message for check in plan.preconditions)


def test_plan_submit_reports_unreadable_script_and_missing_directive(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "R20260710-0001"
    _create_ready_run(run_dir)
    job_script = run_dir / "submit" / "job.sh"
    original_read_text = Path.read_text

    def fail_job_read(path: Path, *args: object, **kwargs: object) -> str:
        if path == job_script:
            raise PermissionError("permission denied")
        return original_read_text(path, *args, **kwargs)

    with patch.object(Path, "read_text", fail_job_read):
        plan = plan_submit(SubmitRequest(run_dir=run_dir))

    checks = _checks(plan)
    assert checks["job_script_exists"].passed is True
    assert checks["job_script_readable"].passed is False
    assert "permission denied" in checks["job_script_readable"].message
    assert checks["job_script_has_sbatch"].passed is False


def test_plan_submit_reports_script_without_sbatch(tmp_path: Path) -> None:
    run_dir = tmp_path / "R20260710-0001"
    _create_ready_run(run_dir)
    (run_dir / "submit" / "job.sh").write_text(
        "#!/bin/bash\necho hello\n",
        encoding="utf-8",
    )

    plan = plan_submit(SubmitRequest(run_dir=run_dir))

    checks = _checks(plan)
    assert checks["job_script_readable"].passed is True
    assert checks["job_script_has_sbatch"].passed is False


def test_plan_submit_reports_empty_and_unreadable_input(tmp_path: Path) -> None:
    run_dir = tmp_path / "R20260710-0001"
    _create_ready_run(run_dir)
    (run_dir / "input" / "params.toml").unlink()

    empty_plan = plan_submit(SubmitRequest(run_dir=run_dir))

    assert _checks(empty_plan)["input_ready"].passed is False

    input_dir = run_dir / "input"
    original_iterdir = Path.iterdir

    def fail_input_list(path: Path):  # type: ignore[no-untyped-def]
        if path == input_dir:
            raise PermissionError("cannot list input")
        return original_iterdir(path)

    with patch.object(Path, "iterdir", fail_input_list):
        unreadable_plan = plan_submit(SubmitRequest(run_dir=run_dir))

    input_check = _checks(unreadable_plan)["input_ready"]
    assert input_check.passed is False
    assert "cannot list input" in input_check.message


def test_plan_submit_is_read_only_and_public_types_are_frozen(tmp_path: Path) -> None:
    run_dir = tmp_path / "R20260710-0001"
    _create_ready_run(run_dir)
    manifest_path = run_dir / "manifest.toml"
    before = manifest_path.read_bytes()

    plan = plan_submit(SubmitRequest(run_dir=run_dir))

    assert manifest_path.read_bytes() == before
    assert not (run_dir / "status").exists()
    with pytest.raises(FrozenInstanceError):
        plan.run_id = "changed"  # type: ignore[misc]
    assert SubmitRequest.__dataclass_params__.frozen is True
    assert SubmitPrecondition.__dataclass_params__.frozen is True
    assert SubmitPlan.__dataclass_params__.frozen is True
    assert SubmissionResult.__dataclass_params__.frozen is True


def test_apply_submit_rejects_blocked_plan_without_call_or_mutation(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "R20260710-0001"
    _create_ready_run(run_dir, status="running")
    plan = plan_submit(SubmitRequest(run_dir=run_dir))
    before = (run_dir / "manifest.toml").read_bytes()
    calls: list[tuple[str, ...]] = []

    def submitter(command: tuple[str, ...]) -> str:
        calls.append(command)
        return "12345"

    with pytest.raises(SubmissionBlockedError, match="state_created"):
        apply_submit(plan, submitter)

    assert calls == []
    assert (run_dir / "manifest.toml").read_bytes() == before
    assert not (run_dir / "status").exists()


def test_apply_submit_external_failure_leaves_manifest_and_state_unchanged(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "R20260710-0001"
    _create_ready_run(run_dir)
    plan = plan_submit(SubmitRequest(run_dir=run_dir))
    before = (run_dir / "manifest.toml").read_bytes()
    calls: list[tuple[str, ...]] = []

    def submitter(command: tuple[str, ...]) -> str:
        calls.append(command)
        raise RuntimeError("scheduler unavailable")

    with pytest.raises(RuntimeError, match="scheduler unavailable"):
        apply_submit(plan, submitter)

    assert calls == [plan.command]
    assert (run_dir / "manifest.toml").read_bytes() == before
    assert not (run_dir / "status").exists()


@pytest.mark.parametrize(
    ("section_update", "message"),
    [
        ({"run": {"status": "submitted"}}, "state"),
        ({"run": {"id": "R20260710-replaced"}}, "run_id"),
    ],
)
def test_apply_submit_rejects_stale_plan_before_scheduler_call(
    tmp_path: Path,
    section_update: dict[str, Any],
    message: str,
) -> None:
    from runops.core.manifest import update_manifest

    run_dir = tmp_path / "R20260710-0001"
    _create_ready_run(run_dir)
    plan = plan_submit(SubmitRequest(run_dir=run_dir))
    update_manifest(run_dir, section_update)
    before = (run_dir / "manifest.toml").read_bytes()
    calls: list[tuple[str, ...]] = []

    def submitter(command: tuple[str, ...]) -> str:
        calls.append(command)
        return "12345"

    with pytest.raises(SubmissionStaleError, match=message):
        apply_submit(plan, submitter)

    assert calls == []
    assert (run_dir / "manifest.toml").read_bytes() == before
    assert not (run_dir / "status").exists()


def test_apply_submit_fixed_clock_preserves_history_options_and_types(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "R20260710-0001"
    existing_attempt = {
        "job_id": "100",
        "submitted_at": "2026-07-09T00:00:00+00:00",
        "attempt": "1",
        "partition": "old",
    }
    _create_ready_run(
        run_dir,
        job={
            "job_id": "100",
            "submitted_at": "2026-07-09T00:00:00+00:00",
            "attempt": 1,
            "attempts": [existing_attempt],
            "queue": "old",
        },
    )
    plan = plan_submit(
        SubmitRequest(
            run_dir=run_dir,
            queue_name="compute",
            qos="debugqos",
            afterok="67890",
        )
    )
    fixed = datetime(2026, 7, 10, 3, 4, 5, tzinfo=timezone.utc)
    calls: list[tuple[str, ...]] = []

    def submitter(command: tuple[str, ...]) -> str:
        calls.append(command)
        return "12345"

    result = apply_submit(plan, submitter, now=lambda: fixed)

    assert calls == [plan.command]
    assert result == SubmissionResult(
        run_id="R20260710-0001",
        job_id="12345",
        submitted_at="2026-07-10T03:04:05+00:00",
        attempt=2,
        command=plan.command,
        warnings=(),
        state_before="created",
        state_after="submitted",
    )
    updated = read_manifest(run_dir)
    assert updated.run["status"] == "submitted"
    assert updated.run["last_slurm_state"] == ""
    assert updated.job["job_id"] == "12345"
    assert updated.job["submitted_at"] == "2026-07-10T03:04:05+00:00"
    assert updated.job["attempt"] == 2
    assert isinstance(updated.job["attempt"], int)
    assert updated.job["queue"] == "compute"
    assert updated.job["partition"] == "compute"
    assert updated.job["qos"] == "debugqos"
    assert updated.job["afterok"] == "67890"
    assert updated.job["attempts"][0] == existing_attempt
    new_attempt = updated.job["attempts"][1]
    assert new_attempt == {
        "job_id": "12345",
        "submitted_at": "2026-07-10T03:04:05+00:00",
        "attempt": "2",
        "partition": "compute",
        "queue": "compute",
        "qos": "debugqos",
        "afterok": "67890",
    }
    assert all(isinstance(value, str) for value in new_attempt.values())
    assert (run_dir / "status" / "state.json").exists()


def test_submission_warning_is_preserved_from_plan_to_result(tmp_path: Path) -> None:
    run_dir = tmp_path / "R20260710-0001"
    _create_ready_run(run_dir, production_dirty=True)
    plan = plan_submit(SubmitRequest(run_dir=run_dir))

    assert plan.warnings == ("production run submitted with dirty git working tree",)

    result = apply_submit(plan, lambda command: "12345")

    assert result.warnings == plan.warnings


def test_apply_submit_calls_clock_once_and_normalizes_to_utc(tmp_path: Path) -> None:
    run_dir = tmp_path / "R20260710-0001"
    _create_ready_run(run_dir)
    plan = plan_submit(SubmitRequest(run_dir=run_dir))
    calls = 0

    def clock() -> datetime:
        nonlocal calls
        calls += 1
        return datetime(
            2026,
            7,
            10,
            12,
            4,
            5,
            tzinfo=timezone(timedelta(hours=9)),
        )

    result = apply_submit(plan, lambda command: "12345", now=clock)

    assert calls == 1
    assert result.submitted_at == "2026-07-10T03:04:05+00:00"


@pytest.mark.parametrize("clock_failure", ["naive", "raises"])
def test_apply_submit_rejects_invalid_clock_before_scheduler_or_mutation(
    tmp_path: Path,
    clock_failure: str,
) -> None:
    run_dir = tmp_path / "R20260710-0001"
    _create_ready_run(run_dir)
    plan = plan_submit(SubmitRequest(run_dir=run_dir))
    before = (run_dir / "manifest.toml").read_bytes()
    clock_calls = 0
    scheduler_calls: list[tuple[str, ...]] = []

    def clock() -> datetime:
        nonlocal clock_calls
        clock_calls += 1
        if clock_failure == "raises":
            raise RuntimeError("clock unavailable")
        return datetime(2026, 7, 10, 3, 4, 5)

    def submitter(command: tuple[str, ...]) -> str:
        scheduler_calls.append(command)
        return "12345"

    expected_error = RuntimeError if clock_failure == "raises" else ValueError
    with pytest.raises(expected_error):
        apply_submit(plan, submitter, now=clock)

    assert clock_calls == 1
    assert scheduler_calls == []
    assert (run_dir / "manifest.toml").read_bytes() == before
    assert not (run_dir / "status").exists()


def test_apply_submit_keeps_existing_unspecified_scheduler_options(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "R20260710-0001"
    _create_ready_run(
        run_dir,
        job={
            "queue": "existing-queue",
            "partition": "existing-partition",
            "qos": "existing-qos",
            "afterok": "existing-dependency",
        },
    )
    plan = plan_submit(SubmitRequest(run_dir=run_dir))

    apply_submit(plan, lambda command: "12345")

    updated = read_manifest(run_dir)
    assert updated.job["queue"] == "existing-queue"
    assert updated.job["partition"] == "existing-partition"
    assert updated.job["qos"] == "existing-qos"
    assert updated.job["afterok"] == "existing-dependency"
