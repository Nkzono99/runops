"""Tests for the shared submission plan/apply use case."""

from __future__ import annotations

import os
import stat
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event, Lock
from typing import Any
from unittest.mock import patch

import pytest
import tomli_w

from runops.application.execution.submission import (
    SubmissionBlockedError,
    SubmissionClaimError,
    SubmissionLockError,
    SubmissionOutcomeUnknownError,
    SubmissionPersistenceError,
    SubmissionResult,
    SubmissionStaleError,
    SubmitPlan,
    SubmitPrecondition,
    SubmitRequest,
    apply_submit,
    plan_submit,
    reset_retry_under_submission_lock,
)
from runops.application.ports.scheduler import SchedulerRejectedError
from runops.core.manifest import read_manifest

EXPECTED_PRECONDITIONS = (
    "state_created",
    "job_id_empty",
    "submission_claim_empty",
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


def test_plan_submit_resolves_relative_run_dir_to_absolute_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "relative-run"
    _create_ready_run(run_dir)
    monkeypatch.chdir(tmp_path)

    plan = plan_submit(SubmitRequest(run_dir=Path("relative-run")))

    resolved_run_dir = run_dir.resolve()
    assert plan.run_dir == resolved_run_dir
    assert plan.run_dir.is_absolute()
    assert plan.job_script == resolved_run_dir / "submit" / "job.sh"
    assert plan.work_dir == resolved_run_dir / "work"
    assert plan.command == (
        "sbatch",
        f"--chdir={resolved_run_dir / 'work'}",
        str(resolved_run_dir / "submit" / "job.sh"),
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


def test_plan_submit_blocks_nonempty_accepted_job_id(tmp_path: Path) -> None:
    run_dir = tmp_path / "R20260710-0001"
    _create_ready_run(run_dir, job={"job_id": "12345"})

    plan = plan_submit(SubmitRequest(run_dir=run_dir))

    check = _checks(plan)["job_id_empty"]
    assert plan.job_id_before == "12345"
    assert check.passed is False
    assert "12345" in check.message
    assert plan.ready is False


def test_plan_submit_blocks_nonempty_submission_claim(tmp_path: Path) -> None:
    run_dir = tmp_path / "R20260710-0001"
    _create_ready_run(run_dir)
    (run_dir / ".runops-submit.lock").write_text("accepted:12345\n", encoding="utf-8")

    plan = plan_submit(SubmitRequest(run_dir=run_dir))

    check = _checks(plan)["submission_claim_empty"]
    assert plan.claim_before == "accepted:12345"
    assert check.passed is False
    assert "accepted:12345" in check.message


def test_plan_submit_blocks_unreadable_submission_claim(tmp_path: Path) -> None:
    run_dir = tmp_path / "R20260710-0001"
    _create_ready_run(run_dir)
    (run_dir / ".runops-submit.lock").symlink_to(run_dir / "manifest.toml")

    plan = plan_submit(SubmitRequest(run_dir=run_dir))

    check = _checks(plan)["submission_claim_empty"]
    assert check.passed is False
    assert "unreadable" in plan.claim_before
    assert "unreadable" in check.message


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


def test_plan_submit_reports_non_utf8_script_as_unreadable(tmp_path: Path) -> None:
    run_dir = tmp_path / "R20260710-0001"
    _create_ready_run(run_dir)
    (run_dir / "submit" / "job.sh").write_bytes(b"\xff\xfe\x00")

    plan = plan_submit(SubmitRequest(run_dir=run_dir))

    checks = _checks(plan)
    assert tuple(checks) == EXPECTED_PRECONDITIONS
    assert checks["job_script_exists"].passed is True
    assert checks["job_script_readable"].passed is False
    assert "decode" in checks["job_script_readable"].message.lower()
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


def test_apply_submit_unknown_external_failure_keeps_pending_claim(
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

    with pytest.raises(
        SubmissionOutcomeUnknownError,
        match="scheduler unavailable",
    ) as error_info:
        apply_submit(plan, submitter)

    assert error_info.value.run_id == plan.run_id
    assert error_info.value.attempt == 1
    assert error_info.value.cause_type == "RuntimeError"
    assert error_info.value.__cause__ is error_info.value.cause
    assert calls == [plan.command]
    assert (run_dir / "manifest.toml").read_bytes() == before
    assert not (run_dir / "status").exists()
    assert (run_dir / ".runops-submit.lock").read_text(encoding="utf-8") == (
        "pending\n"
    )
    recovery_plan = plan_submit(SubmitRequest(run_dir=run_dir))
    assert _checks(recovery_plan)["submission_claim_empty"].passed is False


def test_apply_submit_definitive_scheduler_rejection_clears_pending_claim(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "R20260710-0001"
    _create_ready_run(run_dir)
    plan = plan_submit(SubmitRequest(run_dir=run_dir))
    before = (run_dir / "manifest.toml").read_bytes()

    def submitter(command: tuple[str, ...]) -> str:
        raise SchedulerRejectedError("scheduler rejected request")

    with pytest.raises(SchedulerRejectedError, match="scheduler rejected request"):
        apply_submit(plan, submitter)

    assert (run_dir / "manifest.toml").read_bytes() == before
    assert not (run_dir / "status").exists()
    assert (run_dir / ".runops-submit.lock").read_text(encoding="utf-8") == ""


@pytest.mark.parametrize(
    ("section_update", "message"),
    [
        ({"run": {"status": "submitted"}}, "state"),
        ({"run": {"id": "R20260710-replaced"}}, "run_id"),
        ({"job": {"job_id": "12345"}}, "job_id"),
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


@pytest.mark.parametrize("initial_work_exists", [True, False])
def test_apply_submit_rejects_changed_work_dir_selection_before_scheduler_call(
    tmp_path: Path,
    initial_work_exists: bool,
) -> None:
    run_dir = tmp_path / "R20260710-0001"
    _create_ready_run(run_dir, create_work=initial_work_exists)
    plan = plan_submit(SubmitRequest(run_dir=run_dir))

    work_dir = run_dir / "work"
    if initial_work_exists:
        work_dir.rmdir()
    else:
        work_dir.mkdir()
    scheduler_calls: list[tuple[str, ...]] = []

    with pytest.raises(SubmissionStaleError, match="work_dir"):
        apply_submit(
            plan,
            lambda command: scheduler_calls.append(command) or "12345",
        )

    assert scheduler_calls == []


def test_apply_submit_rejects_claim_created_after_planning(tmp_path: Path) -> None:
    run_dir = tmp_path / "R20260710-0001"
    _create_ready_run(run_dir)
    plan = plan_submit(SubmitRequest(run_dir=run_dir))
    (run_dir / ".runops-submit.lock").write_text("pending\n", encoding="utf-8")
    scheduler_calls: list[tuple[str, ...]] = []

    with pytest.raises(SubmissionStaleError, match=r"claim changed.*pending"):
        apply_submit(
            plan,
            lambda command: scheduler_calls.append(command) or "12345",
        )

    assert scheduler_calls == []


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
            "job_id": "",
            "submitted_at": "",
            "attempt": 1,
            "attempts": [existing_attempt],
            "queue": "old",
        },
    )
    from runops.core.manifest import update_manifest

    update_manifest(
        run_dir,
        {
            "job": {"future_scheduler_field": "preserve-job-value"},
            "extensions": {"future_tool": {"token": "preserve-top-level"}},
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
    assert updated.job["future_scheduler_field"] == "preserve-job-value"
    assert updated.extra_sections["extensions"] == {
        "future_tool": {"token": "preserve-top-level"}
    }
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


def test_apply_submit_preserves_subsecond_attempt_boundary(tmp_path: Path) -> None:
    run_dir = tmp_path / "R20260710-0001"
    _create_ready_run(run_dir)
    plan = plan_submit(SubmitRequest(run_dir=run_dir))
    fixed = datetime(
        2026,
        7,
        10,
        3,
        4,
        5,
        900_000,
        tzinfo=timezone.utc,
    )

    result = apply_submit(plan, lambda command: "12345", now=lambda: fixed)

    assert result.submitted_at == "2026-07-10T03:04:05.900000+00:00"
    assert read_manifest(run_dir).job["submitted_at"] == result.submitted_at


def test_apply_submit_rechecks_freshness_after_clock_side_effect(
    tmp_path: Path,
) -> None:
    from runops.core.manifest import update_manifest

    run_dir = tmp_path / "R20260710-0001"
    _create_ready_run(run_dir)
    plan = plan_submit(SubmitRequest(run_dir=run_dir))
    scheduler_calls: list[tuple[str, ...]] = []

    def clock() -> datetime:
        update_manifest(run_dir, {"run": {"status": "submitted"}})
        return datetime(2026, 7, 10, 3, 4, 5, tzinfo=timezone.utc)

    def submitter(command: tuple[str, ...]) -> str:
        scheduler_calls.append(command)
        return "12345"

    with pytest.raises(SubmissionStaleError, match="state changed"):
        apply_submit(plan, submitter, now=clock)

    assert scheduler_calls == []
    updated = read_manifest(run_dir)
    assert updated.run["status"] == "submitted"
    assert updated.job.get("job_id", "") == ""
    assert not (run_dir / "status").exists()


def test_concurrent_apply_submit_calls_scheduler_once_per_run(tmp_path: Path) -> None:
    run_dir = tmp_path / "R20260710-0001"
    _create_ready_run(run_dir)
    plan = plan_submit(SubmitRequest(run_dir=run_dir))
    first_scheduler_call = Event()
    second_scheduler_call = Event()
    second_apply_started = Event()
    release_scheduler = Event()
    scheduler_call_lock = Lock()
    scheduler_calls: list[tuple[str, ...]] = []

    def submitter(command: tuple[str, ...]) -> str:
        with scheduler_call_lock:
            scheduler_calls.append(command)
            first_scheduler_call.set()
            if len(scheduler_calls) == 2:
                second_scheduler_call.set()
        assert release_scheduler.wait(timeout=5)
        return "12345"

    def second_apply() -> SubmissionResult:
        second_apply_started.set()
        return apply_submit(plan, submitter)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(apply_submit, plan, submitter)
        assert first_scheduler_call.wait(timeout=5)
        second = executor.submit(second_apply)
        assert second_apply_started.wait(timeout=5)
        assert not second_scheduler_call.wait(timeout=0.5)
        release_scheduler.set()

        assert first.result(timeout=5).job_id == "12345"
        with pytest.raises(SubmissionStaleError):
            second.result(timeout=5)

    assert scheduler_calls == [plan.command]
    assert (run_dir / ".runops-submit.lock").is_file()
    assert (run_dir / ".runops-submit.lock").read_text(encoding="utf-8") == ""


def test_concurrent_waiter_is_blocked_after_manifest_persistence_failure(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "R20260710-0001"
    _create_ready_run(run_dir)
    plan = plan_submit(SubmitRequest(run_dir=run_dir))
    first_scheduler_call = Event()
    second_apply_started = Event()
    release_scheduler = Event()
    scheduler_calls: list[tuple[str, ...]] = []

    def submitter(command: tuple[str, ...]) -> str:
        scheduler_calls.append(command)
        first_scheduler_call.set()
        assert release_scheduler.wait(timeout=5)
        return "98765"

    def second_apply() -> SubmissionResult:
        second_apply_started.set()
        return apply_submit(plan, submitter)

    with (
        patch(
            "runops.application.execution.submission.update_manifest",
            side_effect=OSError("manifest disk full"),
        ),
        ThreadPoolExecutor(max_workers=2) as executor,
    ):
        first = executor.submit(apply_submit, plan, submitter)
        assert first_scheduler_call.wait(timeout=5)
        second = executor.submit(second_apply)
        assert second_apply_started.wait(timeout=5)
        release_scheduler.set()

        with pytest.raises(SubmissionPersistenceError):
            first.result(timeout=5)
        with pytest.raises(SubmissionStaleError, match="accepted:98765"):
            second.result(timeout=5)

    assert scheduler_calls == [plan.command]
    assert (run_dir / ".runops-submit.lock").read_text(encoding="utf-8") == (
        "accepted:98765\n"
    )


def test_apply_submit_lock_failure_is_typed_and_calls_no_scheduler(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "R20260710-0001"
    _create_ready_run(run_dir)
    plan = plan_submit(SubmitRequest(run_dir=run_dir))
    scheduler_calls: list[tuple[str, ...]] = []

    with (
        patch(
            "runops.application.execution.submission.fcntl.flock",
            side_effect=OSError("locking unsupported"),
        ),
        pytest.raises(SubmissionLockError, match="locking unsupported"),
    ):
        apply_submit(
            plan,
            lambda command: scheduler_calls.append(command) or "12345",
        )

    assert scheduler_calls == []


def test_apply_submit_rejects_hardlinked_lock_without_mutating_target(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "R20260710-0001"
    _create_ready_run(run_dir)
    plan = plan_submit(SubmitRequest(run_dir=run_dir))
    target = tmp_path / "unrelated.txt"
    target.write_text("", encoding="utf-8")
    os.link(target, run_dir / ".runops-submit.lock")
    scheduler_calls: list[tuple[str, ...]] = []

    with pytest.raises(SubmissionLockError, match="regular single-link file"):
        apply_submit(
            plan,
            lambda command: scheduler_calls.append(command) or "12345",
        )

    assert scheduler_calls == []
    assert target.read_text(encoding="utf-8") == ""


def test_plan_submit_rejects_fifo_claim_without_blocking(tmp_path: Path) -> None:
    run_dir = tmp_path / "R20260710-0001"
    _create_ready_run(run_dir)
    os.mkfifo(run_dir / ".runops-submit.lock")

    plan = plan_submit(SubmitRequest(run_dir=run_dir))

    claim_check = _checks(plan)["submission_claim_empty"]
    assert claim_check.passed is False
    assert "unreadable" in plan.claim_before
    assert "regular single-link file" in plan.claim_before


def test_apply_submit_new_lock_directory_fsync_failure_calls_no_scheduler(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "R20260710-0001"
    _create_ready_run(run_dir)
    plan = plan_submit(SubmitRequest(run_dir=run_dir))
    scheduler_calls: list[tuple[str, ...]] = []

    with (
        patch(
            "runops.application.execution.submission._fsync_directory",
            side_effect=OSError("directory fsync failed"),
        ),
        pytest.raises(SubmissionLockError, match="directory fsync failed"),
    ):
        apply_submit(
            plan,
            lambda command: scheduler_calls.append(command) or "12345",
        )

    assert scheduler_calls == []


def test_apply_submit_pending_claim_failure_is_typed_and_calls_no_scheduler(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "R20260710-0001"
    _create_ready_run(run_dir)
    (run_dir / ".runops-submit.lock").write_text("", encoding="utf-8")
    plan = plan_submit(SubmitRequest(run_dir=run_dir))
    scheduler_calls: list[tuple[str, ...]] = []
    real_fsync = os.fsync

    def fail_claim_fsync(descriptor: int) -> None:
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            real_fsync(descriptor)
            return
        raise OSError("claim fsync failed")

    with (
        patch(
            "runops.application.execution.submission.os.fsync",
            side_effect=fail_claim_fsync,
        ),
        pytest.raises(SubmissionClaimError, match="claim fsync failed"),
    ):
        apply_submit(
            plan,
            lambda command: scheduler_calls.append(command) or "12345",
        )

    assert scheduler_calls == []
    assert (run_dir / ".runops-submit.lock").read_text(encoding="utf-8") != ""


def test_apply_submit_accepted_claim_failure_preserves_accepted_job(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "R20260710-0001"
    _create_ready_run(run_dir)
    (run_dir / ".runops-submit.lock").write_text("", encoding="utf-8")
    plan = plan_submit(SubmitRequest(run_dir=run_dir))
    scheduler_calls: list[tuple[str, ...]] = []
    real_fsync = os.fsync
    claim_fsync_calls = 0

    def fail_accepted_claim_fsync(descriptor: int) -> None:
        nonlocal claim_fsync_calls
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            real_fsync(descriptor)
            return
        claim_fsync_calls += 1
        if claim_fsync_calls == 2:
            raise OSError("accepted claim fsync failed")
        real_fsync(descriptor)

    def submitter(command: tuple[str, ...]) -> str:
        scheduler_calls.append(command)
        return "98765"

    with (
        patch(
            "runops.application.execution.submission.os.fsync",
            side_effect=fail_accepted_claim_fsync,
        ),
        pytest.raises(SubmissionPersistenceError) as error_info,
    ):
        apply_submit(plan, submitter)

    assert error_info.value.job_id == "98765"
    assert error_info.value.phase == "claim"
    assert scheduler_calls == [plan.command]
    assert (run_dir / ".runops-submit.lock").read_text(encoding="utf-8") == (
        "accepted:98765\n"
    )


def test_retry_interruption_after_claim_clear_keeps_terminal_manifest_guard(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "R20260710-0001"
    _create_ready_run(
        run_dir,
        status="cancelled",
        job={"job_id": "12345"},
    )
    (run_dir / ".runops-submit.lock").write_text(
        "accepted:12345\n",
        encoding="utf-8",
    )

    def interrupted_reset() -> None:
        assert (run_dir / ".runops-submit.lock").read_text(encoding="utf-8") == ""
        raise RuntimeError("interrupted before reset")

    with pytest.raises(RuntimeError, match="interrupted before reset"):
        reset_retry_under_submission_lock(run_dir, interrupted_reset)

    unchanged = read_manifest(run_dir)
    assert unchanged.run["status"] == "cancelled"
    assert unchanged.job["job_id"] == "12345"
    recovery_plan = plan_submit(SubmitRequest(run_dir=run_dir))
    assert _checks(recovery_plan)["state_created"].passed is False
    assert _checks(recovery_plan)["job_id_empty"].passed is False


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


@pytest.mark.parametrize(
    ("phase", "target", "failure"),
    [
        (
            "manifest",
            "runops.application.execution.submission.update_manifest",
            OSError("manifest disk full"),
        ),
        (
            "state",
            "runops.application.execution.submission.update_state",
            OSError("state disk full"),
        ),
    ],
)
def test_apply_submit_preserves_scheduler_acceptance_on_persistence_failure(
    tmp_path: Path,
    phase: str,
    target: str,
    failure: OSError,
) -> None:
    run_dir = tmp_path / "R20260710-0001"
    _create_ready_run(run_dir)
    plan = plan_submit(SubmitRequest(run_dir=run_dir))
    fixed = datetime(2026, 7, 10, 3, 4, 5, tzinfo=timezone.utc)
    scheduler_calls: list[tuple[str, ...]] = []

    def submitter(command: tuple[str, ...]) -> str:
        scheduler_calls.append(command)
        return "98765"

    with (
        patch(target, side_effect=failure),
        pytest.raises(SubmissionPersistenceError) as error_info,
    ):
        apply_submit(plan, submitter, now=lambda: fixed)

    error = error_info.value
    assert error.job_id == "98765"
    assert error.attempt == 1
    assert error.submitted_at == "2026-07-10T03:04:05+00:00"
    assert error.phase == phase
    assert error.cause is failure
    assert error.__cause__ is failure
    assert "98765" in str(error)
    assert scheduler_calls == [plan.command]

    updated = read_manifest(run_dir)
    if phase == "manifest":
        assert updated.job.get("job_id", "") == ""
    else:
        assert updated.job["job_id"] == "98765"
        assert updated.job["attempt"] == 1
        recovery_plan = plan_submit(SubmitRequest(run_dir=run_dir))
        assert _checks(recovery_plan)["job_id_empty"].passed is False
        with pytest.raises(SubmissionBlockedError, match="job_id_empty"):
            apply_submit(recovery_plan, submitter)
        assert scheduler_calls == [plan.command]
    assert not (run_dir / "status").exists()
