"""`runo mv` (rename/move keeping the id), `sweep --names`, and walltime evidence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runops.manifest import Manifest
from runops.project import Project
from runops.util import move_noreplace


def _manifest(project_dir: Path, run_id: str) -> Manifest:
    return Project.open(project_dir).resolve_run(run_id)


def test_mv_renames_and_moves_keeping_identity(project_dir: Path, cli) -> None:  # type: ignore[no-untyped-def]
    res = cli("sweep", "demo", "--set", "x=1,2", "--label", "scan", "--apply")
    first, second = res.run_ids()
    before = _manifest(project_dir, first)
    old_dir = before.run_dir

    res = cli("mv", first, "--dest", "noem", "--label", "wh1", "--why", "shorter path")
    assert res.code == 0, res.err
    m = _manifest(project_dir, first)
    assert m.run_dir == project_dir / "runs/noem" / f"{first}--wh1"
    assert m.label == "wh1"
    assert m.data["path"]["run_dir"] == f"runs/noem/{first}--wh1"
    assert m.sweep == "scan" and m.case == "demo"
    assert m.data["identity"] == before.data["identity"]
    assert m.notes[-1]["text"] == f"moved from runs/demo/scan/{old_dir.name}: shorter path"
    assert str(m.run_dir) in (m.run_dir / "submit/job.sh").read_text()
    assert not old_dir.exists()

    res = cli("mv", second, "--dest", "runs/noem")
    assert res.code == 0, res.err
    assert not (project_dir / "runs/demo/scan").exists()  # emptied parent pruned
    assert _manifest(project_dir, second).run_dir.parent == project_dir / "runs/noem"

    assert cli("mv", first, "--label", "").code == 0
    assert _manifest(project_dir, first).run_dir.name == first


def test_mv_refusals(project_dir: Path, cli, fake_slurm) -> None:  # type: ignore[no-untyped-def]
    (a,) = cli("new", "demo").run_ids()
    (b,) = cli("new", "demo").run_ids()
    assert cli("mv", a).code == 2  # nothing to change
    res = cli("mv", a, b, "--label", "x")
    assert res.code == 2 and "one RUN" in res.err
    res = cli("mv", a, "--dest", str(_manifest(project_dir, b).run_dir))
    assert res.code == 2 and "inside the run" in res.err
    res = cli("mv", a, "--dest", "_archive/x")
    assert res.code == 2
    cli("mv", b, "--label", "same")
    (_manifest(project_dir, b).run_dir.parent / f"{a}--same").mkdir()
    res = cli("mv", a, "--label", "same")
    assert res.code == 2 and "already exists" in res.err

    assert cli("submit", a).code == 0
    res = cli("mv", a, "--dest", "elsewhere")
    assert res.code == 2 and "submitted" in res.err
    fake_slurm.states[fake_slurm.last_job] = "COMPLETED"
    cli("sync")
    assert cli("mv", a, "--dest", "done").code == 0  # terminal runs may move
    cli("archive", a, "-y")
    res = cli("mv", a, "--dest", "back")
    assert res.code == 2 and "restore" in res.err


def test_sweep_names_label_each_point(project_dir: Path, cli) -> None:  # type: ignore[no-untyped-def]
    long_values = "x=[1,2,3],[4,5,6]"
    res = cli("sweep", "demo", "--set", long_values, "--set", "name=a,b", "--json")
    assert json.loads(res.out)["points"][0]["label"] == "x1-2-3_namea"

    args = ["sweep", "demo", "--set", long_values, "--set", "name=a,b", "--names", "x=wh0,wh1"]
    preview = json.loads(cli(*args, "--label", "d5m_T10eV", "--dest", "runs", "--json").out)
    assert [p["label"] for p in preview["points"]] == [
        "wh0_namea",
        "wh0_nameb",
        "wh1_namea",
        "wh1_nameb",
    ]
    assert preview["parent"] == "runs/d5m_T10eV"
    res = cli(*args, "--label", "d5m_T10eV", "--dest", "runs", "--apply")
    assert res.code == 0, res.err
    m = _manifest(project_dir, res.run_ids()[0])
    assert m.run_dir.parent == project_dir / "runs/d5m_T10eV"
    assert m.label == "wh0_namea" and m.params["x"] == [1, 2, 3]

    assert cli("sweep", "demo", "--set", "x=1,2", "--names", "x=a").code == 2
    assert cli("sweep", "demo", "--set", "x=1,2", "--names", "y=a,b").code == 2
    assert cli("sweep", "demo", "--set", "x=1,2", "--names", "x=a,a").code == 2


def test_elapsed_and_timeout_are_reported(project_dir: Path, cli, fake_slurm) -> None:  # type: ignore[no-untyped-def]
    (ok,) = cli("new", "demo", "--submit").run_ids()
    fake_slurm.states[fake_slurm.last_job] = "COMPLETED"
    fake_slurm.elapsed[fake_slurm.last_job] = "00:45:00"
    (slow,) = cli("new", "demo", "--submit").run_ids()
    fake_slurm.states[fake_slurm.last_job] = "TIMEOUT"
    fake_slurm.elapsed[fake_slurm.last_job] = "01:00:02"
    cli("sync")

    rows = {r["id"]: r for r in json.loads(cli("list", "--json").out)}
    assert rows[ok]["elapsed"] == "00:45:00"
    assert rows[ok]["walltime"] == "1:00:00"
    assert rows[ok]["walltime_used"] == 0.75
    assert rows[slow]["status"] == "failed" and rows[slow]["slurm_state"] == "TIMEOUT"
    assert _manifest(project_dir, ok).job["attempts"][-1]["elapsed"] == "00:45:00"
    table = cli("status", ok, slow).out
    assert "00:45:00 (75%)" in table and "failed (TIMEOUT)" in table


def test_elapsed_from_exit_record(project_dir: Path, cli, fake_slurm) -> None:  # type: ignore[no-untyped-def]
    (run_id,) = cli("new", "demo", "--submit").run_ids()
    m = _manifest(project_dir, run_id)
    fake_slurm.unknown.add(m.job_id)
    (m.run_dir / "submit" / f"exit.{m.job_id}").write_text(
        'exit_code = 0\nstarted_at = "2026-10-15T10:00:00+09:00"\n'
        'finished_at = "2026-10-16T11:30:05+09:00"\nhostname = "n1"\nstage = "run"\n'
    )
    cli("sync")
    assert _manifest(project_dir, run_id).job["attempts"][-1]["elapsed"] == "1-01:30:05"


def test_mv_checks_every_run_before_moving(project_dir: Path, cli, fake_slurm) -> None:  # type: ignore[no-untyped-def]
    a, b, c = cli("sweep", "demo", "--set", "x=1,2,3", "--label", "s", "--apply").run_ids()
    before = {r: _manifest(project_dir, r).run_dir for r in (a, b, c)}
    assert cli("submit", b).code == 0
    res = cli("mv", a, b, c, "--dest", "regrouped")
    assert res.code == 2 and f"{b} is submitted" in res.err
    assert {r: _manifest(project_dir, r).run_dir for r in (a, b, c)} == before
    assert not (project_dir / "runs/regrouped").exists()

    (project_dir / "runs/regrouped" / before[c].name).mkdir(parents=True)
    res = cli("mv", a, c, "--dest", "regrouped")
    assert res.code == 2 and "already exists" in res.err
    assert _manifest(project_dir, a).run_dir == before[a]


def test_mv_reports_runs_moved_before_a_failure(
    project_dir: Path,
    cli,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a, b = cli("sweep", "demo", "--set", "x=1,2", "--label", "s", "--apply").run_ids()
    calls: list[Path] = []

    def flaky(src: Path, dst: Path) -> None:
        calls.append(src)
        if len(calls) == 2:
            raise OSError("disk quota exceeded")
        move_noreplace(src, dst)

    monkeypatch.setattr("runops.ops.tidy.move_noreplace", flaky)
    res = cli("mv", a, b, "--dest", "regrouped")
    assert res.code == 1
    assert f"{b}: disk quota exceeded (already moved: {a})" in res.err
    assert _manifest(project_dir, a).run_dir.parent == project_dir / "runs/regrouped"
    assert _manifest(project_dir, b).run_dir.parent == project_dir / "runs/demo/s"
