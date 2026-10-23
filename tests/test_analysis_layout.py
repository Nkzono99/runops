"""Analysis placement, log retention, group archival and read-only discovery (§9.1)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from runops.errors import UsageError
from runops.manifest import Manifest
from runops.ops.tidy import apply_candidates, archive_runs, find_candidates, plan_archive
from runops.project import Project


def _pair(directory: Path, job: int, days: float, name: str = "plot") -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    paths = [directory / f"{name}.{job}.{suffix}" for suffix in ("out", "err")]
    stamp = time.time() - days * 86400
    for path in paths:
        path.write_text("job log\n")
        os.utime(path, (stamp, stamp))
    return paths


def _run(project_dir: Path, cli, dest: str = "demo/series", status: str = "completed") -> Manifest:  # type: ignore[no-untyped-def]
    (run_id,) = cli("new", "demo", "--dest", dest).run_ids()
    manifest = Project.open(project_dir).resolve_run(run_id)
    manifest.run["status"] = status
    manifest.save()
    return manifest


def _topic(group: Path, name: str = "speed") -> Path:
    topic = group / "_analysis" / name
    topic.mkdir(parents=True)
    (topic / "README.md").write_text("# Result\nContents stay out of context.\n")
    (topic / "out").mkdir()
    (topic / "out/data.json").write_text('{"value": 42}\n')
    return topic


@pytest.mark.parametrize("scope", ["project", "group", "run", "run-topic"])
def test_analysis_logs_preview_apply_and_retention(project_dir: Path, cli, scope: str) -> None:  # type: ignore[no-untyped-def]
    run = _run(project_dir, cli)
    roots = {
        "project": project_dir / "analysis/speed",
        "group": run.run_dir.parent / "_analysis/speed",
        "run": run.run_dir / "analysis",
        "run-topic": run.run_dir / "analysis/speed",
    }
    root = roots[scope]
    logs = root / "logs"
    old = _pair(logs, 101, 50)
    newest = _pair(logs, 102, 40)  # even the latest old pair must survive
    single = _pair(logs, 103, 50, "other")
    recent = _pair(logs, 104, 2, "other")
    keep = root / "README.md"
    keep.write_text("findings")
    (logs / "important.txt").write_text("keep")
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}

    result = cli("tidy", "--only", "analysis-logs", "--json")
    assert result.code == 0, result.err
    candidates = json.loads(result.out)
    assert {f for c in candidates for f in c["files"]} == {
        p.relative_to(project_dir).as_posix() for p in old + single
    }
    assert all(p.read_bytes() == content for p, content in before.items())
    result = cli("tidy", "--apply", "--only", "analysis-logs", "-y")
    assert result.code == 0, result.err
    assert all(not p.exists() for p in old + single)
    assert all(p.exists() for p in newest + recent)
    assert keep.read_text() == "findings" and (logs / "important.txt").is_file()


def test_log_pair_uses_newer_member_and_configured_age(project_dir: Path, cli) -> None:  # type: ignore[no-untyped-def]
    logs = project_dir / "analysis/topic/logs"
    old = _pair(logs, 101, 10)
    _pair(logs, 102, 1)
    assert json.loads(cli("tidy", "--only", "analysis-logs", "--json").out) == []
    config = project_dir / "runops.toml"
    config.write_text(config.read_text().replace("tidy_failed_days = 30", "tidy_failed_days = 7"))
    assert len(json.loads(cli("tidy", "--only", "analysis-logs", "--json").out)) == 1
    assert json.loads(cli("tidy", "--older-than", "20d", "--json").out) == []
    os.utime(old[1], None)  # recently written stderr protects both members
    assert json.loads(cli("tidy", "--only", "analysis-logs", "--json").out) == []


def test_log_pairs_keep_newest_on_tied_mtime_and_allow_missing_stderr(
    project_dir: Path, cli
) -> None:  # type: ignore[no-untyped-def]
    logs = project_dir / "analysis/topic/logs"
    old = _pair(logs, 9, 40)
    new = _pair(logs, 10, 40)
    stamp = old[0].stat().st_mtime
    for path in old + new:
        os.utime(path, (stamp, stamp))
    old[1].unlink()
    result = cli("tidy", "--only", "analysis-logs", "--apply", "-y")
    assert result.code == 0, result.err
    assert not old[0].exists() and all(p.exists() for p in new)


@pytest.mark.parametrize("protected", ["pinned", "archived", "submitted", "running"])
def test_tidy_preserves_protected_runs(project_dir: Path, cli, protected: str) -> None:  # type: ignore[no-untyped-def]
    run = _run(project_dir, cli)
    if protected == "pinned":
        run.run["pinned"] = True
    else:
        run.run["status"] = protected
    run.save()
    old = _pair(run.run_dir / "analysis/logs", 101, 50)
    _pair(run.run_dir / "analysis/logs", 102, 40)
    assert json.loads(cli("tidy", "--only", "analysis-logs", "--json").out) == []
    assert all(p.exists() for p in old)


def test_tidy_ignores_symlinks_and_files_outside_analysis(project_dir: Path, cli) -> None:  # type: ignore[no-untyped-def]
    run = _run(project_dir, cli)
    for root in (
        project_dir / "logs",
        run.run_dir / "work/logs",
        project_dir / "runs/_archive/a/_analysis/t/logs",
    ):
        _pair(root, 101, 50)
        _pair(root, 102, 40)
    analysis = project_dir / "analysis/topic"
    analysis.mkdir(parents=True)
    (analysis / "logs").symlink_to(project_dir / "logs", target_is_directory=True)
    assert json.loads(cli("tidy", "--only", "analysis-logs", "--json").out) == []
    (analysis / "logs").unlink()
    (analysis / "logs").mkdir()
    (analysis / "logs/plot.101.out").symlink_to(project_dir / "logs/plot.101.out")
    _pair(analysis / "logs", 102, 40)
    assert json.loads(cli("tidy", "--only", "analysis-logs", "--json").out) == []


@pytest.mark.parametrize("change", ["touch", "pin", "symlink", "remove-newest"])
def test_tidy_rechecks_log_candidates_before_deleting(project_dir: Path, cli, change: str) -> None:  # type: ignore[no-untyped-def]
    run = _run(project_dir, cli)
    logs = run.run_dir / "analysis/logs"
    old = _pair(logs, 101, 50)
    new = _pair(logs, 102, 40)
    project = Project.open(project_dir)
    candidates = [
        c for c in find_candidates(project, check_slurm=False) if c.kind == "analysis-logs"
    ]
    assert len(candidates) == 1
    if change == "touch":
        os.utime(old[1], None)
    elif change == "pin":
        run.run["pinned"] = True
        run.save()
    elif change == "symlink":
        logs.rename(logs.with_name("saved-logs"))
        logs.symlink_to(logs.with_name("saved-logs"), target_is_directory=True)
    else:
        for path in new:
            path.unlink()
    report = apply_candidates(project, candidates)
    assert report.errors and not report.applied
    assert all(p.exists() for p in old)


def test_whole_group_archive_moves_analysis_and_context_topics(project_dir: Path, cli) -> None:  # type: ignore[no-untyped-def]
    a = _run(project_dir, cli)
    b = _run(project_dir, cli)
    topic = _topic(a.run_dir.parent)
    data = json.loads(cli("context", "--json").out)
    assert data["group_analysis"] == {"runs/demo/series": ["speed"]}
    assert "runs/demo/series/_analysis/: speed" in cli("context").out
    result = cli("archive", "demo/series", "-y")
    assert result.code == 0, result.err
    assert "analysis runs/demo/series/_analysis" in result.out
    archived = project_dir / "runs/_archive/demo/series/_analysis/speed"
    assert (archived / "out/data.json").read_text() == '{"value": 42}\n'
    assert not topic.exists()
    assert not a.run_dir.parent.exists()
    project = Project.open(project_dir)
    assert all(project.resolve_run(m.id).status.value == "archived" for m in (a, b))
    assert json.loads(cli("context", "--json").out)["group_analysis"] == {}
    assert cli("restore", a.id).code == 0
    assert archived.is_dir()  # restore RUN does not move shared results


@pytest.mark.parametrize("remaining", ["pinned", "created", "submitted", "running"])
def test_partial_archive_leaves_shared_analysis(project_dir: Path, cli, remaining: str) -> None:  # type: ignore[no-untyped-def]
    a = _run(project_dir, cli)
    b = _run(project_dir, cli, status="completed" if remaining == "pinned" else remaining)
    if remaining == "pinned":
        b.run["pinned"] = True
        b.save()
    topic = _topic(a.run_dir.parent)
    result = cli("archive", "demo/series", "-y")
    assert result.code == 0, result.err
    assert topic.is_dir() and b.run_dir.is_dir()


def test_archive_analysis_collision_preflights_before_any_move(project_dir: Path, cli) -> None:  # type: ignore[no-untyped-def]
    run = _run(project_dir, cli)
    topic = _topic(run.run_dir.parent)
    target = project_dir / "runs/_archive/demo/series/_analysis"
    target.mkdir(parents=True)
    (target / "keep.txt").write_text("existing")
    result = cli("archive", "demo/series", "-y")
    assert result.code == 2 and "already exists" in result.err
    assert run.run_dir.is_dir() and topic.is_dir()
    assert (target / "keep.txt").read_text() == "existing"


def test_archive_rechecks_new_group_member(project_dir: Path, cli) -> None:  # type: ignore[no-untyped-def]
    run = _run(project_dir, cli)
    topic = _topic(run.run_dir.parent)
    project = Project.open(project_dir)
    plan = plan_archive(project, ["demo/series"])
    _run(project_dir, cli, status="created")
    with pytest.raises(UsageError, match="still has runs"):
        archive_runs(project, plan.targets, analysis_dirs=plan.analysis_dirs)
    assert run.run_dir.is_dir() and topic.is_dir()


def test_archive_nested_groups_and_explicit_runs(project_dir: Path, cli) -> None:  # type: ignore[no-untyped-def]
    a = _run(project_dir, cli)
    b = _run(project_dir, cli, dest="demo/series/sub")
    parent = _topic(a.run_dir.parent)
    nested = _topic(b.run_dir.parent)
    assert cli("archive", a.id, "-y").code == 0
    assert parent.is_dir() and nested.is_dir()
    assert cli("archive", "demo/series", "demo/series/sub", "-y").code == 0
    assert not parent.exists() and not nested.exists()
    for suffix in ("_analysis/speed", "sub/_analysis/speed"):
        assert (project_dir / "runs/_archive/demo/series" / suffix / "README.md").is_file()


def test_context_reads_names_and_discovery_ignores_analysis_manifests(
    project_dir: Path, cli
) -> None:  # type: ignore[no-untyped-def]
    run = _run(project_dir, cli)
    topic = _topic(run.run_dir.parent)
    copy = Manifest.load(run.path)
    copy.run["id"] = "R20000101-9999"
    (topic / "manifest.toml").write_text(run.path.read_text().replace(run.id, copy.id))
    project = Project.open(project_dir)
    project.update_index(copy.id, topic)
    assert {m.id for m in project.iter_runs()} == {run.id}
    assert cli("status", copy.id).code == 2
    assert cli("status", str(topic)).code == 2
    assert cli("new", "demo", "--dest", "demo/series/_analysis/speed").code == 2
    (topic.parent / "unfinished").mkdir()
    (topic.parent / "linked").symlink_to(topic, target_is_directory=True)
    _topic(run.run_dir / "work")
    result = cli("context", "--json")
    assert json.loads(result.out)["group_analysis"] == {"runs/demo/series": ["speed"]}
    assert "Contents stay out" not in result.out


def test_analysis_skill_and_ignore_template_are_deployed(project_dir: Path, cli) -> None:  # type: ignore[no-untyped-def]
    for base in (".agents/skills", ".claude/skills"):
        assert (project_dir / base / "runops-analyze/SKILL.md").is_file()
    ignore = (project_dir / ".gitignore").read_text()
    assert all(
        pattern in ignore for pattern in ("**/logs/", "__pycache__/", ".runops/analysis-env/")
    )
    assert "Notes and analysis" in (project_dir / "AGENTS.md").read_text()
    assert cli("update", "--skills-only").code == 0


@pytest.mark.parametrize("status", ["completed", "failed"])
def test_tidy_handles_logs_before_moving_or_deleting_their_run(
    project_dir: Path, cli, status: str
) -> None:  # type: ignore[no-untyped-def]
    run = _run(project_dir, cli, status=status)
    run.run["created_at"] = "2000-01-01T00:00:00+00:00"
    run.save()
    _pair(run.run_dir / "analysis/logs", 101, 50)
    _pair(run.run_dir / "analysis/logs", 102, 40)
    result = cli("tidy", "--apply", "-y")
    assert result.code == 0, result.err
    if status == "completed":
        moved = Project.open(project_dir).resolve_run(run.id)
        assert moved.status.value == "archived"
        assert (moved.run_dir / "analysis/logs/plot.102.out").is_file()
        assert not (moved.run_dir / "analysis/logs/plot.101.out").exists()
    else:
        assert not run.run_dir.exists()


@pytest.mark.parametrize("conflict", ["symlink", "parent-file", "source-link"])
def test_archive_analysis_refuses_unsafe_paths_before_run_moves(
    project_dir: Path, cli, conflict: str
) -> None:  # type: ignore[no-untyped-def]
    run = _run(project_dir, cli)
    topic = _topic(run.run_dir.parent)
    project = Project.open(project_dir)
    plan = plan_archive(project, ["demo/series"])
    target = project_dir / "runs/_archive/demo/series/_analysis"
    if conflict == "symlink":
        target.parent.mkdir(parents=True)
        target.symlink_to(project_dir / "missing", target_is_directory=True)
    elif conflict == "parent-file":
        target.parent.parent.mkdir(parents=True)
        target.parent.write_text("existing file")
    else:
        topic.parent.rename(topic.parent.with_name("saved-analysis"))
        topic.parent.symlink_to(topic.parent.with_name("saved-analysis"), target_is_directory=True)
    with pytest.raises(UsageError):
        archive_runs(project, plan.targets, analysis_dirs=plan.analysis_dirs)
    assert run.run_dir.is_dir() and topic.is_dir()
