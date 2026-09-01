"""Application tests for the isolated TestAttempt lifecycle."""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from runops.application import test_attempts as test_attempts_module
from runops.application.test_attempts import (
    TestAttemptWorkflowError as AttemptWorkflowError,
)
from runops.application.test_attempts import (
    clean_test_attempts,
    hash_case_input,
    list_test_attempts,
    prepare_test_attempt,
    record_test_result,
)

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


def _project(root: Path) -> Path:
    (root / "runops.toml").write_text('[project]\nname = "demo"\n', encoding="utf-8")
    case_dir = root / "cases" / "generic" / "base"
    (case_dir / "input" / "nested").mkdir(parents=True)
    (case_dir / "case.toml").write_text(
        '[case]\nname = "base"\nsimulator = "generic"\nlauncher = "srun"\n',
        encoding="utf-8",
    )
    (case_dir / "input" / "a.txt").write_bytes(b"alpha\n")
    (case_dir / "input" / "nested" / "b.bin").write_bytes(b"\x00beta")
    (root / "runs").mkdir()
    return root


def test_prepare_uses_separate_t_identity_and_canonical_input_snapshot(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)

    prepared = prepare_test_attempt(
        project,
        "generic/base",
        kind="smoke",
        profile="quick",
        source_commit="abc123",
        executable_hash="sha256:" + "1" * 64,
        adapter="generic",
        adapter_version="1.2.3",
        now=NOW,
    )

    assert prepared.attempt.id == "T20260901-0001"
    assert prepared.attempt.state == "prepared"
    assert prepared.cached is False
    assert prepared.attempt.input_hash.startswith("sha256:")
    assert prepared.attempt.input_hash != hash_case_input(
        project / "cases/generic/base"
    )
    assert (prepared.path / "test-receipt.toml").is_file()
    assert (prepared.path / "input/a.txt").read_bytes() == b"alpha\n"
    assert (prepared.path / "input/params.json").read_text(encoding="utf-8") == "{}"
    assert not list((project / "runs").rglob("manifest.toml"))
    assert not (project / ".runops" / "run-id-sequence.toml").exists()


@pytest.mark.parametrize("unsafe_entry", [".runops", ".runops/cache"])
def test_prepare_rejects_symlinked_state_or_cache_without_external_writes(
    tmp_path: Path,
    unsafe_entry: str,
) -> None:
    project = _project(tmp_path)
    outside = tmp_path / "outside-state"
    outside.mkdir()
    link = project / unsafe_entry
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(outside, target_is_directory=True)

    with pytest.raises(AttemptWorkflowError, match="symbolic link"):
        prepare_test_attempt(
            project,
            "generic/base",
            kind="smoke",
            source_commit="abc123",
            executable_hash="sha256:" + "1" * 64,
            adapter_version="1.2.3",
            now=NOW,
        )

    assert list(outside.iterdir()) == []
    assert not list((project / "runs").rglob("manifest.toml"))


