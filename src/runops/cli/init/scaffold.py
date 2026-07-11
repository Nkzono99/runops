"""Scaffold and file-copy helpers for ``runo init`` and ``runo setup``."""

from __future__ import annotations

import importlib.resources
import shutil
from pathlib import Path


def _write_if_missing(path: Path, content: str) -> bool:
    """Write content to path if the file does not already exist.

    Args:
        path: File path to create.
        content: File content to write.

    Returns:
        True if the file was created, False if it already existed.
    """
    if path.exists():
        return False
    path.write_text(content, encoding="utf-8")
    return True


def _mkdir_if_missing(path: Path) -> bool:
    """Create a directory if it does not already exist.

    Args:
        path: Directory path to create.

    Returns:
        True if the directory was created, False if it already existed.
    """
    if path.exists():
        return False
    path.mkdir(parents=True)
    return True


def _create_runops_skeleton(project_dir: Path, created: list[str]) -> None:
    """Create .runops/ skeleton for internal/generated state.

    Args:
        project_dir: Project root directory.
        created: Mutable list to append created items.
    """
    runops_dir = project_dir / ".runops"
    if _mkdir_if_missing(runops_dir):
        created.append(".runops/")
    if _mkdir_if_missing(runops_dir / "insights"):
        created.append(".runops/insights/")
    from runops.templates import load_static

    if _write_if_missing(runops_dir / "facts.toml", load_static("scaffold/facts.toml")):
        created.append(".runops/facts.toml")
    # Knowledge integration directories
    if _mkdir_if_missing(runops_dir / "knowledge"):
        created.append(".runops/knowledge/")
    if _mkdir_if_missing(runops_dir / "knowledge" / "enabled"):
        created.append(".runops/knowledge/enabled/")
    if _mkdir_if_missing(runops_dir / "knowledge" / "candidates"):
        created.append(".runops/knowledge/candidates/")
    if _mkdir_if_missing(runops_dir / "knowledge" / "candidates" / "facts"):
        created.append(".runops/knowledge/candidates/facts/")


def _create_notes_skeleton(project_dir: Path, created: list[str]) -> None:
    """Create the lab-notebook skeleton.

    The lab notebook is a visible human/agent workspace for chronological
    append-only entries, edited via
    ``runo notes append`` or the ``/note`` skill.

    Args:
        project_dir: Project root directory.
        created: Mutable list to append created items.
    """
    notes_dir = project_dir / "notes"
    if _mkdir_if_missing(notes_dir):
        created.append("notes/")
    reports_dir = notes_dir / "reports"
    if _mkdir_if_missing(reports_dir):
        created.append("notes/reports/")
    if _mkdir_if_missing(reports_dir / "archive"):
        created.append("notes/reports/archive/")
    if _mkdir_if_missing(reports_dir / "figures"):
        created.append("notes/reports/figures/")
    if _mkdir_if_missing(notes_dir / "history"):
        created.append("notes/history/")

    from runops.templates import load_static

    readme_path = notes_dir / "README.md"
    if _write_if_missing(readme_path, load_static("scaffold/notes/README.md")):
        created.append("notes/README.md")
    reports_readme_path = reports_dir / "README.md"
    if _write_if_missing(
        reports_readme_path,
        load_static("scaffold/notes/reports/README.md"),
    ):
        created.append("notes/reports/README.md")


def _create_materials_skeleton(project_dir: Path, created: list[str]) -> None:
    """Create the human-facing source-material skeleton."""
    materials_dir = project_dir / "materials"
    if _mkdir_if_missing(materials_dir):
        created.append("materials/")
    for dirname in ("papers", "manuals", "figures", "snippets"):
        if _mkdir_if_missing(materials_dir / dirname):
            created.append(f"materials/{dirname}/")

    from runops.templates import load_static

    readme_path = materials_dir / "README.md"
    if _write_if_missing(readme_path, load_static("scaffold/materials/README.md")):
        created.append("materials/README.md")
    index_path = materials_dir / "index.toml"
    if _write_if_missing(index_path, load_static("scaffold/materials/index.toml")):
        created.append("materials/index.toml")


def _create_research_skeleton(project_dir: Path, created: list[str]) -> None:
    """Create the high-level research decision skeleton."""
    research_dir = project_dir / "research"
    if _mkdir_if_missing(research_dir):
        created.append("research/")
    for dirname in ("proposals", "reviews"):
        if _mkdir_if_missing(research_dir / dirname):
            created.append(f"research/{dirname}/")

    from runops.templates import load_static

    readme_path = research_dir / "README.md"
    if _write_if_missing(readme_path, load_static("scaffold/research/README.md")):
        created.append("research/README.md")
    agenda_path = research_dir / "agenda.md"
    if _write_if_missing(agenda_path, load_static("scaffold/research/agenda.md")):
        created.append("research/agenda.md")
    paper_requests_path = research_dir / "paper_requests.toml"
    if _write_if_missing(
        paper_requests_path,
        load_static("scaffold/research/paper_requests.toml"),
    ):
        created.append("research/paper_requests.toml")
    experiments_path = research_dir / "experiments.toml"
    if _write_if_missing(
        experiments_path,
        load_static("scaffold/research/experiments.toml"),
    ):
        created.append("research/experiments.toml")
    for dirname in ("proposals", "reviews"):
        keep_path = research_dir / dirname / ".gitkeep"
        template_path = f"scaffold/research/{dirname}/.gitkeep"
        if _write_if_missing(keep_path, load_static(template_path)):
            created.append(f"research/{dirname}/.gitkeep")


def _get_data_path() -> Path:
    """Return the path to the package's bundled _data directory.

    Falls back to the repository root when running in editable/dev mode
    where force-include has not been applied.
    """
    pkg_data = Path(str(importlib.resources.files("runops") / "_data"))
    if (pkg_data / "README.md").is_file():
        return pkg_data
    # Dev mode fallback: walk up from this file to the repo root
    repo_root = Path(__file__).resolve().parents[4]
    if (repo_root / "README.md").is_file() and (repo_root / "docs").is_dir():
        return repo_root
    return pkg_data


def _copy_docs(project_dir: Path) -> tuple[list[str], list[str]]:
    """Copy bundled README.md and docs/ into the project directory.

    Returns:
        Tuple of (created_list, skipped_list).
    """
    created: list[str] = []
    skipped: list[str] = []
    data_path = _get_data_path()

    # README.md -> docs/runops-guide.md
    readme_src = data_path / "README.md"
    readme_dst = project_dir / "docs" / "runops-guide.md"
    if readme_dst.exists():
        skipped.append("docs/runops-guide.md")
    elif readme_src.exists():
        readme_dst.parent.mkdir(exist_ok=True)
        shutil.copy2(readme_src, readme_dst)
        created.append("docs/runops-guide.md")

    # docs/*.md
    docs_src = data_path / "docs"
    if docs_src.is_dir():
        docs_dst = project_dir / "docs"
        docs_dst.mkdir(exist_ok=True)
        for src_file in sorted(docs_src.iterdir()):
            if src_file.suffix == ".md":
                dst_file = docs_dst / src_file.name
                rel = f"docs/{src_file.name}"
                if dst_file.exists():
                    skipped.append(rel)
                else:
                    shutil.copy2(src_file, dst_file)
                    created.append(rel)

    return created, skipped
