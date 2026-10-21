"""Acceptance 1, 3, 5, 6: create -> submit -> sync -> list; discovery; archive."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from runops import __version__
from runops.manifest import Manifest
from runops.project import Project


def _manifest(project_dir: Path, run_id: str) -> Manifest:
    return Project.open(project_dir).resolve_run(run_id)


def test_full_cycle(project_dir: Path, cli, fake_slurm) -> None:  # type: ignore[no-untyped-def]
    res = cli("case", "new", "other", "--simulator", "generic")
    assert res.code == 0, res.err
    assert (project_dir / "cases/other/case.toml").is_file()

    res = cli("new", "demo", "--why", "x", "--set", "x=3")
    assert res.code == 0, res.err
    (run_id,) = res.run_ids()
    m = _manifest(project_dir, run_id)
    assert m.run_dir.parent == project_dir / "runs" / "demo"
    assert (m.run_dir / "input/input.txt").read_text() == "x = 3\nname = a\n"
    assert m.params == {"x": 3, "name": "a"}
    assert m.data["variation"]["changed_keys"] == ["x"]
    assert m.why == "x"
    assert m.tags == ["t1"]
    assert (m.run_dir / "submit/job.sh").is_file()

    res = cli("submit", run_id)
    assert res.code == 0, res.err
    assert fake_slurm.commands[-1][0] == "sbatch"
    assert any(c.startswith("--chdir=") and c.endswith("/work") for c in fake_slurm.commands[-1])
    m = _manifest(project_dir, run_id)
    assert m.status.value == "submitted"
    assert m.job_id == fake_slurm.last_job
    assert m.job["attempts"][0]["job_id"] == fake_slurm.last_job
    assert "Submitted batch job" in (m.run_dir / "submit/sbatch.log").read_text()

    fake_slurm.states[fake_slurm.last_job] = "RUNNING"
    assert cli("sync").code == 0
    assert _manifest(project_dir, run_id).status.value == "running"

    fake_slurm.states[fake_slurm.last_job] = "COMPLETED"
    res = cli("sync", "--json")
    assert json.loads(res.out)[0]["after"] == "completed"
    m = _manifest(project_dir, run_id)
    assert m.status.value == "completed"
    assert m.job["last_slurm_state"] == "COMPLETED"
    assert m.job["finished_at"]

    res = cli("list", "--json")
    rows = json.loads(res.out)
    assert [r["id"] for r in rows] == [run_id]
    assert rows[0]["status"] == "completed"


def test_adapter_failure_overrides_slurm_completed(project_dir: Path, cli, fake_slurm) -> None:  # type: ignore[no-untyped-def]
    cfg = project_dir / "runops.toml"
    cfg.write_text(
        cfg.read_text().replace(
            'command = "./run.sh"', 'command = "./run.sh"\nsuccess_marker = "DONE"'
        )
    )
    (run_id,) = cli("new", "demo", "--submit").run_ids()
    fake_slurm.states[fake_slurm.last_job] = "COMPLETED"
    cli("sync")
    assert _manifest(project_dir, run_id).status.value == "failed"


def test_submit_failure_keeps_created(project_dir: Path, cli, fake_slurm) -> None:  # type: ignore[no-untyped-def]
    (run_id,) = cli("new", "demo").run_ids()
    fake_slurm.fail_sbatch = True
    res = cli("submit", run_id)
    assert res.code == 1
    assert "invalid partition" in res.err
    assert _manifest(project_dir, run_id).status.value == "created"


def test_discovery_after_move(project_dir: Path, cli) -> None:  # type: ignore[no-untyped-def]
    (run_id,) = cli("new", "demo", "--why", "w", "--label", "moved-one").run_ids()
    src = _manifest(project_dir, run_id).run_dir
    dst = project_dir / "runs" / "elsewhere" / "deep" / src.name
    dst.parent.mkdir(parents=True)
    shutil.move(str(src), str(dst))
    res = cli("status", run_id, "--json")
    assert res.code == 0, res.err
    assert json.loads(res.out)[0]["run_dir"] == f"runs/elsewhere/deep/{src.name}"
    assert cli("status", src.name.split("--")[1]).code == 0  # unique fragment


def test_ambiguous_and_missing_refs(project_dir: Path, cli) -> None:  # type: ignore[no-untyped-def]
    cli("new", "demo")
    cli("new", "demo")
    res = cli("status", "R2")
    assert res.code == 2 and "matches 2 runs" in res.err
    assert cli("status", "R19990101-0001").code == 2


def test_archive_restore(project_dir: Path, cli, fake_slurm) -> None:  # type: ignore[no-untyped-def]
    (run_id,) = cli("new", "demo", "--submit").run_ids()
    fake_slurm.states[fake_slurm.last_job] = "COMPLETED"
    cli("sync")
    original = _manifest(project_dir, run_id).run_dir
    rel = original.relative_to(project_dir).as_posix()

    assert cli("archive", run_id, "-y").code == 0
    m = _manifest(project_dir, run_id)
    assert m.status.value == "archived"
    assert m.run_dir == project_dir / "runs/_archive" / original.relative_to(project_dir / "runs")
    assert m.data["path"]["archived_from"] == rel
    assert json.loads(cli("list", "--json").out) == []
    assert len(json.loads(cli("list", "--archived", "--json").out)) == 1

    assert cli("restore", run_id).code == 0
    m = _manifest(project_dir, run_id)
    assert m.status.value == "completed"
    assert m.data["path"]["run_dir"] == rel
    assert m.run_dir == original

    cli("archive", run_id, "-y")
    original.mkdir(parents=True)
    res = cli("restore", run_id)
    assert res.code == 2 and "already exists" in res.err


def test_state_guards(project_dir: Path, cli, fake_slurm) -> None:  # type: ignore[no-untyped-def]
    (run_id,) = cli("new", "demo", "--submit").run_ids()
    res = cli("submit", run_id)
    assert res.code == 1 and "only created runs" in res.err
    res = cli("delete", run_id, "-y")
    assert res.code == 2 and "cancel it first" in res.err  # submitted
    fake_slurm.states[fake_slurm.last_job] = "COMPLETED"
    cli("sync")
    res = cli("delete", run_id, "-y")
    assert res.code == 2 and "archive completed runs instead" in res.err

    (other,) = cli("new", "demo").run_ids()
    cli("pin", other)
    res = cli("delete", other, "-y")
    assert res.code == 2 and "pinned" in res.err
    cli("pin", other, "--off")
    assert cli("delete", other, "-y").code == 0
    assert cli("status", other).code == 2


def test_cancel_retry(project_dir: Path, cli, fake_slurm) -> None:  # type: ignore[no-untyped-def]
    (run_id,) = cli("new", "demo", "--submit").run_ids()
    first = fake_slurm.last_job
    assert cli("cancel", run_id, "-y").code == 0
    assert ["scancel", first] in fake_slurm.commands
    assert _manifest(project_dir, run_id).status.value == "cancelled"
    assert cli("retry", run_id, "--submit").code == 0
    m = _manifest(project_dir, run_id)
    assert m.status.value == "submitted"
    assert m.job["attempt"] == 2
    assert [a["job_id"] for a in m.job["attempts"]] == [first, fake_slurm.last_job]
    assert m.job["attempts"][0]["slurm_state"] == "CANCELLED"


def test_orphan_job_marked_failed(project_dir: Path, cli, fake_slurm) -> None:  # type: ignore[no-untyped-def]
    (run_id,) = cli("new", "demo", "--submit").run_ids()
    fake_slurm.unknown.add(fake_slurm.last_job)
    res = cli("tidy", "--json")
    kinds = [c["kind"] for c in json.loads(res.out)]
    assert kinds == ["orphan-job"]
    cli("tidy", "--apply", "-y")
    assert _manifest(project_dir, run_id).status.value == "failed"


def test_new_from_and_notes(project_dir: Path, cli) -> None:  # type: ignore[no-untyped-def]
    (src,) = cli("new", "demo", "--set", "x=5").run_ids()
    (derived,) = cli("new", "--from", src, "--set", "name=b", "--why", "vary name").run_ids()
    m = _manifest(project_dir, derived)
    assert m.params == {"x": 5, "name": "b"}
    assert m.data["origin"]["parent_run"] == src
    assert (m.run_dir / "input/input.txt").read_text() == "x = 5\nname = b\n"
    assert cli("note", derived, "looks fine").code == 0
    res = cli("list", "--json")
    row = next(r for r in json.loads(res.out) if r["id"] == derived)
    assert row["last_note"] == "looks fine"
    res = cli("new", "--from", src, "--continue")
    assert res.code == 2 and "--continue" in res.err


def test_submit_all_requires_confirmation(project_dir: Path, cli, fake_slurm) -> None:  # type: ignore[no-untyped-def]
    cli("new", "demo")
    cli("new", "demo")
    res = cli("submit", "--all")
    assert res.code == 2 and "--yes" in res.err
    assert cli("submit", "--all", "-y").code == 0
    assert sum(1 for c in fake_slurm.commands if c[0] == "sbatch") == 2


def test_context_and_summarize(project_dir: Path, cli) -> None:  # type: ignore[no-untyped-def]
    (run_id,) = cli("new", "demo", "--why", "ctx").run_ids()
    data = json.loads(cli("context", "--json").out)
    assert data["recent_runs"][0]["id"] == run_id
    assert data["simulators"]["generic"]["adapter"] == "generic"
    res = cli("summarize", run_id)
    assert res.code == 0
    assert (_manifest(project_dir, run_id).run_dir / "analysis/summary.json").is_file()


def test_context_warns_about_stale_runops_skills(project_dir: Path, cli) -> None:  # type: ignore[no-untyped-def]
    assert json.loads(cli("context", "--json").out)["warnings"] == []
    lock = project_dir / ".runops/skills.lock"
    text = lock.read_text()
    lock.write_text(text.replace(f'version = "{__version__}"', 'version = "0.0.1"'))
    data = json.loads(cli("context", "--json").out)
    assert data["warnings"] and "runo update --skills-only" in data["warnings"][0]
    assert "0.0.1" in cli("context").err


def test_cancel_why_guards_retry(project_dir: Path, cli, fake_slurm) -> None:  # type: ignore[no-untyped-def]
    (run_id,) = cli("new", "demo", "--submit").run_ids()
    assert cli("cancel", run_id, "--why", "wrong dt; replaced by new series", "-y").code == 0
    m = _manifest(project_dir, run_id)
    assert m.notes[-1]["text"] == "cancelled: wrong dt; replaced by new series"
    res = cli("retry", run_id)  # not a terminal: confirmation required
    assert res.code == 2 and "wrong dt" in res.err
    assert _manifest(project_dir, run_id).status.value == "cancelled"
    assert cli("retry", run_id, "-y").code == 0
    assert _manifest(project_dir, run_id).status.value == "created"
    # a later cancel without --why does not reuse the old reason
    assert cli("submit", run_id).code == 0
    assert cli("cancel", run_id, "-y").code == 0
    assert cli("retry", run_id).code == 0
