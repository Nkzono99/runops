"""Progress samples from the adapter's ``progress()`` hook, and the rates derived from them."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from runops.ops.progress import format_progress, summarize
from runops.project import Project

PROGRESS_ADAPTER = """
from pathlib import Path

class Adapter:
    name = "progsim"
    def render_inputs(self, params, run_dir):
        return []
    def build_command(self, runtime, run_dir):
        return ["progsim"]
    def detect_status(self, run_dir):
        return "completed"
    def progress(self, run_dir):
        path = run_dir / "work" / "progress.txt"
        if not path.is_file():
            return None
        done, total, start = path.read_text().split()
        return {"done": int(done), "total": int(total), "unit": "batch", "start": int(start)}
"""


def _project_with_progress(project_dir: Path) -> None:
    (project_dir / "adapters").mkdir()
    (project_dir / "adapters/progsim.py").write_text(PROGRESS_ADAPTER)
    cfg = project_dir / "runops.toml"
    cfg.write_text(
        cfg.read_text()
        + '\n[simulators.progsim]\nadapter = "progsim"\n'
        + 'resolver_mode = "local_executable"\nexecutable = "bin/progsim"\n'
    )
    exe = project_dir / "bin/progsim"
    exe.parent.mkdir()
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    case = project_dir / "cases/prog"
    case.mkdir()
    (case / "case.toml").write_text(
        '[case]\nname = "prog"\nsimulator = "progsim"\n[job]\nwalltime = "10:00:00"\n'
    )


def _at(minutes: float) -> str:
    base = datetime(2026, 10, 23, 12, 0, tzinfo=datetime.now().astimezone().tzinfo)
    return (base + timedelta(minutes=minutes)).isoformat(timespec="seconds")


def test_summarize_counts_from_the_resume_point_and_the_recent_window() -> None:
    samples = [
        {"at": _at(60), "done": 1360},  # 100 batch/min since a resume at 1000 (+ 0.0)
        {"at": _at(80), "done": 3360},
        {"at": _at(90), "done": 3960},  # last 10 min: 60 batch/min
    ]
    start = datetime.fromisoformat(_at(56.4))
    out = summarize(samples, total=10000, unit="batch", start=1000, started_at=start)
    assert out["done"] == 3960 and out["fraction"] == 0.396
    assert out["rate_recent_per_hour"] == 3600.0  # 600 in 10 min
    assert round(out["rate_attempt_per_hour"]) == round(2960 / (33.6 / 60))
    assert out["eta_hours"] == round(6040 / 3600, 2)
    assert format_progress(out) == "40% 1 s/batch eta 1.7h"

    final = summarize(samples, total=10000, unit="batch", start=1000, started_at=start, final=True)
    assert "eta_hours" not in final


def test_summarize_without_start_uses_the_first_sample() -> None:
    samples = [{"at": _at(0), "done": 500}, {"at": _at(30), "done": 800}]
    out = summarize(samples, total=None, unit="step", start=None, started_at=None)
    assert out["rate_attempt_per_hour"] == 600.0
    assert "fraction" not in out and "eta_hours" not in out
    assert format_progress(out).startswith("800 step 6 s/step")


def test_sync_records_samples_and_the_final_rate(project_dir: Path, cli, fake_slurm) -> None:  # type: ignore[no-untyped-def]
    _project_with_progress(project_dir)
    (run_id,) = cli("new", "prog", "--submit", "--why", "p").run_ids()
    job = fake_slurm.last_job
    m = Project.open(project_dir).resolve_run(run_id)
    work = m.run_dir / "work"
    started = (datetime.now().astimezone() - timedelta(hours=1)).isoformat(timespec="seconds")
    (work / f"{job}.out").write_text(f"runops: start {started} on node1\n")
    (work / "progress.txt").write_text("2500 10000 1000\n")
    fake_slurm.states[job] = "RUNNING"

    assert cli("sync").code == 0
    m = Project.open(project_dir).resolve_run(run_id)
    attempt = m.job["attempts"][-1]
    assert attempt["started_at"] == started
    progress = attempt["progress"]
    assert progress["done"] == 2500 and progress["start"] == 1000
    assert 1400 < progress["rate_attempt_per_hour"] < 1600  # 1500 batches in ~1 h
    assert "eta_hours" in progress
    samples = (m.run_dir / f"submit/progress.{job}.jsonl").read_text().splitlines()
    assert json.loads(samples[-1])["done"] == 2500
    assert "25%" in cli("list").out
    assert json.loads(cli("status", run_id, "--json").out)[0]["progress"]["done"] == 2500

    (work / "progress.txt").write_text("10000 10000 1000\n")
    fake_slurm.states[job] = "COMPLETED"
    assert cli("sync").code == 0
    progress = Project.open(project_dir).resolve_run(run_id).job["attempts"][-1]["progress"]
    assert progress["fraction"] == 1.0 and "eta_hours" not in progress


def test_runs_without_progress_hook_are_unchanged(project_dir: Path, cli, fake_slurm) -> None:  # type: ignore[no-untyped-def]
    (run_id,) = cli("new", "demo", "--submit").run_ids()
    fake_slurm.states[fake_slurm.last_job] = "RUNNING"
    assert cli("sync").code == 0
    m = Project.open(project_dir).resolve_run(run_id)
    assert "progress" not in m.job["attempts"][-1]
    assert not list((m.run_dir / "submit").glob("progress.*"))
