"""Concurrency contracts for Slurm state synchronization."""

from __future__ import annotations

import contextlib
import json
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from pathlib import Path
from threading import Event
from typing import Any

import pytest
import tomli_w

from runops.application.actions import ActionStatus, execute_action
from runops.application.actions import create_run as create_run_action
from runops.core.manifest import read_manifest, update_manifest
from runops.core.state import RunState
from runops.slurm.query import JobStatus


def _write_manifest(run_dir: Path, data: dict[str, Any]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    with (run_dir / "manifest.toml").open("wb") as stream:
        tomli_w.dump(data, stream)


def _write_project_with_case(project_root: Path) -> None:
    (project_root / "runops.toml").write_text(
        '[project]\nname = "sync-locking"\n',
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
        "ntasks = 1\n"
        'walltime = "00:01:00"\n'
        "\n"
        "[params]\n"
        "nx = 8\n",
        encoding="utf-8",
    )


def _recording_guard(events: list[str], label: str) -> Any:
    @contextlib.contextmanager
    def guard(_path: Path) -> Iterator[None]:
        events.append(f"enter:{label}")
        try:
            yield
        finally:
            events.append(f"exit:{label}")

    return guard


def test_managed_completion_uses_global_admission_lock_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from runops.application import experiments, run_namespace
    from runops.application.execution import submission

    (tmp_path / "runops.toml").write_text(
        '[project]\nname = "sync-lock-order"\n',
        encoding="utf-8",
    )
    run_dir = tmp_path / "runs" / "R20260901-0001"
    _write_manifest(
        run_dir,
        {
            "run": {"id": run_dir.name, "status": "running"},
            "job": {"job_id": "12345"},
        },
    )
    events: list[str] = []
    monkeypatch.setattr(
        experiments,
        "experiment_lock",
        _recording_guard(events, "experiment"),
    )
    monkeypatch.setattr(
        submission,
        "submission_guard",
        _recording_guard(events, "submission"),
    )
    monkeypatch.setattr(
        run_namespace,
        "run_namespace_guard",
        _recording_guard(events, "namespace"),
    )
    monkeypatch.setattr(
        "runops.slurm.query.query_job_status",
        lambda _job_id: JobStatus(
            run_state=RunState.COMPLETED,
            slurm_state="COMPLETED",
        ),
    )

    result = execute_action("sync_run", run_dir=run_dir)

    assert result.status is ActionStatus.SUCCESS
    assert events == [
        "enter:experiment",
        "enter:submission",
        "enter:namespace",
        "exit:namespace",
        "exit:submission",
        "exit:experiment",
    ]


@pytest.mark.parametrize(
    ("concurrent_update", "expected_message", "expected_state"),
    [
        ({"job": {"job_id": "67890"}}, "job_id changed", "running"),
        ({"run": {"status": "cancelled"}}, "Run state changed", "cancelled"),
    ],
)
def test_sync_rejects_manifest_changed_after_scheduler_query(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    concurrent_update: dict[str, dict[str, str]],
    expected_message: str,
    expected_state: str,
) -> None:
    run_dir = tmp_path / "R20260901-0001"
    _write_manifest(
        run_dir,
        {
            "run": {"id": run_dir.name, "status": "running"},
            "job": {"job_id": "12345"},
        },
    )

    def mutate_manifest(_job_id: str) -> JobStatus:
        update_manifest(run_dir, concurrent_update)
        return JobStatus(
            run_state=RunState.COMPLETED,
            slurm_state="COMPLETED",
        )

    monkeypatch.setattr("runops.slurm.query.query_job_status", mutate_manifest)

    result = execute_action("sync_run", run_dir=run_dir)

    assert result.status is ActionStatus.PRECONDITION_FAILED
    assert expected_message in result.message
    assert read_manifest(run_dir).run["status"] == expected_state


def test_sync_completion_waits_for_formal_create_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from runops.application.run_creation import workflow as workflow_module

    _write_project_with_case(tmp_path)
    existing = tmp_path / "runs" / "existing" / "R20260901-0001"
    _write_manifest(
        existing,
        {
            "run": {"id": existing.name, "status": "running"},
            "job": {"job_id": "12345"},
            "curation": {"review_status": "unreviewed"},
        },
    )
    publication_entered = Event()
    release_publication = Event()
    query_entered = Event()
    real_commit = workflow_module.commit_staged_directory

    def blocking_commit(source: Path, destination: Path) -> None:
        publication_entered.set()
        assert release_publication.wait(timeout=5)
        real_commit(source, destination)

    def completed_status(_job_id: str) -> JobStatus:
        query_entered.set()
        return JobStatus(
            run_state=RunState.COMPLETED,
            slurm_state="COMPLETED",
        )

    monkeypatch.setattr(workflow_module, "commit_staged_directory", blocking_commit)
    monkeypatch.setattr("runops.slurm.query.query_job_status", completed_status)

    with ThreadPoolExecutor(max_workers=2) as executor:
        created = executor.submit(create_run_action, tmp_path, "my_case")
        assert publication_entered.wait(timeout=5)
        synced = executor.submit(execute_action, "sync_run", run_dir=existing)
        assert query_entered.wait(timeout=5)
        try:
            with pytest.raises(FutureTimeoutError):
                synced.result(timeout=0.1)
            assert read_manifest(existing).run["status"] == "running"
        finally:
            release_publication.set()

        create_result = created.result(timeout=5)
        sync_result = synced.result(timeout=5)

    assert create_result.status is ActionStatus.SUCCESS
    assert sync_result.status is ActionStatus.SUCCESS
    assert read_manifest(existing).run["status"] == "completed"
    created_dir = Path(str(create_result.data["run_dir"]))
    with (created_dir / "input" / "params.json").open(encoding="utf-8") as stream:
        assert json.load(stream)["nx"] == 8
