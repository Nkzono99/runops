"""Acceptance 8b: local_source build cache."""

from __future__ import annotations

import subprocess
from pathlib import Path

from runops.project import Project


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "simsrc"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "main.sh").write_text("#!/bin/sh\necho sim\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def test_local_source_build_once(project_dir: Path, tmp_path: Path, cli) -> None:  # type: ignore[no-untyped-def]
    repo = _make_repo(tmp_path)
    counter = tmp_path / "builds.txt"
    cfg = project_dir / "runops.toml"
    cfg.write_text(
        cfg.read_text()
        + f"""
[simulators.mysim]
adapter = "generic"
resolver_mode = "local_source"
source_repo = "{repo}"
executable = "bin/sim"
build_command = "echo built >> {counter} && mkdir -p bin && cp main.sh bin/sim && chmod +x bin/sim"
command = "{{executable}} --flag"
"""
    )
    case = project_dir / "cases/srccase"
    case.mkdir()
    (case / "case.toml").write_text('[case]\nsimulator = "mysim"\n[job]\nwalltime = "0:10:00"\n')

    (first,) = cli("new", "srccase").run_ids()
    commit = _git(repo, "rev-parse", "HEAD")
    build = project_dir / f".runops/build/mysim-{commit[:12]}"
    assert (build / "bin/sim").is_file()
    m = Project.open(project_dir).resolve_run(first)
    sim = m.section("simulator")
    assert sim["git_commit"] == commit
    assert sim["git_dirty"] is False
    assert sim["exe_hash"].startswith("sha256:")
    assert sim["executable"] == str(build / "bin/sim")
    assert f"{build}/bin/sim --flag" in (m.run_dir / "submit/job.sh").read_text()

    cli("new", "srccase")
    assert counter.read_text().count("built") == 1

    (repo / "main.sh").write_text("#!/bin/sh\necho changed\n")
    cli("new", "srccase")
    assert counter.read_text().count("built") == 2
    dirty = [p.name for p in (project_dir / ".runops/build").iterdir() if "dirty" in p.name]
    assert len(dirty) == 1

    assert cli("build", "mysim", "--force").code == 0
    assert counter.read_text().count("built") == 3


def test_build_failure_reports_log(project_dir: Path, tmp_path: Path, cli) -> None:  # type: ignore[no-untyped-def]
    repo = _make_repo(tmp_path)
    cfg = project_dir / "runops.toml"
    cfg.write_text(
        cfg.read_text()
        + f"""
[simulators.broken]
adapter = "generic"
resolver_mode = "local_source"
source_repo = "{repo}"
executable = "bin/sim"
build_command = "echo compile error >&2; exit 3"
"""
    )
    res = cli("build", "broken")
    assert res.code == 1
    assert "compile error" in res.err
    assert not any(
        p for p in (project_dir / ".runops/build").iterdir() if not p.name.startswith(".")
    )
