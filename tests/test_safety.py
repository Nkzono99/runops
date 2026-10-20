"""Concurrent and failure paths: duplicate submits, purge without keep rules,
nested runs, id reuse after delete, and `new --from` after the case changed."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from runops.errors import UsageError
from runops.manifest import Manifest
from runops.ops.submit import submit_run
from runops.project import Project


def _manifest(project_dir: Path, run_id: str) -> Manifest:
    return Project.open(project_dir).resolve_run(run_id)


def _sbatch_calls(fake_slurm) -> int:  # type: ignore[no-untyped-def]
    return sum(1 for c in fake_slurm.commands if c[0] == "sbatch")


def test_same_run_twice_submits_once(project_dir: Path, cli, fake_slurm) -> None:  # type: ignore[no-untyped-def]
    (run_id,) = cli("new", "demo").run_ids()
    run_dir = str(_manifest(project_dir, run_id).run_dir)
    res = cli("submit", run_id, run_dir, run_id, "-y")
    assert res.code == 0, res.err
    assert _sbatch_calls(fake_slurm) == 1
    m = _manifest(project_dir, run_id)
    assert [a["job_id"] for a in m.job["attempts"]] == [m.job_id]


def test_stale_manifest_is_reloaded_before_submit(project: Project, cli, fake_slurm) -> None:  # type: ignore[no-untyped-def]
    (run_id,) = cli("new", "demo").run_ids()
    first = project.resolve_run(run_id)
    stale = project.resolve_run(run_id)
    submit_run(project, first, runner=fake_slurm)
    with pytest.raises(UsageError, match="is submitted"):
        submit_run(project, stale, runner=fake_slurm)
    assert _sbatch_calls(fake_slurm) == 1
    assert len(project.resolve_run(run_id).job["attempts"]) == 1


def test_concurrent_submits_sbatch_once(project: Project, cli, fake_slurm) -> None:  # type: ignore[no-untyped-def]
    (run_id,) = cli("new", "demo").run_ids()
    copies = [project.resolve_run(run_id) for _ in range(4)]
    barrier = threading.Barrier(len(copies))
    errors: list[Exception] = []

    def worker(m: Manifest) -> None:
        barrier.wait()
        try:
            submit_run(project, m, runner=fake_slurm)
        except UsageError as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(m,)) for m in copies]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert _sbatch_calls(fake_slurm) == 1
    assert len(errors) == len(copies) - 1


def test_purge_refuses_when_adapter_fails(
    project_dir: Path, cli, fake_slurm, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    (run_id,) = cli("new", "demo", "--submit").run_ids()
    fake_slurm.states[fake_slurm.last_job] = "COMPLETED"
    cli("sync")
    work = _manifest(project_dir, run_id).run_dir / "work"
    (work / "checkpoint.h5").write_text("keep me")
    (work / "big.dat").write_text("x")

    def broken(*_args: object) -> object:
        raise UsageError("adapter 'generic' could not be imported")

    monkeypatch.setattr("runops.ops.tidy.run_sim_context", broken)
    res = cli("tidy", "--purge-work", run_id, "-y")
    assert res.code == 2
    assert "nothing was deleted" in res.err
    assert (work / "checkpoint.h5").exists() and (work / "big.dat").exists()
    assert not _manifest(project_dir, run_id).data["storage"]["work_purged_at"]


def test_sync_reports_setup_failure(project_dir: Path, cli, fake_slurm) -> None:  # type: ignore[no-untyped-def]
    (run_id,) = cli("new", "demo", "--submit").run_ids()
    m = _manifest(project_dir, run_id)
    fake_slurm.unknown.add(m.job_id)
    (m.run_dir / "submit" / f"exit.{m.job_id}").write_text(
        'exit_code = 127\nstarted_at = ""\nfinished_at = ""\nhostname = "n1"\nstage = "setup"\n'
    )
    (result,) = json.loads(cli("sync", "--json").out)
    assert result["after"] == "failed"
    assert "setup failed" in result["message"]
