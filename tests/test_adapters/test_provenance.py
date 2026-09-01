"""Tests for shared executable provenance collection."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any

import pytest

from runops.adapters import _provenance as provenance_module
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
        "git_state_observed": False,
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
    assert clean["git_state_observed"] is True

    (repo / "tracked.txt").write_text("dirty\n", encoding="utf-8")
    dirty = collect_executable_provenance(runtime)
    assert dirty["git_commit"] == commit
    assert dirty["git_dirty"] is True
    assert dirty["git_state_observed"] is True


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
    assert provenance["git_state_observed"] is False


@pytest.mark.parametrize("failed_command", ["rev-parse", "status"])
def test_local_source_git_command_failure_is_unobserved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failed_command: str,
) -> None:
    repo = tmp_path / "source"
    repo.mkdir()

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        del kwargs
        if command[1] == failed_command:
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="failed")
        stdout = "a" * 40 + "\n" if command[1] == "rev-parse" else ""
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(provenance_module.subprocess, "run", fake_run)

    provenance = collect_executable_provenance(
        {
            "resolver_mode": "local_source",
            "source_repo": str(repo),
            "executable": "solver",
        }
    )

    assert provenance["git_state_observed"] is False


def test_local_source_missing_git_is_unobserved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "source"
    repo.mkdir()

    def missing_git(
        command: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        del command, kwargs
        raise FileNotFoundError

    monkeypatch.setattr(provenance_module.subprocess, "run", missing_git)

    provenance = collect_executable_provenance(
        {
            "resolver_mode": "local_source",
            "source_repo": str(repo),
            "executable": "solver",
        }
    )

    assert provenance["git_commit"] == ""
    assert provenance["git_dirty"] is False
    assert provenance["git_state_observed"] is False
