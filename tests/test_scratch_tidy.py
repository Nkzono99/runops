"""Acceptance 2 and tidy kinds."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from runops.project import Project


def _set(project_dir: Path, run_id: str, **run_fields: object) -> None:
    m = Project.open(project_dir).resolve_run(run_id)
    m.run.update(run_fields)
    m.save()


def _ago(days: float) -> str:
    return (datetime.now().astimezone() - timedelta(days=days)).isoformat(timespec="seconds")


def test_scratch_hidden_and_expired(project_dir: Path, cli) -> None:  # type: ignore[no-untyped-def]
    (scratch,) = cli("new", "demo", "--scratch").run_ids()
    (pinned,) = cli("new", "demo", "--scratch").run_ids()
    m = Project.open(project_dir).resolve_run(scratch)
    assert m.run_dir.parent == project_dir / "runs/_scratch"
    assert m.run["expires_at"]
    assert json.loads(cli("list", "--json").out) == []
    assert len(json.loads(cli("list", "--scratch", "--json").out)) == 2

    _set(project_dir, scratch, expires_at=_ago(1))
    _set(project_dir, pinned, expires_at=_ago(1), pinned=True)
    cands = json.loads(cli("tidy", "--json").out)
    assert [(c["kind"], c["target"]) for c in cands] == [("expired-scratch", scratch)]
    assert cli("tidy", "--apply", "-y").code == 0
    assert cli("status", scratch).code == 2
    assert cli("status", pinned).code == 0


def test_stale_failed_and_old_completed(project_dir: Path, cli, fake_slurm) -> None:  # type: ignore[no-untyped-def]
    ids = {}
    for key in ("failed_plain", "failed_why", "completed_old", "completed_new"):
        args = ["new", "demo", "--submit"] + (["--why", "keep"] if key == "failed_why" else [])
        (ids[key],) = cli(*args).run_ids()
        fake_slurm.states[fake_slurm.last_job] = (
            "FAILED" if key.startswith("failed") else "COMPLETED"
        )
    cli("sync")
    _set(project_dir, ids["failed_plain"], created_at=_ago(40))
    _set(project_dir, ids["failed_why"], created_at=_ago(40))
    _set(project_dir, ids["completed_old"], created_at=_ago(100))
    cands = {(c["kind"], c["target"]) for c in json.loads(cli("tidy", "--json").out)}
    assert cands == {
        ("stale-failed", ids["failed_plain"]),
        ("old-completed", ids["completed_old"]),
    }

    # default list hides the old ones, --all shows them
    listed = {r["id"] for r in json.loads(cli("list", "--json").out)}
    assert listed == {ids["completed_new"]}
    assert len(json.loads(cli("list", "--all", "--json").out)) == 4

    assert cli("tidy", "--apply", "--only", "old-completed", "-y").code == 0
    m = Project.open(project_dir).resolve_run(ids["completed_old"])
    assert m.status.value == "archived"
    assert cli("status", ids["failed_plain"]).code == 0


def test_purge_work(project_dir: Path, cli, fake_slurm) -> None:  # type: ignore[no-untyped-def]
    (run_id,) = cli("new", "demo", "--submit").run_ids()
    m = Project.open(project_dir).resolve_run(run_id)
    (m.run_dir / "work/big.dat").write_text("x" * 100)
    res = cli("tidy", "--purge-work", run_id, "-y")
    assert res.code == 2  # not completed
    fake_slurm.states[fake_slurm.last_job] = "COMPLETED"
    cli("sync")
    assert cli("tidy", "--purge-work", run_id, "-y").code == 0
    m = Project.open(project_dir).resolve_run(run_id)
    assert not (m.run_dir / "work/big.dat").exists()
    assert m.data["storage"]["work_purged_at"]


def test_unused_build(project_dir: Path, cli) -> None:  # type: ignore[no-untyped-def]
    build = project_dir / ".runops/build/sim-abc"
    build.mkdir(parents=True)
    cands = json.loads(cli("tidy", "--json").out)
    assert [(c["kind"], c["target"]) for c in cands] == [("unused-build", "sim-abc")]
    cli("tidy", "--apply", "-y")
    assert not build.exists()


def test_list_filters(project_dir: Path, cli) -> None:  # type: ignore[no-untyped-def]
    cli("new", "demo", "--tag", "extra")
    cli("new", "demo")
    assert len(json.loads(cli("list", "--tag", "extra", "--json").out)) == 1
    assert len(json.loads(cli("list", "--case", "demo", "--json").out)) == 2
    assert len(json.loads(cli("list", "--status", "created", "--json").out)) == 2
    assert json.loads(cli("list", "--case", "nope", "--json").out) == []
    assert cli("list", "--status", "bogus").code == 2


def _set_defaults(project_dir: Path, **values: object) -> None:
    cfg = project_dir / "runops.toml"
    text = cfg.read_text()
    for key, value in values.items():
        text = re.sub(rf"(?m)^{key} = .*$", f"{key} = {value}", text)
    cfg.write_text(text)


def test_tidy_thresholds_from_config(project_dir: Path, cli, fake_slurm) -> None:  # type: ignore[no-untyped-def]
    (failed,) = cli("new", "demo", "--submit").run_ids()
    fake_slurm.states[fake_slurm.last_job] = "FAILED"
    (done,) = cli("new", "demo", "--submit").run_ids()
    fake_slurm.states[fake_slurm.last_job] = "COMPLETED"
    cli("sync")
    _set(project_dir, failed, created_at=_ago(10))
    _set(project_dir, done, created_at=_ago(20))
    assert json.loads(cli("tidy", "--json").out) == []  # defaults: 30 / 90 days

    _set_defaults(project_dir, tidy_failed_days=7, tidy_archive_days=14)
    kinds = {(c["kind"], c["target"]) for c in json.loads(cli("tidy", "--json").out)}
    assert kinds == {("stale-failed", failed), ("old-completed", done)}

    _set_defaults(project_dir, tidy_failed_days=30, tidy_archive_days=90)
    kinds = {c["kind"] for c in json.loads(cli("tidy", "--older-than", "5d", "--json").out)}
    assert kinds == {"stale-failed", "old-completed"}


def test_invalid_defaults_rejected(project_dir: Path, cli) -> None:  # type: ignore[no-untyped-def]
    _set_defaults(project_dir, tidy_failed_days=0)
    res = cli("list")
    assert res.code == 2 and "tidy_failed_days" in res.err
    _set_defaults(project_dir, tidy_failed_days=30, label_max_length=4)
    assert cli("list").code == 2


def test_label_max_length_from_config(project_dir: Path, cli) -> None:  # type: ignore[no-untyped-def]
    _set_defaults(project_dir, label_max_length=10)
    (run_id,) = cli("new", "demo", "--set", "a_long_parameter_name=123456").run_ids()
    label = Project.open(project_dir).resolve_run(run_id).label
    assert label == "a_long_par"
