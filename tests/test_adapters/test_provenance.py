"""Tests for shared executable provenance collection."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from runops.adapters._provenance import collect_executable_provenance


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _initialize_git_repo(repo: Path) -> str:
    repo.mkdir()
    _git(repo, "init", "--quiet")
    _git(repo, "config", "user.name", "runops tests")
    _git(repo, "config", "user.email", "runops@example.invalid")
    (repo / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "--quiet", "-m", "initial")
    return _git(repo, "rev-parse", "HEAD")


def test_empty_runtime_returns_stable_payload() -> None:
    assert collect_executable_provenance({}) == {
        "resolver_mode": "",
        "executable": "",
        "exe_hash": "",
        "git_commit": "",
        "git_dirty": False,
        "source_repo": "",
        "build_command": "",
        "package_version": "",
    }


def test_runtime_fields_are_preserved() -> None:
    provenance = collect_executable_provenance(
        {
            "resolver_mode": "package",
            "executable": "solver",
            "source_repo": "/src/simulator",
            "build_command": "make build",
            "package_version": "1.2.3",
        }
    )

    assert provenance["resolver_mode"] == "package"
    assert provenance["executable"] == "solver"
    assert provenance["source_repo"] == "/src/simulator"
    assert provenance["build_command"] == "make build"
    assert provenance["package_version"] == "1.2.3"


def test_executable_file_gets_sha256_hash(tmp_path: Path) -> None:
    payload = b"simulator executable\n"
    executable = tmp_path / "solver"
    executable.write_bytes(payload)

    provenance = collect_executable_provenance(
        {
            "resolver_mode": "local_executable",
            "executable": str(executable),
        }
    )

    expected = hashlib.sha256(payload).hexdigest()
    assert provenance["exe_hash"] == f"sha256:{expected}"


def test_non_file_executable_has_empty_hash(tmp_path: Path) -> None:
    executable_dir = tmp_path / "solver"
    executable_dir.mkdir()

    provenance = collect_executable_provenance(
        {
            "resolver_mode": "local_executable",
            "executable": str(executable_dir),
        }
    )

    assert provenance["exe_hash"] == ""


def test_local_source_reports_clean_and_dirty_git_state(tmp_path: Path) -> None:
    repo = tmp_path / "source"
    commit = _initialize_git_repo(repo)
    runtime = {
        "resolver_mode": "local_source",
        "source_repo": str(repo),
        "executable": "solver",
    }

    clean = collect_executable_provenance(runtime)
    assert clean["git_commit"] == commit
    assert clean["git_dirty"] is False

    (repo / "tracked.txt").write_text("dirty\n", encoding="utf-8")
    dirty = collect_executable_provenance(runtime)
    assert dirty["git_commit"] == commit
    assert dirty["git_dirty"] is True


def test_non_local_source_does_not_report_git_state(tmp_path: Path) -> None:
    repo = tmp_path / "source"
    _initialize_git_repo(repo)

    provenance = collect_executable_provenance(
        {
            "resolver_mode": "package",
            "source_repo": str(repo),
            "executable": "solver",
        }
    )

    assert provenance["git_commit"] == ""
    assert provenance["git_dirty"] is False
