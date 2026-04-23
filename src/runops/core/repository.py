"""Repository-related utility helpers."""

from __future__ import annotations


def repo_name_from_url(url: str) -> str:
    """Extract a repository directory name from a git URL."""
    stem = url.rsplit("/", 1)[-1].rsplit(":", 1)[-1]
    if stem.endswith(".git"):
        stem = stem[:-4]
    return stem
