"""Filesystem paths for the local knowledge layer."""

from __future__ import annotations

from pathlib import Path

RUNOPS_DIR = ".runops"
INSIGHTS_DIR = "insights"
KNOWLEDGE_DIR = "knowledge"
CANDIDATE_FACTS_DIR = "candidates/facts"
FACTS_FILE = "facts.toml"


def get_runops_dir(project_root: Path) -> Path:
    """Return the .runops directory for a project, creating if needed."""
    directory = project_root / RUNOPS_DIR
    directory.mkdir(exist_ok=True)
    return directory


def get_insights_dir(project_root: Path) -> Path:
    """Return the .runops/insights directory, creating if needed."""
    directory = get_runops_dir(project_root) / INSIGHTS_DIR
    directory.mkdir(exist_ok=True)
    return directory


def get_knowledge_dir(project_root: Path) -> Path:
    """Return the .runops/knowledge directory, creating if needed."""
    directory = get_runops_dir(project_root) / KNOWLEDGE_DIR
    directory.mkdir(exist_ok=True)
    return directory


def get_candidate_facts_dir(project_root: Path) -> Path:
    """Return the candidate fact transport directory, creating if needed."""
    directory = get_knowledge_dir(project_root) / CANDIDATE_FACTS_DIR
    directory.mkdir(parents=True, exist_ok=True)
    return directory
