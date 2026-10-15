"""Scheduler-friendly sync, the job exit record, per-attempt executable hash,
duplicate-input warnings, ``new --json`` and sweep ``--dest`` labels."""

from __future__ import annotations

import json
from pathlib import Path

from runops.manifest import Manifest
from runops.project import Project


def _manifest(project_dir: Path, run_id: str) -> Manifest:
    return Project.open(project_dir).resolve_run(run_id)


def _write_exit_record(m: Manifest, code: int) -> None:
    (m.run_dir / "submit" / f"exit.{m.job_id}").write_text(
        f'exit_code = {code}\nstarted_at = "2026-10-15T10:00:00+09:00"\n'
        'finished_at = "2026-10-15T11:00:00+09:00"\nhostname = "n1"\n'
    )


def test_sync_and_tidy_query_slurm_once(project_dir: Path, cli, fake_slurm) -> None:  # type: ignore[no-untyped-def]
    ids = [cli("new", "demo", "--submit").run_ids()[0] for _ in range(3)]
    fake_slurm.commands.clear()
    assert cli("sync").code == 0
    calls = fake_slurm.scheduler_calls()
    assert [c[0] for c in calls] == ["squeue"]  # all pending: one squeue, no sacct
    assert calls[0][1] == "--jobs=" + ",".join(_manifest(project_dir, i).job_id for i in ids)

    fake_slurm.states[_manifest(project_dir, ids[1]).job_id] = "COMPLETED"
    fake_slurm.commands.clear()
    cli("sync")
    assert [c[0] for c in fake_slurm.scheduler_calls()] == ["squeue", "sacct"]
    assert _manifest(project_dir, ids[1]).status.value == "completed"
    assert _manifest(project_dir, ids[0]).status.value == "submitted"

    fake_slurm.commands.clear()
    cli("tidy", "--json")
    assert [c[0] for c in fake_slurm.scheduler_calls()] == ["squeue"]


def test_exit_record_settles_orphan(project_dir: Path, cli, fake_slurm) -> None:  # type: ignore[no-untyped-def]
    (ok,) = cli("new", "demo", "--submit").run_ids()
    (bad,) = cli("new", "demo", "--submit").run_ids()
    for run_id in (ok, bad):
        fake_slurm.unknown.add(_manifest(project_dir, run_id).job_id)
    _write_exit_record(_manifest(project_dir, ok), 0)
    _write_exit_record(_manifest(project_dir, bad), 3)

    results = {r["run_id"]: r for r in json.loads(cli("sync", "--json").out)}
    assert results[ok]["after"] == "completed" and "exit record" in results[ok]["message"]
    assert results[bad]["after"] == "failed" and "exit=3" in results[bad]["message"]
    m = _manifest(project_dir, ok)
    assert m.job["exit_code"] == "0"
    assert m.job["finished_at"] == "2026-10-15T11:00:00+09:00"
    assert m.job["attempts"][-1]["started_at"] == "2026-10-15T10:00:00+09:00"
    assert m.job["attempts"][-1]["exit_code"] == 0
    assert _manifest(project_dir, bad).job["exit_code"] == "3"


def test_exit_record_zero_still_defers_to_adapter(project_dir: Path, cli, fake_slurm) -> None:  # type: ignore[no-untyped-def]
    cfg = project_dir / "runops.toml"
    cfg.write_text(
        cfg.read_text().replace(
            'command = "./run.sh"', 'command = "./run.sh"\nsuccess_marker = "DONE"'
        )
    )
    (run_id,) = cli("new", "demo", "--submit").run_ids()
    m = _manifest(project_dir, run_id)
    fake_slurm.unknown.add(m.job_id)
    _write_exit_record(m, 0)
    cli("sync")
    assert _manifest(project_dir, run_id).status.value == "failed"  # no work/DONE


def test_exe_hash_recorded_per_attempt(project_dir: Path, cli, fake_slurm) -> None:  # type: ignore[no-untyped-def]
    sim = project_dir / "sim.sh"
    sim.write_text("#!/bin/sh\necho v1\n")
    cfg = project_dir / "runops.toml"
    cfg.write_text(
        cfg.read_text().replace(
            'command = "./run.sh"', 'command = "{executable}"\nexecutable = "./sim.sh"'
        )
    )
    (run_id,) = cli("new", "demo").run_ids()
    created_hash = _manifest(project_dir, run_id).data["simulator"]["exe_hash"]
    assert created_hash.startswith("sha256:")

    res = cli("submit", run_id)
    assert res.code == 0 and "executable changed" not in res.err
    assert _manifest(project_dir, run_id).job["attempts"][0]["exe_hash"] == created_hash

    sim.write_text("#!/bin/sh\necho v2\n")
    assert cli("cancel", run_id, "-y").code == 0
    res = cli("retry", run_id, "--submit")
    assert res.code == 0 and "executable changed" in res.err
    attempts = _manifest(project_dir, run_id).job["attempts"]
    assert attempts[1]["exe_hash"] != created_hash
    assert _manifest(project_dir, run_id).data["simulator"]["exe_hash"] == created_hash


def test_duplicate_inputs_warn_but_create(project_dir: Path, cli) -> None:  # type: ignore[no-untyped-def]
    first = cli("new", "demo", "--set", "x=7")
    assert "same inputs" not in first.err
    (first_id,) = first.run_ids()
    second = cli("new", "demo", "--set", "x=7")
    assert second.code == 0 and second.run_ids()
    assert f"same inputs and executable as {first_id}" in second.err
    assert "same inputs" not in cli("new", "demo", "--set", "x=8").err
    plan = cli("sweep", "demo", "--set", "x=11,12", "--apply")
    assert plan.code == 0 and "same inputs" not in plan.err


def test_new_json_and_sweep_json(project_dir: Path, cli, fake_slurm) -> None:  # type: ignore[no-untyped-def]
    res = cli("new", "demo", "--set", "x=4", "--submit", "--json")
    assert res.code == 0, res.err
    rows = json.loads(res.out)
    assert len(rows) == 1
    assert rows[0]["params"] == {"x": 4, "name": "a"}
    assert rows[0]["changed_keys"] == ["x"]
    assert rows[0]["status"] == "submitted" and rows[0]["job_id"] == fake_slurm.last_job
    assert rows[0]["input_hash"].startswith("sha256:")

    res = cli("sweep", "demo", "--set", "x=1,2", "--apply", "--json")
    rows = json.loads(res.out)
    assert [r["params"]["x"] for r in rows] == [1, 2]
    assert all(r["sweep"] for r in rows)


def test_sweep_label_counter_follows_dest(project: Project) -> None:
    from runops.ops.create import CreateRequest, apply_sweep, plan_sweep

    first = plan_sweep(project, "demo", {"x": [1]}, dest="runs/elsewhere")
    apply_sweep(project, first, CreateRequest(case="demo"))
    second = plan_sweep(project, "demo", {"x": [2]}, dest="runs/elsewhere")
    assert first.parent.parent == project.runs_dir / "elsewhere"
    assert first.sweep_label.endswith("-01") and second.sweep_label.endswith("-02")
