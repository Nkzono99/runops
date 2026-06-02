"""Tests for GitHub auth preflight during runops init."""

from __future__ import annotations

import subprocess
from typing import Any

import pytest
import typer

from runops.cli.init.github_auth import ensure_github_auth_for_simulators


def test_github_auth_login_runs_when_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--gh-auth-login runs gh auth login and rechecks status."""
    monkeypatch.setattr(
        "runops.cli.init.github_auth.collect_pip_packages",
        lambda _sim_names: [
            "MPIEMSES3D @ git+https://github.com/CS12-Laboratory/MPIEMSES3D.git"
        ],
    )
    monkeypatch.setattr(
        "runops.cli.init.github_auth.collect_doc_repos",
        lambda _sim_names: (_ for _ in ()).throw(
            AssertionError("refs should not be inspected by default")
        ),
    )
    monkeypatch.setattr("runops.cli.init.github_auth.shutil.which", lambda _cmd: "gh")

    calls: list[list[str]] = []

    def _run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[:3] == ["gh", "auth", "status"]:
            return subprocess.CompletedProcess(args, 1 if len(calls) == 1 else 0)
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr("runops.cli.init.github_auth.subprocess.run", _run)

    ensure_github_auth_for_simulators(
        ["emses"],
        interactive=False,
        login=True,
        skip=False,
    )

    assert ["gh", "auth", "login", "--hostname", "github.com"] in calls


def test_github_auth_checks_refs_only_when_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """include_refs adds optional refs mirrors to the GitHub preflight."""
    monkeypatch.setattr(
        "runops.cli.init.github_auth.collect_pip_packages",
        lambda _sim_names: [],
    )
    monkeypatch.setattr(
        "runops.cli.init.github_auth.collect_doc_repos",
        lambda _sim_names: [("https://github.com/example/docs.git", "docs")],
    )
    monkeypatch.setattr("runops.cli.init.github_auth.shutil.which", lambda _cmd: "gh")

    calls: list[list[str]] = []

    def _run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr("runops.cli.init.github_auth.subprocess.run", _run)

    ensure_github_auth_for_simulators(
        ["emses"],
        interactive=False,
        login=False,
        skip=False,
        include_refs=True,
    )

    assert ["gh", "auth", "status", "--hostname", "github.com"] in calls


def test_github_auth_missing_gh_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing GitHub CLI fails before init writes project files."""
    monkeypatch.setattr(
        "runops.cli.init.github_auth.collect_pip_packages",
        lambda _sim_names: [
            "MPIEMSES3D @ git+https://github.com/CS12-Laboratory/MPIEMSES3D.git"
        ],
    )
    monkeypatch.setattr("runops.cli.init.github_auth.shutil.which", lambda _cmd: None)

    with pytest.raises(typer.Exit):
        ensure_github_auth_for_simulators(
            ["emses"],
            interactive=False,
            login=False,
            skip=False,
        )


def test_github_auth_skip_does_not_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Skipping auth avoids gh probing entirely."""

    def _fail_collect_packages(_sim_names: list[str]) -> list[str]:
        raise AssertionError("should not inspect repositories")

    def _fail_collect_repos(_sim_names: list[str]) -> list[tuple[str, str]]:
        raise AssertionError("should not inspect repositories")

    monkeypatch.setattr(
        "runops.cli.init.github_auth.collect_pip_packages",
        _fail_collect_packages,
    )
    monkeypatch.setattr(
        "runops.cli.init.github_auth.collect_doc_repos",
        _fail_collect_repos,
    )

    ensure_github_auth_for_simulators(
        ["emses"],
        interactive=False,
        login=False,
        skip=True,
    )
