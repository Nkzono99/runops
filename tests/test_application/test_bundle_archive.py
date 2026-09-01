"""Concurrency contracts for bundle archive and restore actions."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from contextlib import contextmanager
from pathlib import Path
from threading import Event
from typing import Any
from unittest.mock import patch

import pytest
import tomli as tomllib
import tomli_w

from runops.application.actions import ActionStatus, archive_bundle, restore_bundle
from runops.application.execution.submission import (
    SubmissionLockError,
    SubmitRequest,
    apply_submit,
    plan_submit,
    reset_retry_under_submission_lock,
)
from runops.core.manifest import read_manifest, update_manifest
from runops.core.project import load_project


def _write_manifest(run_dir: Path, data: dict[str, Any]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    with open(run_dir / "manifest.toml", "wb") as stream:
        tomli_w.dump(data, stream)


def _write_project(root: Path) -> None:
    (root / "runops.toml").write_text(
        '[project]\nname = "test"\n',
        encoding="utf-8",
    )


def _setup_adoption_bundle(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    _write_project(tmp_path)
    bundle = tmp_path / "runs" / "scan"
    current = bundle / "R20260901-0002"
    _write_manifest(
        current,
        {"run": {"id": current.name, "status": "cancelled"}},
    )
    destination = tmp_path / "runs" / "_archive" / "scan"
    adopted = destination / "nested" / "R20260901-0001"
    _write_manifest(
        adopted,
        {
            "run": {"id": adopted.name, "status": "archived"},
            "path": {
                "run_dir": str(adopted),
                "archived_from": str(bundle / "nested" / adopted.name),
            },
        },
    )
    return bundle, destination, current, adopted


def _assert_adoption_recovered(
    bundle: Path,
    destination: Path,
    current: Path,
    adopted: Path,
) -> None:
    assert not bundle.exists()
    assert (destination / ".runops-archive.toml").is_file()
    assert not list(destination.parent.glob(f".tmp-adopt-{destination.name}-*"))
    final_current = destination / current.relative_to(bundle)
    final_adopted = destination / adopted.relative_to(destination)
    for run_dir in (final_current, final_adopted):
        manifest = read_manifest(run_dir)
        assert manifest.path["run_dir"] == str(run_dir.resolve())
        assert manifest.path["bundle_archived_at"]
        assert manifest.storage["tier"] == "cold"


def test_archive_bundle_waits_for_submit_and_revalidates_state(tmp_path: Path) -> None:
    _write_project(tmp_path)
    bundle = tmp_path / "runs" / "scan"
    run_dir = bundle / "R20260901-0001"
    _write_manifest(
        run_dir,
        {
            "run": {"id": run_dir.name, "status": "created"},
            "job": {},
        },
    )
    (run_dir / "submit").mkdir()
    (run_dir / "submit" / "job.sh").write_text(
        "#!/bin/bash\n#SBATCH --job-name=test\n",
        encoding="utf-8",
    )
    (run_dir / "input").mkdir()
    (run_dir / "input" / "params.json").write_text("{}", encoding="utf-8")
    submit_plan = plan_submit(SubmitRequest(run_dir=run_dir))
    scheduler_entered = Event()
    release_scheduler = Event()
    archive_started = Event()

    def submitter(command: tuple[str, ...]) -> str:
        scheduler_entered.set()
        assert release_scheduler.wait(timeout=5)
        return "98765"

    def archive() -> Any:
        archive_started.set()
        return archive_bundle(bundle)

    with ThreadPoolExecutor(max_workers=2) as executor:
        submitted = executor.submit(apply_submit, submit_plan, submitter)
        assert scheduler_entered.wait(timeout=5)
        archived = executor.submit(archive)
        assert archive_started.wait(timeout=5)
        assert not archived.done()
        release_scheduler.set()

        assert submitted.result(timeout=5).job_id == "98765"
        archive_result = archived.result(timeout=5)

    assert archive_result.status is ActionStatus.PRECONDITION_FAILED
    assert "submitted" in archive_result.message
    assert bundle.is_dir()
    assert read_manifest(run_dir).run["status"] == "submitted"
    assert not (tmp_path / "runs" / "_archive" / "scan").exists()


def test_restore_bundle_waits_for_retry_and_reloads_manifest(tmp_path: Path) -> None:
    _write_project(tmp_path)
    bundle = tmp_path / "runs" / "scan"
    run_dir = bundle / "R20260901-0001"
    _write_manifest(
        run_dir,
        {
            "run": {"id": run_dir.name, "status": "failed"},
            "job": {"job_id": "12345"},
        },
    )
    archive_result = archive_bundle(bundle)
    assert archive_result.status is ActionStatus.SUCCESS
    archived_bundle = Path(str(archive_result.data["archive_path"]))
    archived_run = archived_bundle / run_dir.name
    retry_entered = Event()
    release_retry = Event()
    restore_started = Event()

    def resetter() -> None:
        retry_entered.set()
        assert release_retry.wait(timeout=5)
        update_manifest(
            archived_run,
            {
                "run": {"status": "created"},
                "job": {"job_id": ""},
            },
        )

    def restore() -> Any:
        restore_started.set()
        return restore_bundle(archived_bundle)

    with ThreadPoolExecutor(max_workers=2) as executor:
        retried = executor.submit(
            reset_retry_under_submission_lock,
            archived_run,
            resetter,
        )
        assert retry_entered.wait(timeout=5)
        restored = executor.submit(restore)
        assert restore_started.wait(timeout=5)
        assert not restored.done()
        release_retry.set()

        retried.result(timeout=5)
        restore_result = restored.result(timeout=5)

    assert restore_result.status is ActionStatus.SUCCESS
    restored_manifest = read_manifest(run_dir)
    assert restored_manifest.run["status"] == "created"
    assert restored_manifest.job["job_id"] == ""


def test_archive_bundle_holds_child_guards_in_path_order_through_updates(
    tmp_path: Path,
) -> None:
    from runops.application.actions import bundle_archive as bundle_module

    _write_project(tmp_path)
    bundle = tmp_path / "runs" / "scan"
    run_dirs = [
        bundle / "nested" / "R20260901-0002",
        bundle / "R20260901-0001",
    ]
    for run_dir in run_dirs:
        _write_manifest(
            run_dir,
            {"run": {"id": run_dir.name, "status": "completed"}},
        )
    expected = tuple(sorted((path.resolve() for path in run_dirs), key=str))
    entered: list[Path] = []
    active: set[Path] = set()
    real_write_manifest = bundle_module.write_manifest

    @contextmanager
    def recording_guard(run_dir: Path) -> Any:
        entered.append(run_dir)
        active.add(run_dir)
        try:
            yield
        finally:
            active.remove(run_dir)

    def guarded_write_manifest(run_dir: Path, data: Any) -> None:
        assert active == set(expected)
        real_write_manifest(run_dir, data)

    with (
        patch.object(bundle_module, "submission_guard", side_effect=recording_guard),
        patch.object(
            bundle_module,
            "write_manifest",
            side_effect=guarded_write_manifest,
        ),
    ):
        result = archive_bundle(bundle)

    assert result.status is ActionStatus.SUCCESS
    assert entered == list(expected)
    assert active == set()


def test_archive_bundle_reports_child_lock_failure_without_mutation(
    tmp_path: Path,
) -> None:
    from runops.application.actions import bundle_archive as bundle_module

    _write_project(tmp_path)
    bundle = tmp_path / "runs" / "scan"
    run_dir = bundle / "R20260901-0001"
    _write_manifest(
        run_dir,
        {"run": {"id": run_dir.name, "status": "completed"}},
    )
    lock_path = run_dir / ".runops-submit.lock"

    @contextmanager
    def failing_guard(guarded_run: Path) -> Any:
        raise SubmissionLockError(guarded_run / lock_path.name, OSError("busy"))
        yield

    with patch.object(bundle_module, "submission_guard", side_effect=failing_guard):
        result = archive_bundle(bundle)

    assert result.status is ActionStatus.PRECONDITION_FAILED
    assert result.data["lock_path"] == str(lock_path)
    assert "Failed to lock bundle child Run" in result.message
    assert run_dir.is_dir()
    assert not (tmp_path / "runs" / "_archive" / "scan").exists()


def test_archive_bundle_does_not_replace_destination_claimed_after_revalidation(
    tmp_path: Path,
) -> None:
    from runops.application.actions import bundle_archive as bundle_module

    _write_project(tmp_path)
    bundle = tmp_path / "runs" / "scan"
    run_dir = bundle / "R20260901-0001"
    _write_manifest(
        run_dir,
        {"run": {"id": run_dir.name, "status": "completed"}},
    )
    destination = tmp_path / "runs" / "_archive" / "scan"
    real_move = bundle_module.move_directory_noreplace

    def claim_then_move(source: Path, target: Path) -> None:
        target.mkdir(parents=True)
        (target / "competitor.txt").write_text("keep\n", encoding="utf-8")
        real_move(source, target)

    with patch.object(
        bundle_module,
        "move_directory_noreplace",
        side_effect=claim_then_move,
    ):
        result = archive_bundle(bundle)

    assert result.status is ActionStatus.ERROR
    assert "File exists" in result.message
    assert run_dir.is_dir()
    assert (bundle / ".runops-archive.toml").is_file()
    assert list(bundle.parent.glob(".runops-bundle-archive-*.receipt.toml"))
    assert (destination / "competitor.txt").read_text(encoding="utf-8") == "keep\n"


def test_restore_bundle_does_not_replace_destination_claimed_after_revalidation(
    tmp_path: Path,
) -> None:
    from runops.application.actions import bundle_archive as bundle_module

    _write_project(tmp_path)
    bundle = tmp_path / "runs" / "scan"
    run_dir = bundle / "R20260901-0001"
    _write_manifest(
        run_dir,
        {"run": {"id": run_dir.name, "status": "completed"}},
    )
    archived_result = archive_bundle(bundle)
    archived = Path(str(archived_result.data["archive_path"]))
    real_move = bundle_module.move_directory_noreplace

    def claim_then_move(source: Path, target: Path) -> None:
        target.mkdir(parents=True)
        (target / "competitor.txt").write_text("keep\n", encoding="utf-8")
        real_move(source, target)

    with patch.object(
        bundle_module,
        "move_directory_noreplace",
        side_effect=claim_then_move,
    ):
        result = restore_bundle(archived)

    assert result.status is ActionStatus.ERROR
    assert "File exists" in result.message
    assert archived.is_dir()
    assert (archived / ".runops-archive.toml").is_file()
    assert (bundle / "competitor.txt").read_text(encoding="utf-8") == "keep\n"


def test_managed_bundle_rejects_external_archive_root(tmp_path: Path) -> None:
    _write_project(tmp_path)
    bundle = tmp_path / "runs" / "scan"
    run_dir = bundle / "R20260901-0001"
    _write_manifest(
        run_dir,
        {"run": {"id": run_dir.name, "status": "completed"}},
    )

    result = archive_bundle(bundle, archive_root=tmp_path / "external-cold")

    assert result.status is ActionStatus.PRECONDITION_FAILED
    assert (
        "external archive root would bypass Result and budget gates" in result.message
    )
    assert run_dir.is_dir()


def test_managed_bundle_rejects_symlinked_archive_root(tmp_path: Path) -> None:
    _write_project(tmp_path)
    bundle = tmp_path / "runs" / "scan"
    run_dir = bundle / "R20260901-0001"
    _write_manifest(
        run_dir,
        {"run": {"id": run_dir.name, "status": "completed"}},
    )
    outside = tmp_path / "external-cold"
    outside.mkdir()
    (tmp_path / "runs" / "_archive").symlink_to(
        outside,
        target_is_directory=True,
    )

    result = archive_bundle(bundle)

    assert result.status is ActionStatus.PRECONDITION_FAILED
    assert "archive root must not be a symlink" in result.message
    assert run_dir.is_dir()
    assert not (outside / "scan").exists()


def test_bundle_archive_rejects_hidden_symlink_run_namespace(tmp_path: Path) -> None:
    _write_project(tmp_path)
    bundle = tmp_path / "runs" / "scan"
    visible = bundle / "R20260901-0001"
    _write_manifest(
        visible,
        {"run": {"id": visible.name, "status": "completed"}},
    )
    outside = tmp_path / "outside-runs"
    hidden = outside / "R20260901-0002"
    _write_manifest(
        hidden,
        {"run": {"id": hidden.name, "status": "running"}},
    )
    (bundle / "hidden").symlink_to(outside, target_is_directory=True)

    result = archive_bundle(bundle)

    assert result.status is ActionStatus.PRECONDITION_FAILED
    assert "symbolic link" in result.message
    assert visible.is_dir()
    assert hidden.is_dir()


def test_bundle_archive_waits_for_full_run_publication_transaction(
    tmp_path: Path,
) -> None:
    from runops.application.run_creation import create_case_run
    from runops.application.run_creation import workflow as workflow_module

    _write_project(tmp_path)
    (tmp_path / "simulators.toml").write_text(
        "[simulators.generic]\n"
        'adapter = "generic"\n'
        'executable = "echo"\n'
        'resolver_mode = "package"\n',
        encoding="utf-8",
    )
    (tmp_path / "launchers.toml").write_text(
        '[launchers.srun]\nkind = "srun"\ncommand = "srun"\nuse_slurm_ntasks = true\n',
        encoding="utf-8",
    )
    case_dir = tmp_path / "cases" / "base"
    case_dir.mkdir(parents=True)
    (case_dir / "case.toml").write_text(
        "[case]\n"
        'name = "base"\n'
        'simulator = "generic"\n'
        'launcher = "srun"\n\n'
        "[job]\n"
        'walltime = "00:10:00"\n'
        "ntasks = 1\n",
        encoding="utf-8",
    )
    bundle = tmp_path / "runs" / "scan"
    existing = bundle / "R20260901-0001"
    _write_manifest(
        existing,
        {"run": {"id": existing.name, "status": "completed"}},
    )
    project = load_project(tmp_path)
    render_entered = Event()
    release_render = Event()
    real_copy = workflow_module._copy_case_files

    def block_after_staging(source: Path, destination: Path) -> list[str]:
        render_entered.set()
        assert release_render.wait(timeout=5)
        return real_copy(source, destination)

    with (
        patch.object(workflow_module, "_copy_case_files", block_after_staging),
        ThreadPoolExecutor(max_workers=2) as executor,
    ):
        created_future = executor.submit(
            create_case_run,
            project,
            "base",
            dest_dir=bundle,
        )
        assert render_entered.wait(timeout=5)
        archived_future = executor.submit(archive_bundle, bundle)
        with pytest.raises(FutureTimeoutError):
            archived_future.result(timeout=0.1)
        release_render.set()
        created = created_future.result(timeout=5)
        archived = archived_future.result(timeout=5)

    assert created.run_info.run_dir.is_dir()
    assert archived.status is ActionStatus.PRECONDITION_FAILED
    assert bundle.is_dir()
    assert not list(bundle.glob(".tmp-*"))


def test_managed_bundle_restore_rejects_edited_external_destination(
    tmp_path: Path,
) -> None:
    _write_project(tmp_path)
    bundle = tmp_path / "runs" / "scan"
    run_dir = bundle / "R20260901-0001"
    _write_manifest(
        run_dir,
        {"run": {"id": run_dir.name, "status": "completed"}},
    )
    archived_result = archive_bundle(bundle)
    assert archived_result.status is ActionStatus.SUCCESS
    archived = Path(str(archived_result.data["archive_path"]))
    outside = tmp_path / "external-restore"
    with (archived / ".runops-archive.toml").open("wb") as stream:
        tomli_w.dump(
            {
                "bundle": {
                    "format_version": 1,
                    "archived_from": str(outside),
                    "run_count": 1,
                }
            },
            stream,
        )

    result = restore_bundle(archived)

    assert result.status is ActionStatus.PRECONDITION_FAILED
    assert "must be restored inside" in result.message
    assert archived.is_dir()
    assert not outside.exists()


def test_archive_bundle_refuses_move_when_marker_directory_fsync_fails(
    tmp_path: Path,
) -> None:
    from runops.application.actions import bundle_archive as bundle_module

    _write_project(tmp_path)
    bundle = tmp_path / "runs" / "scan"
    run_dir = bundle / "R20260901-0001"
    _write_manifest(
        run_dir,
        {"run": {"id": run_dir.name, "status": "completed"}},
    )

    with patch.object(
        bundle_module,
        "_fsync_directory",
        side_effect=OSError("injected marker fsync failure"),
    ):
        result = archive_bundle(bundle)

    assert result.status is ActionStatus.ERROR
    assert "injected marker fsync failure" in result.message
    assert run_dir.is_dir()
    assert not (bundle / ".runops-archive.toml").exists()
    assert not (tmp_path / "runs" / "_archive" / "scan").exists()


def test_restore_bundle_rolls_back_when_marker_unlink_fsync_fails(
    tmp_path: Path,
) -> None:
    from runops.application.actions import bundle_archive as bundle_module

    _write_project(tmp_path)
    bundle = tmp_path / "runs" / "scan"
    run_dir = bundle / "R20260901-0001"
    _write_manifest(
        run_dir,
        {"run": {"id": run_dir.name, "status": "completed"}},
    )
    archived_result = archive_bundle(bundle)
    assert archived_result.status is ActionStatus.SUCCESS
    archived = Path(str(archived_result.data["archive_path"]))

    with patch.object(
        bundle_module,
        "_fsync_directory",
        side_effect=[OSError("injected marker unlink fsync failure"), None],
    ):
        result = restore_bundle(archived)

    assert result.status is ActionStatus.ERROR
    assert "injected marker unlink fsync failure" in result.message
    assert archived.is_dir()
    assert (archived / ".runops-archive.toml").is_file()
    assert not bundle.exists()
    assert read_manifest(archived / run_dir.name).storage["tier"] == "cold"


@pytest.mark.parametrize("unsafe_kind", ["symlink", "hardlink"])
def test_restore_bundle_rejects_unsafe_marker_without_moving(
    tmp_path: Path,
    unsafe_kind: str,
) -> None:
    _write_project(tmp_path)
    bundle = tmp_path / "runs" / "scan"
    run_dir = bundle / "R20260901-0001"
    _write_manifest(
        run_dir,
        {"run": {"id": run_dir.name, "status": "completed"}},
    )
    archived_result = archive_bundle(bundle)
    archived = Path(str(archived_result.data["archive_path"]))
    marker = archived / ".runops-archive.toml"
    external = tmp_path / "external-marker.toml"
    external.write_bytes(marker.read_bytes())
    marker.unlink()
    if unsafe_kind == "symlink":
        marker.symlink_to(external)
    else:
        marker.hardlink_to(external)

    result = restore_bundle(archived)

    assert result.status is ActionStatus.PRECONDITION_FAILED
    assert "single-link regular file" in result.message
    assert archived.is_dir()
    assert not bundle.exists()


def test_restore_bundle_fails_closed_when_marker_changes_during_move(
    tmp_path: Path,
) -> None:
    from runops.application.actions import bundle_archive as bundle_module

    _write_project(tmp_path)
    bundle = tmp_path / "runs" / "scan"
    run_dir = bundle / "R20260901-0001"
    _write_manifest(
        run_dir,
        {"run": {"id": run_dir.name, "status": "completed"}},
    )
    archived_result = archive_bundle(bundle)
    archived = Path(str(archived_result.data["archive_path"]))
    original_marker = (archived / ".runops-archive.toml").read_bytes()
    real_move = bundle_module.move_directory_noreplace
    calls = 0

    def mutate_then_move(source: Path, destination: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            marker = source / ".runops-archive.toml"
            marker.write_text(
                marker.read_text(encoding="utf-8") + "\n# concurrent edit\n",
                encoding="utf-8",
            )
        real_move(source, destination)

    with patch.object(
        bundle_module,
        "move_directory_noreplace",
        side_effect=mutate_then_move,
    ):
        result = restore_bundle(archived)

    assert result.status is ActionStatus.ERROR
    assert "marker image changed" in result.message
    assert not archived.exists()
    assert bundle.is_dir()
    changed_marker = bundle / ".runops-archive.toml"
    assert changed_marker.read_bytes() != original_marker
    assert b"concurrent edit" in changed_marker.read_bytes()
    assert list(archived.parent.glob(".runops-bundle-restore-*.receipt.toml"))


@pytest.mark.parametrize(
    "interrupt_phase",
    ["receipt", "marker", "move", "manifest", "cleanup", "after_cleanup"],
)
def test_archive_bundle_resumes_ordinary_transaction_after_process_death(
    tmp_path: Path,
    interrupt_phase: str,
) -> None:
    from runops.application.actions import bundle_archive as bundle_module

    _write_project(tmp_path)
    bundle = tmp_path / "runs" / "scan"
    for index in (1, 2):
        run_dir = bundle / f"R20260901-{index:04d}"
        _write_manifest(
            run_dir,
            {"run": {"id": run_dir.name, "status": "completed"}},
        )
    real_toml = bundle_module._write_toml_atomic
    real_bytes = bundle_module._write_bytes_atomic
    real_move = bundle_module.move_directory_noreplace
    real_cleanup = bundle_module._unlink_file_durable_with_retry
    interrupted = False

    def interrupting_toml(path: Path, data: dict[str, Any]) -> None:
        real_toml(path, data)
        if path.name.endswith(".receipt.toml"):
            raise KeyboardInterrupt("after receipt")

    def interrupting_bytes(path: Path, payload: bytes) -> None:
        nonlocal interrupted
        real_bytes(path, payload)
        if interrupt_phase == "marker" and path.name == ".runops-archive.toml":
            raise KeyboardInterrupt("after marker")
        if (
            interrupt_phase == "manifest"
            and path.name == "manifest.toml"
            and not interrupted
        ):
            interrupted = True
            raise KeyboardInterrupt("after one manifest")

    def interrupting_move(source: Path, destination: Path) -> Any:
        real_move(source, destination)
        raise KeyboardInterrupt("after move")

    def interrupting_cleanup(path: Path) -> None:
        if interrupt_phase == "cleanup":
            raise KeyboardInterrupt("before receipt cleanup")
        real_cleanup(path)
        raise KeyboardInterrupt("after receipt cleanup")

    if interrupt_phase == "receipt":
        patch_name, side_effect = "_write_toml_atomic", interrupting_toml
    elif interrupt_phase in {"marker", "manifest"}:
        patch_name, side_effect = "_write_bytes_atomic", interrupting_bytes
    elif interrupt_phase == "move":
        patch_name, side_effect = "move_directory_noreplace", interrupting_move
    else:
        patch_name, side_effect = (
            "_unlink_file_durable_with_retry",
            interrupting_cleanup,
        )
    with (
        patch.object(bundle_module, patch_name, side_effect=side_effect),
        pytest.raises(KeyboardInterrupt),
    ):
        archive_bundle(bundle)

    resumed = archive_bundle(bundle)

    assert resumed.status is ActionStatus.SUCCESS
    assert resumed.data["resumed"] is True
    destination = tmp_path / "runs" / "_archive" / "scan"
    assert not bundle.exists()
    assert (destination / ".runops-archive.toml").is_file()
    assert not list(bundle.parent.glob(".runops-bundle-archive-*.receipt.toml"))
    for run_dir in destination.glob("R*"):
        assert read_manifest(run_dir).storage["tier"] == "cold"


@pytest.mark.parametrize(
    "interrupt_phase",
    ["receipt", "move", "manifest", "marker_cleanup", "cleanup", "after_cleanup"],
)
def test_restore_bundle_resumes_ordinary_transaction_after_process_death(
    tmp_path: Path,
    interrupt_phase: str,
) -> None:
    from runops.application.actions import bundle_archive as bundle_module

    _write_project(tmp_path)
    bundle = tmp_path / "runs" / "scan"
    for index in (1, 2):
        run_dir = bundle / f"R20260901-{index:04d}"
        _write_manifest(
            run_dir,
            {"run": {"id": run_dir.name, "status": "completed"}},
        )
    archived_result = archive_bundle(bundle)
    archived = Path(str(archived_result.data["archive_path"]))
    real_toml = bundle_module._write_toml_atomic
    real_bytes = bundle_module._write_bytes_atomic
    real_move = bundle_module.move_directory_noreplace
    real_cleanup = bundle_module._unlink_file_durable_with_retry
    interrupted = False

    def interrupting_toml(path: Path, data: dict[str, Any]) -> None:
        real_toml(path, data)
        if path.name.endswith(".receipt.toml"):
            raise KeyboardInterrupt("after receipt")

    def interrupting_bytes(path: Path, payload: bytes) -> None:
        nonlocal interrupted
        real_bytes(path, payload)
        if path.name == "manifest.toml" and not interrupted:
            interrupted = True
            raise KeyboardInterrupt("after one manifest")

    def interrupting_move(source: Path, destination: Path) -> Any:
        real_move(source, destination)
        raise KeyboardInterrupt("after move")

    def interrupting_cleanup(path: Path) -> None:
        is_marker = path.name == ".runops-archive.toml"
        is_receipt = path.name.endswith(".receipt.toml")
        if interrupt_phase == "marker_cleanup" and is_marker:
            real_cleanup(path)
            raise KeyboardInterrupt("after marker cleanup")
        if interrupt_phase == "cleanup" and is_receipt:
            raise KeyboardInterrupt("before receipt cleanup")
        real_cleanup(path)
        if interrupt_phase == "after_cleanup" and is_receipt:
            raise KeyboardInterrupt("after receipt cleanup")

    if interrupt_phase == "receipt":
        patch_name, side_effect = "_write_toml_atomic", interrupting_toml
    elif interrupt_phase == "manifest":
        patch_name, side_effect = "_write_bytes_atomic", interrupting_bytes
    elif interrupt_phase == "move":
        patch_name, side_effect = "move_directory_noreplace", interrupting_move
    else:
        patch_name, side_effect = (
            "_unlink_file_durable_with_retry",
            interrupting_cleanup,
        )
    with (
        patch.object(bundle_module, patch_name, side_effect=side_effect),
        pytest.raises(KeyboardInterrupt),
    ):
        restore_bundle(archived)

    resumed = restore_bundle(archived)

    assert resumed.status is ActionStatus.SUCCESS
    assert resumed.data["resumed"] is True
    assert not archived.exists()
    assert bundle.is_dir()
    assert not (bundle / ".runops-archive.toml").exists()
    assert not list(archived.parent.glob(".runops-bundle-restore-*.receipt.toml"))
    for run_dir in bundle.glob("R*"):
        assert read_manifest(run_dir).storage["tier"] == "hot"


def test_archive_bundle_recovery_rejects_manifest_drift_without_clobber(
    tmp_path: Path,
) -> None:
    from runops.application.actions import bundle_archive as bundle_module

    _write_project(tmp_path)
    bundle = tmp_path / "runs" / "scan"
    run_dir = bundle / "R20260901-0001"
    _write_manifest(
        run_dir,
        {"run": {"id": run_dir.name, "status": "completed"}},
    )
    real_toml = bundle_module._write_toml_atomic

    def interrupt_after_receipt(path: Path, data: dict[str, Any]) -> None:
        real_toml(path, data)
        if path.name.endswith(".receipt.toml"):
            raise KeyboardInterrupt("after receipt")

    with (
        patch.object(
            bundle_module,
            "_write_toml_atomic",
            side_effect=interrupt_after_receipt,
        ),
        pytest.raises(KeyboardInterrupt),
    ):
        archive_bundle(bundle)
    manifest = read_manifest(run_dir)
    manifest.extra_sections["analysis"] = {"operator_note": "changed after receipt"}
    _write_manifest(run_dir, manifest.to_dict())
    changed = (run_dir / "manifest.toml").read_bytes()

    resumed = archive_bundle(bundle)

    assert resumed.status is ActionStatus.PRECONDITION_FAILED
    assert "manifest image changed" in resumed.message
    assert (run_dir / "manifest.toml").read_bytes() == changed
    assert not (tmp_path / "runs" / "_archive" / "scan").exists()
    assert list(bundle.parent.glob(".runops-bundle-archive-*.receipt.toml"))


def test_archive_bundle_recovery_rejects_tampered_receipt_postimage_contract(
    tmp_path: Path,
) -> None:
    from runops.application.actions import bundle_archive as bundle_module

    _write_project(tmp_path)
    bundle = tmp_path / "runs" / "scan"
    run_dir = bundle / "R20260901-0001"
    _write_manifest(
        run_dir,
        {"run": {"id": run_dir.name, "status": "completed"}},
    )
    original = (run_dir / "manifest.toml").read_bytes()
    real_toml = bundle_module._write_toml_atomic

    def interrupt_after_receipt(path: Path, data: dict[str, Any]) -> None:
        real_toml(path, data)
        if path.name.endswith(".receipt.toml"):
            raise KeyboardInterrupt("after receipt")

    with (
        patch.object(
            bundle_module,
            "_write_toml_atomic",
            side_effect=interrupt_after_receipt,
        ),
        pytest.raises(KeyboardInterrupt),
    ):
        archive_bundle(bundle)
    receipt = next(bundle.parent.glob(".runops-bundle-archive-*.receipt.toml"))
    with receipt.open("rb") as stream:
        payload = tomllib.load(stream)
    payload["transaction"]["transition_at"] = "2099-01-01T00:00:00+00:00"
    with receipt.open("wb") as stream:
        tomli_w.dump(payload, stream)

    resumed = archive_bundle(bundle)

    assert resumed.status is ActionStatus.PRECONDITION_FAILED
    assert "postimage" in resumed.message
    assert (run_dir / "manifest.toml").read_bytes() == original
    assert not (tmp_path / "runs" / "_archive" / "scan").exists()
    assert receipt.is_file()


def test_restore_bundle_recovery_rejects_directory_replacement_without_move(
    tmp_path: Path,
) -> None:
    from runops.application.actions import bundle_archive as bundle_module

    _write_project(tmp_path)
    bundle = tmp_path / "runs" / "scan"
    run_dir = bundle / "R20260901-0001"
    _write_manifest(
        run_dir,
        {"run": {"id": run_dir.name, "status": "completed"}},
    )
    archived_result = archive_bundle(bundle)
    archived = Path(str(archived_result.data["archive_path"]))
    archived_run = archived / run_dir.name
    original_manifest = (archived_run / "manifest.toml").read_bytes()
    real_toml = bundle_module._write_toml_atomic

    def interrupt_after_receipt(path: Path, data: dict[str, Any]) -> None:
        real_toml(path, data)
        if path.name.endswith(".receipt.toml"):
            raise KeyboardInterrupt("after receipt")

    with (
        patch.object(
            bundle_module,
            "_write_toml_atomic",
            side_effect=interrupt_after_receipt,
        ),
        pytest.raises(KeyboardInterrupt),
    ):
        restore_bundle(archived)
    displaced = tmp_path / "displaced-run"
    archived_run.rename(displaced)
    archived_run.mkdir()
    (archived_run / "manifest.toml").write_bytes(original_manifest)

    resumed = restore_bundle(archived)

    assert resumed.status is ActionStatus.PRECONDITION_FAILED
    assert "directory identity changed" in resumed.message
    assert archived_run.is_dir()
    assert displaced.is_dir()
    assert not bundle.exists()
    assert list(archived.parent.glob(".runops-bundle-restore-*.receipt.toml"))


@pytest.mark.parametrize("interrupt_after_move", [1, 2, 3])
def test_archive_bundle_adoption_resumes_after_each_committed_move(
    tmp_path: Path,
    interrupt_after_move: int,
) -> None:
    from runops.application.actions import bundle_archive as bundle_module

    bundle, destination, current, adopted = _setup_adoption_bundle(tmp_path)
    real_move = bundle_module.move_directory_noreplace
    calls = 0

    def interrupting_move(source: Path, target: Path) -> Any:
        nonlocal calls
        outcome = real_move(source, target)
        calls += 1
        if calls == interrupt_after_move:
            raise KeyboardInterrupt("simulated process death after durable move")
        return outcome

    with (
        patch.object(
            bundle_module,
            "move_directory_noreplace",
            side_effect=interrupting_move,
        ),
        pytest.raises(KeyboardInterrupt),
    ):
        archive_bundle(bundle, adopt_archived=True)

    transactions = list(destination.parent.glob(f".tmp-adopt-{destination.name}-*"))
    assert len(transactions) == 1
    assert (transactions[0] / "receipt.toml").is_file()

    resumed = archive_bundle(bundle, adopt_archived=True)

    assert resumed.status is ActionStatus.SUCCESS
    assert resumed.data["resumed"] is True
    _assert_adoption_recovered(bundle, destination, current, adopted)


@pytest.mark.parametrize(
    "interrupt_phase",
    ["marker", "manifest", "cleanup", "receipt_unlink"],
)
def test_archive_bundle_adoption_resumes_metadata_and_cleanup(
    tmp_path: Path,
    interrupt_phase: str,
) -> None:
    from runops.application.actions import bundle_archive as bundle_module

    bundle, destination, current, adopted = _setup_adoption_bundle(tmp_path)
    real_write_toml = bundle_module._write_toml_atomic
    real_write_manifest = bundle_module.write_manifest
    real_finish = bundle_module._finish_adoption_transaction
    real_unlink = bundle_module._unlink_file_durable
    interrupted = False

    def interrupting_toml(path: Path, data: dict[str, Any]) -> None:
        nonlocal interrupted
        real_write_toml(path, data)
        if path.name == ".runops-archive.toml" and not interrupted:
            interrupted = True
            raise KeyboardInterrupt("simulated process death after marker")

    def interrupting_manifest(run_dir: Path, manifest: Any) -> None:
        nonlocal interrupted
        real_write_manifest(run_dir, manifest)
        if not interrupted:
            interrupted = True
            raise KeyboardInterrupt("simulated process death after manifest")

    def interrupting_finish(transaction: Path) -> None:
        nonlocal interrupted
        if not interrupted:
            interrupted = True
            raise KeyboardInterrupt("simulated process death before cleanup")
        real_finish(transaction)

    def interrupting_unlink(path: Path) -> None:
        nonlocal interrupted
        real_unlink(path)
        if path.name == "receipt.toml" and not interrupted:
            interrupted = True
            raise KeyboardInterrupt("simulated process death after receipt cleanup")

    patch_name: str
    side_effect: Any
    if interrupt_phase == "marker":
        patch_name = "_write_toml_atomic"
        side_effect = interrupting_toml
    elif interrupt_phase == "manifest":
        patch_name = "write_manifest"
        side_effect = interrupting_manifest
    elif interrupt_phase == "cleanup":
        patch_name = "_finish_adoption_transaction"
        side_effect = interrupting_finish
    else:
        patch_name = "_unlink_file_durable"
        side_effect = interrupting_unlink

    with (
        patch.object(bundle_module, patch_name, side_effect=side_effect),
        pytest.raises(KeyboardInterrupt),
    ):
        archive_bundle(bundle, adopt_archived=True)

    resumed = archive_bundle(bundle, adopt_archived=True)

    assert resumed.status is ActionStatus.SUCCESS
    _assert_adoption_recovered(bundle, destination, current, adopted)


def test_archive_bundle_adoption_retry_after_transaction_directory_removal(
    tmp_path: Path,
) -> None:
    from runops.application.actions import bundle_archive as bundle_module

    bundle, destination, current, adopted = _setup_adoption_bundle(tmp_path)
    real_fsync = bundle_module._fsync_directory
    interrupted = False

    def interrupt_after_transaction_removal(path: Path) -> None:
        nonlocal interrupted
        transactions = list(destination.parent.glob(f".tmp-adopt-{destination.name}-*"))
        if path == destination.parent and not transactions and not interrupted:
            interrupted = True
            raise KeyboardInterrupt(
                "simulated process death after adoption transaction removal"
            )
        real_fsync(path)

    with (
        patch.object(
            bundle_module,
            "_fsync_directory",
            side_effect=interrupt_after_transaction_removal,
        ),
        pytest.raises(KeyboardInterrupt),
    ):
        archive_bundle(bundle, adopt_archived=True)

    assert not bundle.exists()
    assert destination.is_dir()
    assert not list(destination.parent.glob(f".tmp-adopt-{destination.name}-*"))

    fsynced: list[Path] = []

    def record_fsync(path: Path) -> None:
        fsynced.append(path)
        real_fsync(path)

    with patch.object(
        bundle_module,
        "_fsync_directory",
        side_effect=record_fsync,
    ):
        resumed = archive_bundle(bundle, adopt_archived=True)

    assert resumed.status is ActionStatus.SUCCESS
    assert resumed.data["resumed"] is True
    assert destination.parent in fsynced
    _assert_adoption_recovered(bundle, destination, current, adopted)


def test_archive_bundle_adoption_fails_closed_on_tampered_receipt(
    tmp_path: Path,
) -> None:
    from runops.application.actions import bundle_archive as bundle_module

    bundle, destination, _current, _adopted = _setup_adoption_bundle(tmp_path)
    real_move = bundle_module.move_directory_noreplace

    def interrupt_first_move(source: Path, target: Path) -> Any:
        real_move(source, target)
        raise KeyboardInterrupt("simulated process death after destination move")

    with (
        patch.object(
            bundle_module,
            "move_directory_noreplace",
            side_effect=interrupt_first_move,
        ),
        pytest.raises(KeyboardInterrupt),
    ):
        archive_bundle(bundle, adopt_archived=True)

    transaction = next(destination.parent.glob(f".tmp-adopt-{destination.name}-*"))
    receipt = transaction / "receipt.toml"
    with open(receipt, "rb") as stream:
        data = tomllib.load(stream)
    data["adoption"]["source_path"] = str(tmp_path / "runs" / "other")
    with open(receipt, "wb") as stream:
        tomli_w.dump(data, stream)

    result = archive_bundle(bundle, adopt_archived=True)

    assert result.status is ActionStatus.PRECONDITION_FAILED
    assert "is inconsistent" in result.message
    assert bundle.is_dir()
    assert (transaction / "adopted").is_dir()


def test_archive_bundle_adoption_preserves_unsupported_v1_receipt(
    tmp_path: Path,
) -> None:
    from runops.application.actions import bundle_archive as bundle_module

    bundle, destination, _current, _adopted = _setup_adoption_bundle(tmp_path)
    real_move = bundle_module.move_directory_noreplace

    def interrupt_first_move(source: Path, target: Path) -> Any:
        real_move(source, target)
        raise KeyboardInterrupt("simulated process death after destination move")

    with (
        patch.object(
            bundle_module,
            "move_directory_noreplace",
            side_effect=interrupt_first_move,
        ),
        pytest.raises(KeyboardInterrupt),
    ):
        archive_bundle(bundle, adopt_archived=True)

    transaction = next(destination.parent.glob(f".tmp-adopt-{destination.name}-*"))
    receipt_path = transaction / "receipt.toml"
    with open(receipt_path, "rb") as stream:
        receipt = tomllib.load(stream)
    receipt["adoption"]["format_version"] = 1
    with open(receipt_path, "wb") as stream:
        tomli_w.dump(receipt, stream)

    result = archive_bundle(bundle, adopt_archived=True)

    assert result.status is ActionStatus.PRECONDITION_FAILED
    assert "Unsupported adoption receipt version" in result.message
    assert bundle.is_dir()
    assert not destination.exists()
    assert (transaction / "adopted").is_dir()
    assert receipt_path.is_file()


def test_archive_bundle_adoption_fails_closed_on_unowned_staged_path(
    tmp_path: Path,
) -> None:
    from runops.application.actions import bundle_archive as bundle_module

    bundle, destination, _current, _adopted = _setup_adoption_bundle(tmp_path)
    real_move = bundle_module.move_directory_noreplace

    def interrupt_first_move(source: Path, target: Path) -> Any:
        real_move(source, target)
        raise KeyboardInterrupt("simulated process death after destination move")

    with (
        patch.object(
            bundle_module,
            "move_directory_noreplace",
            side_effect=interrupt_first_move,
        ),
        pytest.raises(KeyboardInterrupt),
    ):
        archive_bundle(bundle, adopt_archived=True)

    transaction = next(destination.parent.glob(f".tmp-adopt-{destination.name}-*"))
    (transaction / "adopted" / "unowned.txt").write_text(
        "unexpected\n",
        encoding="utf-8",
    )

    result = archive_bundle(bundle, adopt_archived=True)

    assert result.status is ActionStatus.PRECONDITION_FAILED
    assert "unowned path" in result.message
    assert bundle.is_dir()
    assert transaction.is_dir()


def test_archive_bundle_adoption_rejects_manifest_drift_after_receipt(
    tmp_path: Path,
) -> None:
    from runops.application.actions import bundle_archive as bundle_module

    bundle, destination, current, _adopted = _setup_adoption_bundle(tmp_path)
    real_write_toml = bundle_module._write_toml_atomic

    def interrupt_after_receipt(path: Path, data: dict[str, Any]) -> None:
        real_write_toml(path, data)
        if path.name == "receipt.toml":
            raise KeyboardInterrupt("simulated process death after receipt")

    with (
        patch.object(
            bundle_module,
            "_write_toml_atomic",
            side_effect=interrupt_after_receipt,
        ),
        pytest.raises(KeyboardInterrupt, match="after receipt"),
    ):
        archive_bundle(bundle, adopt_archived=True)

    transaction = next(destination.parent.glob(f".tmp-adopt-{destination.name}-*"))
    with open(transaction / "receipt.toml", "rb") as stream:
        receipt = tomllib.load(stream)
    receipt_run = next(
        item for item in receipt["runs"] if item["run_id"] == current.name
    )
    assert receipt["adoption"]["format_version"] == 2
    assert len(receipt_run["manifest_preimage_sha256"]) == 64
    assert len(receipt_run["manifest_postimage_sha256"]) == 64
    assert receipt_run["directory_inode"] > 0
    assert len(receipt_run["tree_identity_sha256"]) == 64

    manifest_path = current / "manifest.toml"
    manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["analysis"] = {"operator_note": "changed after receipt"}
    with open(manifest_path, "wb") as stream:
        tomli_w.dump(manifest, stream)

    result = archive_bundle(bundle, adopt_archived=True)

    assert result.status is ActionStatus.PRECONDITION_FAILED
    assert "manifest" in result.message.lower()
    assert bundle.is_dir()
    assert destination.is_dir()
    assert (transaction / "receipt.toml").is_file()
    assert not (transaction / "adopted").exists()
    assert not (destination / ".runops-archive.toml").exists()


def test_archive_bundle_adoption_rejects_staged_manifest_drift(
    tmp_path: Path,
) -> None:
    from runops.application.actions import bundle_archive as bundle_module

    bundle, destination, _current, adopted = _setup_adoption_bundle(tmp_path)
    real_move = bundle_module.move_directory_noreplace

    def interrupt_after_destination_staged(source: Path, target: Path) -> Any:
        real_move(source, target)
        raise KeyboardInterrupt("simulated process death after destination move")

    with (
        patch.object(
            bundle_module,
            "move_directory_noreplace",
            side_effect=interrupt_after_destination_staged,
        ),
        pytest.raises(KeyboardInterrupt, match="after destination move"),
    ):
        archive_bundle(bundle, adopt_archived=True)

    transaction = next(destination.parent.glob(f".tmp-adopt-{destination.name}-*"))
    staged_run = transaction / "adopted" / adopted.relative_to(destination)
    manifest_path = staged_run / "manifest.toml"
    manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["analysis"] = {"operator_note": "changed while staged"}
    with open(manifest_path, "wb") as stream:
        tomli_w.dump(manifest, stream)

    result = archive_bundle(bundle, adopt_archived=True)

    assert result.status is ActionStatus.PRECONDITION_FAILED
    assert "manifest digest changed" in result.message
    assert bundle.is_dir()
    assert not destination.exists()
    assert staged_run.is_dir()
    assert (transaction / "receipt.toml").is_file()


def test_archive_bundle_adoption_rejects_unknown_run_artifact(
    tmp_path: Path,
) -> None:
    from runops.application.actions import bundle_archive as bundle_module

    bundle, destination, current, _adopted = _setup_adoption_bundle(tmp_path)
    real_move = bundle_module.move_directory_noreplace

    def interrupt_after_destination_staged(source: Path, target: Path) -> Any:
        real_move(source, target)
        raise KeyboardInterrupt("simulated process death after destination move")

    with (
        patch.object(
            bundle_module,
            "move_directory_noreplace",
            side_effect=interrupt_after_destination_staged,
        ),
        pytest.raises(KeyboardInterrupt, match="after destination move"),
    ):
        archive_bundle(bundle, adopt_archived=True)

    unknown = current / "unexpected-after-receipt.bin"
    unknown.write_bytes(b"not owned by the receipt\n")
    transaction = next(destination.parent.glob(f".tmp-adopt-{destination.name}-*"))

    result = archive_bundle(bundle, adopt_archived=True)

    assert result.status is ActionStatus.PRECONDITION_FAILED
    assert "Run tree" in result.message
    assert unknown.is_file()
    assert not destination.exists()
    assert (transaction / "receipt.toml").is_file()
    assert (transaction / "adopted").is_dir()


def test_archive_bundle_adoption_rejects_same_identity_directory_replacement(
    tmp_path: Path,
) -> None:
    from runops.application.actions import bundle_archive as bundle_module

    bundle, destination, current, adopted = _setup_adoption_bundle(tmp_path)
    real_move = bundle_module.move_directory_noreplace
    calls = 0

    def interrupt_after_source_move(source: Path, target: Path) -> Any:
        nonlocal calls
        outcome = real_move(source, target)
        calls += 1
        if calls == 2:
            raise KeyboardInterrupt("simulated process death after source move")
        return outcome

    with (
        patch.object(
            bundle_module,
            "move_directory_noreplace",
            side_effect=interrupt_after_source_move,
        ),
        pytest.raises(KeyboardInterrupt, match="after source move"),
    ):
        archive_bundle(bundle, adopt_archived=True)

    final_current = destination / current.relative_to(bundle)
    original = tmp_path / "replaced-original-run"
    final_current.rename(original)
    _write_manifest(
        final_current,
        {"run": {"id": current.name, "status": "cancelled"}},
    )

    transaction = next(destination.parent.glob(f".tmp-adopt-{destination.name}-*"))
    staged_adopted = transaction / "adopted" / adopted.relative_to(destination)
    result = archive_bundle(bundle, adopt_archived=True)

    assert result.status is ActionStatus.PRECONDITION_FAILED
    assert "identity" in result.message.lower()
    assert final_current.is_dir()
    assert staged_adopted.is_dir()
    assert (transaction / "receipt.toml").is_file()
    assert not (destination / adopted.relative_to(destination)).exists()
    assert not (destination / ".runops-archive.toml").exists()


def test_archive_bundle_adoption_rejects_unknown_source_artifact(
    tmp_path: Path,
) -> None:
    from runops.application.actions import bundle_archive as bundle_module

    bundle, destination, _current, _adopted = _setup_adoption_bundle(tmp_path)
    real_move = bundle_module.move_directory_noreplace

    def interrupt_after_destination_staged(source: Path, target: Path) -> Any:
        real_move(source, target)
        raise KeyboardInterrupt("simulated process death after destination move")

    with (
        patch.object(
            bundle_module,
            "move_directory_noreplace",
            side_effect=interrupt_after_destination_staged,
        ),
        pytest.raises(KeyboardInterrupt, match="after destination move"),
    ):
        archive_bundle(bundle, adopt_archived=True)

    unknown = bundle / "unexpected-after-receipt.bin"
    unknown.write_bytes(b"not owned by the receipt\n")
    transaction = next(destination.parent.glob(f".tmp-adopt-{destination.name}-*"))

    result = archive_bundle(bundle, adopt_archived=True)

    assert result.status is ActionStatus.PRECONDITION_FAILED
    assert "tree" in result.message.lower() or "artifact" in result.message.lower()
    assert unknown.is_file()
    assert not destination.exists()
    assert (transaction / "receipt.toml").is_file()
    assert (transaction / "adopted").is_dir()
