"""`runo archive` of a replaced series: preflight, skips, and `--superseded-by`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runops.errors import UsageError
from runops.manifest import Manifest
from runops.ops.tidy import archive_runs
from runops.project import Project


def _manifest(project_dir: Path, run_id: str) -> Manifest:
    return Project.open(project_dir).resolve_run(run_id)


def _finish_all(cli, fake_slurm) -> None:  # type: ignore[no-untyped-def]
    for job in fake_slurm.states:
        fake_slurm.states[job] = "COMPLETED"
    cli("sync")


def test_archive_series_records_replacements(project_dir: Path, cli, fake_slurm) -> None:  # type: ignore[no-untyped-def]
    res = cli("sweep", "demo", "--set", "x=1,2", "--label", "old", "--apply", "--submit", "-y")
    old = res.run_ids()
    _finish_all(cli, fake_slurm)
    new = [
        cli(
            "new", "--from", r, "--set", "name=b", "--dest", "demo/fixed", "--why", "fix"
        ).run_ids()[0]
        for r in old
    ]

    res = cli("archive", "runs/demo/old", "--superseded-by", "runs/demo/fixed", "-y")
    assert res.code == 2 and "--superseded-by needs --why" in res.err
    res = cli("archive", "runs/demo/old", "--superseded-by", "demo/fixed", "--why", "bad exe", "-y")
    assert res.code == 0, res.err
    assert f"{old[0]}  completed" in res.out and f"-> {new[0]}" in res.out
    for old_id, new_id in zip(old, new, strict=True):
        m = _manifest(project_dir, old_id)
        assert m.status.value == "archived"
        assert m.superseded_by == [new_id]
        assert m.notes[-1]["text"] == f"superseded by {new_id}: bad exe"
    assert not (project_dir / "runs/demo/old").exists()
    rows = json.loads(cli("list", "--archived", "--all", "--json").out)
    assert {r["id"]: r["superseded_by"] for r in rows if r["id"] in old} == {
        old[0]: [new[0]],
        old[1]: [new[1]],
    }


def test_superseded_by_without_parent_link_records_the_series(
    project_dir: Path, cli, fake_slurm
) -> None:  # type: ignore[no-untyped-def]
    (old,) = cli("new", "demo", "--submit").run_ids()
    _finish_all(cli, fake_slurm)
    a, b = cli("sweep", "demo", "--set", "x=3,4", "--label", "redo", "--apply").run_ids()
    res = cli("archive", old, "--superseded-by", "runs/demo/redo", "--why", "redo", "-y")
    assert res.code == 0, res.err
    assert _manifest(project_dir, old).superseded_by == [a, b]

    res = cli("archive", a, "--superseded-by", a, "--why", "x", "-y")
    assert res.code == 2 and "created" in res.err


def test_archive_checks_every_run_before_moving(project_dir: Path, cli, fake_slurm) -> None:  # type: ignore[no-untyped-def]
    (done,) = cli("new", "demo", "--submit").run_ids()
    _finish_all(cli, fake_slurm)
    (running,) = cli("new", "demo", "--submit").run_ids()
    res = cli("archive", done, running, "-y")
    assert res.code == 2 and f"{running} is submitted" in res.err
    assert _manifest(project_dir, done).status.value == "completed"

    res = cli("archive", done, "--superseded-by", done, "--why", "x", "-y")
    assert res.code == 2 and "must not include" in res.err


def test_archive_series_skips_active_and_pinned(project_dir: Path, cli, fake_slurm) -> None:  # type: ignore[no-untyped-def]
    a, b, c = cli(
        "sweep", "demo", "--set", "x=1,2,3", "--label", "mix", "--apply", "--submit", "-y"
    ).run_ids()
    _finish_all(cli, fake_slurm)
    (pending,) = cli("new", "demo", "--dest", "demo/mix", "--submit").run_ids()
    cli("pin", b, "--reason", "fig. 3")

    res = cli("archive", "runs/demo/mix", "--why", "cleanup", "-y")
    assert res.code == 0, res.err
    assert f"skip {pending}  submitted" in res.out
    assert f"skip {b}  pinned" in res.out
    assert _manifest(project_dir, a).status.value == "archived"
    assert _manifest(project_dir, a).notes[-1]["text"] == "archived: cleanup"
    assert _manifest(project_dir, c).status.value == "archived"
    assert _manifest(project_dir, b).status.value == "completed"
    assert _manifest(project_dir, pending).status.value == "submitted"

    # Naming the pinned run explicitly is the user's choice.
    assert cli("archive", b, "-y").code == 0
    res = cli("archive", "runs/demo/mix", "-y")
    assert res.code == 0 and "nothing to archive" in res.out


def test_archive_runs_rechecks_under_the_lock(project_dir: Path, cli, fake_slurm) -> None:  # type: ignore[no-untyped-def]
    a, b = cli(
        "sweep", "demo", "--set", "x=1,2", "--label", "s", "--apply", "--submit", "-y"
    ).run_ids()
    assert cli("cancel", b, "-y").code == 0
    _finish_all(cli, fake_slurm)
    project = Project.open(project_dir)
    stale = [project.resolve_run(a), project.resolve_run(b)]
    # Between the preview and the move, the cancelled b is retried and resubmitted.
    assert cli("retry", b, "--submit", "-y").code == 0
    with pytest.raises(UsageError, match=f"{b} is submitted"):
        archive_runs(project, stale)
    assert _manifest(project_dir, a).status.value == "completed"