def test_passed_cache_skips_within_ttl_and_rerun_creates_prepared_attempt(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    identity = {
        "source_commit": "abc123",
        "executable_hash": "sha256:" + "1" * 64,
        "adapter_version": "1.2.3",
    }
    first = prepare_test_attempt(
        project,
        "generic/base",
        kind="smoke",
        now=NOW,
        **identity,
    )
    record_test_result(
        project,
        first.attempt.id,
        result="passed",
        observation="solver started",
        now=NOW + timedelta(minutes=1),
    )

    cached = prepare_test_attempt(
        project,
        "generic/base",
        kind="smoke",
        cache_ttl=timedelta(hours=1),
        now=NOW + timedelta(minutes=2),
        **identity,
    )
    rerun = prepare_test_attempt(
        project,
        "generic/base",
        kind="smoke",
        cache_ttl=timedelta(hours=1),
        rerun=True,
        now=NOW + timedelta(minutes=3),
        **identity,
    )

    assert cached.cached is True
    assert cached.attempt.state == "passed"
    assert cached.attempt.id == first.attempt.id
    assert cached.path == first.path
    assert cached.cache_age_seconds == 60.0
    assert rerun.cached is False
    assert rerun.attempt.state == "prepared"
    assert [item.id for item in list_test_attempts(project)] == [
        "T20260901-0001",
        "T20260901-0002",
    ]


def test_record_rejects_input_snapshot_drift_without_mutating_receipt(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    prepared = prepare_test_attempt(project, "generic/base", kind="smoke", now=NOW)
    receipt = prepared.path / "test-receipt.toml"
    before = receipt.read_bytes()
    (prepared.path / "input/a.txt").write_bytes(b"tampered\n")

    with pytest.raises(AttemptWorkflowError, match="input snapshot integrity"):
        record_test_result(
            project,
            prepared.attempt.id,
            result="passed",
            now=NOW + timedelta(minutes=1),
        )

    assert receipt.read_bytes() == before
    assert list_test_attempts(project)[0].state == "prepared"


def test_cache_reuse_rejects_drifted_passed_input_snapshot(tmp_path: Path) -> None:
    project = _project(tmp_path)
    identity = {
        "source_commit": "abc123",
        "executable_hash": "sha256:" + "1" * 64,
        "adapter_version": "1.2.3",
    }
    prepared = prepare_test_attempt(
        project,
        "generic/base",
        kind="smoke",
        now=NOW,
        **identity,
    )
    record_test_result(project, prepared.attempt.id, result="passed", now=NOW)
    (prepared.path / "input/a.txt").write_bytes(b"tampered\n")

    with pytest.raises(AttemptWorkflowError, match="input snapshot integrity"):
        prepare_test_attempt(
            project,
            "generic/base",
            kind="smoke",
            now=NOW + timedelta(minutes=1),
            **identity,
        )

    assert [item.id for item in list_test_attempts(project)] == [prepared.attempt.id]


def test_cache_key_changes_with_execution_identity(tmp_path: Path) -> None:
    project = _project(tmp_path)
    first = prepare_test_attempt(
        project,
        "generic/base",
        kind="smoke",
        source_commit="aaa",
        executable_hash="sha256:" + "1" * 64,
        adapter_version="1.2.3",
        now=NOW,
    )
    record_test_result(project, first.attempt.id, result="passed", now=NOW)

    changed = prepare_test_attempt(
        project,
        "generic/base",
        kind="smoke",
        source_commit="bbb",
        executable_hash="sha256:" + "1" * 64,
        adapter_version="1.2.3",
        now=NOW + timedelta(minutes=1),
    )

    assert changed.attempt.state == "prepared"
    assert changed.attempt.cache_key != first.attempt.cache_key


def test_tampered_cache_key_cannot_reuse_mismatched_receipt(tmp_path: Path) -> None:
    project = _project(tmp_path)
    identity = {
        "source_commit": "abc123",
        "executable_hash": "sha256:" + "1" * 64,
        "adapter_version": "1.2.3",
    }
    first = prepare_test_attempt(
        project,
        "generic/base",
        kind="smoke",
        now=NOW,
        **identity,
    )
    record_test_result(project, first.attempt.id, result="passed", now=NOW)
    case_path = project / "cases/generic/base/case.toml"
    case_path.write_text(
        case_path.read_text(encoding="utf-8") + "\n[params]\nsteps = 2\n",
        encoding="utf-8",
    )
    changed = prepare_test_attempt(
        project,
        "generic/base",
        kind="smoke",
        rerun=True,
        now=NOW + timedelta(minutes=1),
        **identity,
    )
    receipt = first.path / "test-receipt.toml"
    original = receipt.read_text(encoding="utf-8")
    receipt.write_text(
        original.replace(first.attempt.cache_key, changed.attempt.cache_key),
        encoding="utf-8",
    )

    with pytest.raises(AttemptWorkflowError, match="canonical TestAttempt identity"):
        prepare_test_attempt(
            project,
            "generic/base",
            kind="smoke",
            now=NOW + timedelta(minutes=2),
            **identity,
        )

    assert not (project / ".runops/test-runs/T20260901-0003").exists()


@pytest.mark.parametrize(
    "missing_field",
    ["source_commit", "executable_hash"],
)
def test_incomplete_identity_disables_cache_reuse(
    tmp_path: Path,
    missing_field: str,
) -> None:
    project = _project(tmp_path)
    identity = {
        "source_commit": "abc123",
        "executable_hash": "sha256:" + "1" * 64,
        "adapter_version": "1.2.3",
    }
    identity[missing_field] = ""
    first = prepare_test_attempt(
        project,
        "generic/base",
        kind="smoke",
        now=NOW,
        **identity,
    )
    record_test_result(project, first.attempt.id, result="passed", now=NOW)

    repeated = prepare_test_attempt(
        project,
        "generic/base",
        kind="smoke",
        now=NOW + timedelta(minutes=1),
        **identity,
    )

    assert repeated.cached is False
    assert repeated.attempt.state == "prepared"
    assert repeated.attempt.observation == "Identity incomplete; cache disabled."
    assert repeated.attempt.id != first.attempt.id


def test_adapter_version_defaults_to_implementation_hash(tmp_path: Path) -> None:
    project = _project(tmp_path)

    prepared = prepare_test_attempt(
        project,
        "generic/base",
        kind="smoke",
        source_commit="abc123",
        executable_hash="sha256:" + "1" * 64,
        now=NOW,
    )

    assert prepared.attempt.adapter_version.startswith("sha256:")
    assert prepared.attempt.observation == ""


def test_rendered_parameter_change_invalidates_cache(tmp_path: Path) -> None:
    project = _project(tmp_path)
    identity = {
        "source_commit": "abc123",
        "executable_hash": "sha256:" + "1" * 64,
    }
    first = prepare_test_attempt(
        project,
        "generic/base",
        kind="smoke",
        now=NOW,
        **identity,
    )
    record_test_result(project, first.attempt.id, result="passed", now=NOW)
    case_path = project / "cases/generic/base/case.toml"
    case_path.write_text(
        case_path.read_text(encoding="utf-8") + "\n[params]\nsteps = 2\n",
        encoding="utf-8",
    )

    changed = prepare_test_attempt(
        project,
        "generic/base",
        kind="smoke",
        now=NOW + timedelta(minutes=1),
        **identity,
    )

    assert changed.cached is False
    assert changed.attempt.input_hash != first.attempt.input_hash


def test_allocator_does_not_reuse_existing_id_when_ledger_is_missing(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    first = prepare_test_attempt(project, "generic/base", kind="smoke", now=NOW)
    (project / ".runops/test-id-sequence.toml").unlink()

    second = prepare_test_attempt(
        project,
        "generic/base",
        kind="debug",
        rerun=True,
        now=NOW,
    )

    assert first.attempt.id == "T20260901-0001"
    assert second.attempt.id == "T20260901-0002"


def test_record_result_is_terminal_and_preserves_created_timestamp(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    prepared = prepare_test_attempt(project, "generic/base", kind="debug", now=NOW)

    finished = record_test_result(
        project,
        prepared.attempt.id,
        result="failed",
        observation="NaN before first step",
        now=NOW + timedelta(minutes=4),
    )

    assert finished.state == "failed"
    assert finished.created_at == NOW.isoformat()
    assert finished.finished_at == (NOW + timedelta(minutes=4)).isoformat()
    assert finished.observation == "NaN before first step"
    with pytest.raises(AttemptWorkflowError, match="terminal"):
        record_test_result(project, prepared.attempt.id, result="passed", now=NOW)


def test_clean_preflights_active_attempts_before_deleting_terminal_ones(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    passed = prepare_test_attempt(project, "generic/base", kind="smoke", now=NOW)
    record_test_result(project, passed.attempt.id, result="passed", now=NOW)
    active = prepare_test_attempt(
        project,
        "generic/base",
        kind="debug",
        rerun=True,
        now=NOW,
    )

    with pytest.raises(AttemptWorkflowError, match=active.attempt.id):
        clean_test_attempts(
            project,
            older_than_days=1,
            now=NOW + timedelta(days=2),
        )

    assert passed.path.is_dir()
    assert active.path.is_dir()


def test_clean_removes_only_terminal_old_attempts(tmp_path: Path) -> None:
    project = _project(tmp_path)
    old = prepare_test_attempt(project, "generic/base", kind="smoke", now=NOW)
    record_test_result(project, old.attempt.id, result="failed", now=NOW)
    recent = prepare_test_attempt(
        project,
        "generic/base",
        kind="debug",
        now=NOW + timedelta(days=2),
    )
    record_test_result(
        project,
        recent.attempt.id,
        result="passed",
        now=NOW + timedelta(days=2),
    )

    cleaned = clean_test_attempts(
        project,
        older_than_days=1,
        now=NOW + timedelta(days=2),
    )

    assert cleaned.removed_ids == (old.attempt.id,)
    assert not old.path.exists()
    assert recent.path.is_dir()


def test_clean_rejects_symlink_anywhere_in_candidate(tmp_path: Path) -> None:
    project = _project(tmp_path)
    attempt = prepare_test_attempt(project, "generic/base", kind="smoke", now=NOW)
    record_test_result(project, attempt.attempt.id, result="passed", now=NOW)
    (attempt.path / "escape").symlink_to(tmp_path)

    with pytest.raises(AttemptWorkflowError, match="symbolic link"):
        clean_test_attempts(
            project,
            older_than_days=1,
            now=NOW + timedelta(days=2),
        )

    assert attempt.path.is_dir()


def test_clean_fails_closed_if_tombstone_is_claimed_concurrently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    attempt = prepare_test_attempt(project, "generic/base", kind="smoke", now=NOW)
    record_test_result(project, attempt.attempt.id, result="passed", now=NOW)

    def collide(_source: Path, destination: Path) -> None:
        destination.mkdir()
        raise FileExistsError(destination)

    monkeypatch.setattr(
        "runops.application.test_attempts.commit_staged_directory",
        collide,
    )

    with pytest.raises(AttemptWorkflowError, match="claimed concurrently"):
        clean_test_attempts(
            project,
            older_than_days=1,
            now=NOW + timedelta(days=2),
        )

    assert attempt.path.is_dir()
    assert (attempt.path.parent / f".delete-{attempt.attempt.id}").is_dir()


def test_prepare_does_not_replace_destination_created_during_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    real_commit = test_attempts_module.move_directory_noreplace
    collision_seen = False

    def collide(source: Path, destination: Path) -> None:
        nonlocal collision_seen
        collision_seen = True
        destination.mkdir()
        real_commit(source, destination)

    monkeypatch.setattr(test_attempts_module, "move_directory_noreplace", collide)

    with pytest.raises(AttemptWorkflowError, match="already exists"):
        prepare_test_attempt(project, "generic/base", kind="smoke", now=NOW)

    destination = project / ".runops/test-runs/T20260901-0001"
    assert collision_seen is True
    assert destination.is_dir()
    assert not (destination / "test-receipt.toml").exists()


def test_clean_rolls_back_all_staged_attempts_if_later_stage_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    attempts = [
        prepare_test_attempt(
            project,
            "generic/base",
            kind="smoke",
            rerun=True,
            now=NOW + timedelta(minutes=index),
        )
        for index in range(2)
    ]
    for attempt in attempts:
        record_test_result(
            project,
            attempt.attempt.id,
            result="passed",
            now=NOW + timedelta(minutes=2),
        )

    real_commit = test_attempts_module.commit_staged_directory
    staged_count = 0

    def fail_second_stage(source: Path, destination: Path) -> None:
        nonlocal staged_count
        if destination.name.startswith(".delete-"):
            staged_count += 1
            if staged_count == 2:
                raise OSError("injected second-stage failure")
        real_commit(source, destination)

    monkeypatch.setattr(
        test_attempts_module,
        "commit_staged_directory",
        fail_second_stage,
    )

    with pytest.raises(AttemptWorkflowError, match="injected second-stage failure"):
        clean_test_attempts(
            project,
            older_than_days=1,
            now=NOW + timedelta(days=2),
        )

    assert all(attempt.path.is_dir() for attempt in attempts)
    assert not list((project / ".runops/test-runs").glob(".delete-*"))
    assert not (project / ".runops/test-runs/.cleanup-pending.json").exists()


def test_clean_deletion_failure_is_diagnosed_and_rerunnable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    attempts = [
        prepare_test_attempt(
            project,
            "generic/base",
            kind="smoke",
            rerun=True,
            now=NOW + timedelta(minutes=index),
        )
        for index in range(2)
    ]
    for attempt in attempts:
        record_test_result(
            project,
            attempt.attempt.id,
            result="failed",
            now=NOW + timedelta(minutes=2),
        )

    real_rmtree = test_attempts_module.shutil.rmtree
    failure_injected = False

    def fail_once(path: Path, *args: object, **kwargs: object) -> None:
        nonlocal failure_injected
        if Path(path).name.startswith(".delete-") and not failure_injected:
            failure_injected = True
            raise OSError("injected deletion failure")
        real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(test_attempts_module.shutil, "rmtree", fail_once)

    with pytest.raises(AttemptWorkflowError, match=r"rerun.*clean"):
        clean_test_attempts(
            project,
            older_than_days=1,
            now=NOW + timedelta(days=2),
        )

    test_root = project / ".runops/test-runs"
    assert (test_root / ".cleanup-pending.json").is_file()
    assert len(list(test_root.glob(".delete-*"))) == 2

    retried = clean_test_attempts(
        project,
        older_than_days=1,
        now=NOW + timedelta(days=2),
    )

    assert retried.removed_ids == tuple(attempt.attempt.id for attempt in attempts)
    assert not (test_root / ".cleanup-pending.json").exists()
    assert not list(test_root.glob(".delete-*"))
    assert all(not attempt.path.exists() for attempt in attempts)


def test_clean_resumes_after_partial_tombstone_deletion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    attempt = prepare_test_attempt(project, "generic/base", kind="smoke", now=NOW)
    record_test_result(project, attempt.attempt.id, result="failed", now=NOW)
    real_rmtree = test_attempts_module.shutil.rmtree
    failure_injected = False

    def partially_delete_then_fail(
        path: Path,
        *args: object,
        **kwargs: object,
    ) -> None:
        nonlocal failure_injected
        tombstone = Path(path)
        if tombstone.name.startswith(".delete-") and not failure_injected:
            failure_injected = True
            (tombstone / "input/a.txt").unlink()
            raise OSError("injected failure after partial deletion")
        real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(
        test_attempts_module.shutil,
        "rmtree",
        partially_delete_then_fail,
    )

    with pytest.raises(AttemptWorkflowError, match=r"rerun.*clean"):
        clean_test_attempts(
            project,
            older_than_days=1,
            now=NOW + timedelta(days=2),
        )

    test_root = project / ".runops/test-runs"
    tombstone = test_root / f".delete-{attempt.attempt.id}"
    assert tombstone.is_dir()
    assert not (tombstone / "input/a.txt").exists()
    assert (test_root / ".cleanup-pending.json").is_file()

    retried = clean_test_attempts(
        project,
        older_than_days=1,
        now=NOW + timedelta(days=2),
    )

    assert retried.removed_ids == (attempt.attempt.id,)
    assert not tombstone.exists()
    assert not (test_root / ".cleanup-pending.json").exists()


def test_clean_rejects_terminal_attempt_with_drifted_input_snapshot(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    attempt = prepare_test_attempt(project, "generic/base", kind="smoke", now=NOW)
    record_test_result(project, attempt.attempt.id, result="passed", now=NOW)
    (attempt.path / "input/a.txt").write_bytes(b"tampered\n")

    with pytest.raises(AttemptWorkflowError, match="input snapshot integrity"):
        clean_test_attempts(
            project,
            older_than_days=1,
            now=NOW + timedelta(days=2),
        )

    test_root = project / ".runops/test-runs"
    assert attempt.path.is_dir()
    assert not (test_root / ".cleanup-pending.json").exists()
    assert not list(test_root.glob(".delete-*"))


def test_clean_resume_rejects_same_content_replacement_tombstone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    attempt = prepare_test_attempt(project, "generic/base", kind="smoke", now=NOW)
    record_test_result(project, attempt.attempt.id, result="passed", now=NOW)
    real_rmtree = test_attempts_module.shutil.rmtree
    failure_injected = False

    def fail_once(path: Path, *args: object, **kwargs: object) -> None:
        nonlocal failure_injected
        if Path(path).name.startswith(".delete-") and not failure_injected:
            failure_injected = True
            raise OSError("injected deletion failure")
        real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(test_attempts_module.shutil, "rmtree", fail_once)
    with pytest.raises(AttemptWorkflowError, match="deletion failed"):
        clean_test_attempts(
            project,
            older_than_days=1,
            now=NOW + timedelta(days=2),
        )

    test_root = project / ".runops/test-runs"
    receipt = test_root / ".cleanup-pending.json"
    tombstone = test_root / f".delete-{attempt.attempt.id}"
    replacement = tmp_path / "replacement-tombstone"
    shutil.copytree(tombstone, replacement)
    preserved = tmp_path / "original-tombstone"
    tombstone.rename(preserved)
    replacement.rename(tombstone)

    with pytest.raises(AttemptWorkflowError, match="directory identity"):
        clean_test_attempts(
            project,
            older_than_days=1,
            now=NOW + timedelta(days=2),
        )

    assert receipt.is_file()
    assert tombstone.is_dir()
    assert preserved.is_dir()


def test_clean_resume_rejects_tombstone_tree_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    attempt = prepare_test_attempt(project, "generic/base", kind="smoke", now=NOW)
    record_test_result(project, attempt.attempt.id, result="passed", now=NOW)
    real_rmtree = test_attempts_module.shutil.rmtree
    failure_injected = False

    def fail_once(path: Path, *args: object, **kwargs: object) -> None:
        nonlocal failure_injected
        if Path(path).name.startswith(".delete-") and not failure_injected:
            failure_injected = True
            raise OSError("injected deletion failure")
        real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(test_attempts_module.shutil, "rmtree", fail_once)
    with pytest.raises(AttemptWorkflowError, match="deletion failed"):
        clean_test_attempts(
            project,
            older_than_days=1,
            now=NOW + timedelta(days=2),
        )

    test_root = project / ".runops/test-runs"
    receipt = test_root / ".cleanup-pending.json"
    tombstone = test_root / f".delete-{attempt.attempt.id}"
    (tombstone / "work/drift.txt").write_bytes(b"tampered after staging\n")

    with pytest.raises(AttemptWorkflowError, match="tree digest"):
        clean_test_attempts(
            project,
            older_than_days=1,
            now=NOW + timedelta(days=2),
        )

    assert receipt.is_file()
    assert tombstone.is_dir()


def test_clean_resume_rejects_tombstone_test_receipt_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    attempt = prepare_test_attempt(project, "generic/base", kind="smoke", now=NOW)
    record_test_result(project, attempt.attempt.id, result="passed", now=NOW)
    real_rmtree = test_attempts_module.shutil.rmtree

    def fail_delete(path: Path, *args: object, **kwargs: object) -> None:
        if Path(path).name.startswith(".delete-"):
            raise OSError("injected deletion failure")
        real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(test_attempts_module.shutil, "rmtree", fail_delete)
    with pytest.raises(AttemptWorkflowError, match="deletion failed"):
        clean_test_attempts(
            project,
            older_than_days=1,
            now=NOW + timedelta(days=2),
        )

    test_root = project / ".runops/test-runs"
    pending = test_root / ".cleanup-pending.json"
    tombstone = test_root / f".delete-{attempt.attempt.id}"
    test_receipt = tombstone / "test-receipt.toml"
    test_receipt.write_text(
        test_receipt.read_text(encoding="utf-8").replace(
            'observation = ""',
            'observation = "drifted"',
        ),
        encoding="utf-8",
    )

    with pytest.raises(AttemptWorkflowError, match="test receipt integrity"):
        clean_test_attempts(
            project,
            older_than_days=1,
            now=NOW + timedelta(days=2),
        )

    assert pending.is_file()
    assert tombstone.is_dir()


def test_clean_resume_rejects_corrupted_cleanup_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    attempt = prepare_test_attempt(project, "generic/base", kind="smoke", now=NOW)
    record_test_result(project, attempt.attempt.id, result="passed", now=NOW)
    real_rmtree = test_attempts_module.shutil.rmtree

    def fail_delete(path: Path, *args: object, **kwargs: object) -> None:
        if Path(path).name.startswith(".delete-"):
            raise OSError("injected deletion failure")
        real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(test_attempts_module.shutil, "rmtree", fail_delete)
    with pytest.raises(AttemptWorkflowError, match="deletion failed"):
        clean_test_attempts(
            project,
            older_than_days=1,
            now=NOW + timedelta(days=2),
        )

    test_root = project / ".runops/test-runs"
    pending = test_root / ".cleanup-pending.json"
    payload = json.loads(pending.read_text(encoding="utf-8"))
    payload["phase"] = "staging"
    pending.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    with pytest.raises(AttemptWorkflowError, match="receipt integrity"):
        clean_test_attempts(
            project,
            older_than_days=1,
            now=NOW + timedelta(days=2),
        )

    assert pending.is_file()
    assert (test_root / f".delete-{attempt.attempt.id}").is_dir()


def test_clean_fails_closed_on_hardlinked_pending_receipt(tmp_path: Path) -> None:
    project = _project(tmp_path)
    test_root = project / ".runops" / "test-runs"
    test_root.mkdir(parents=True)
    external = project / "external-cleanup.json"
    external.write_text(
        '{"schema_version":1,"phase":"deleting","attempt_ids":["T20260901-0001"]}\n',
        encoding="utf-8",
    )
    (test_root / ".cleanup-pending.json").hardlink_to(external)

    with pytest.raises(AttemptWorkflowError, match="single-link"):
        clean_test_attempts(
            project,
            older_than_days=1,
            now=NOW + timedelta(days=2),
        )

    assert external.is_file()
    assert external.stat().st_nlink == 2


def test_clean_rejects_pending_receipt_swapped_before_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    test_root = project / ".runops" / "test-runs"
    test_root.mkdir(parents=True)
    receipt = test_root / ".cleanup-pending.json"
    payload = (
        '{"schema_version":1,"phase":"deleting","attempt_ids":["T20260901-0001"]}\n'
    )
    receipt.write_text(payload, encoding="utf-8")
    replacement = project / "replacement-cleanup.json"
    replacement.write_text(payload, encoding="utf-8")
    real_open = test_attempts_module.os.open
    swapped = False

    def swap_then_open(path: object, flags: int, *args: object) -> int:
        nonlocal swapped
        if Path(path) == receipt and not swapped:
            swapped = True
            os.replace(replacement, receipt)
        return real_open(path, flags, *args)

    monkeypatch.setattr(test_attempts_module.os, "open", swap_then_open)

    with pytest.raises(AttemptWorkflowError, match="changed while opening"):
        clean_test_attempts(
            project,
            older_than_days=1,
            now=NOW + timedelta(days=2),
        )
