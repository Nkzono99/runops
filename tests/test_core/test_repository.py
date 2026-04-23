"""Tests for repository URL helpers."""

from __future__ import annotations

from runops.core.repository import repo_name_from_url


def test_repo_name_from_url_supports_common_git_url_forms() -> None:
    assert repo_name_from_url("https://github.com/user/project.git") == "project"
    assert repo_name_from_url("git@github.com:user/project.git") == "project"
    assert repo_name_from_url("ssh://git@example.com/team/project") == "project"
