"""Direct tests for init scaffold helpers."""

from __future__ import annotations

import importlib.resources
from pathlib import Path
from typing import TYPE_CHECKING

from runops.cli.init import scaffold as scaffold_mod

if TYPE_CHECKING:
    import pytest


def test_write_and_mkdir_helpers_are_idempotent(tmp_path: Path) -> None:
    target_dir = tmp_path / "nested" / "dir"
    target_file = tmp_path / "nested" / "file.txt"

    assert scaffold_mod._mkdir_if_missing(target_dir) is True
    assert scaffold_mod._mkdir_if_missing(target_dir) is False

    assert scaffold_mod._write_if_missing(target_file, "first") is True
    assert scaffold_mod._write_if_missing(target_file, "second") is False
    assert target_file.read_text(encoding="utf-8") == "first"


def test_create_scaffolds_populate_expected_project_files(tmp_path: Path) -> None:
    created: list[str] = []

    scaffold_mod._create_runops_skeleton(tmp_path, created)
    scaffold_mod._create_notes_skeleton(tmp_path, created)
    scaffold_mod._create_materials_skeleton(tmp_path, created)
    scaffold_mod._create_research_skeleton(tmp_path, created)

    assert (tmp_path / ".runops" / "facts.toml").is_file()
    assert (tmp_path / ".runops" / "knowledge" / "enabled").is_dir()
    assert (tmp_path / "notes" / "README.md").is_file()
    assert (tmp_path / "materials" / "README.md").is_file()
    assert (tmp_path / "materials" / "index.toml").is_file()
    assert (tmp_path / "research" / "README.md").is_file()
    assert (tmp_path / "research" / "agenda.md").is_file()
    assert (tmp_path / "research" / "proposals" / ".gitkeep").is_file()
    assert (tmp_path / "research" / "reviews" / ".gitkeep").is_file()
    assert "materials/figures/" in created
    assert "research/agenda.md" in created

    created_second: list[str] = []
    scaffold_mod._create_runops_skeleton(tmp_path, created_second)
    scaffold_mod._create_notes_skeleton(tmp_path, created_second)
    scaffold_mod._create_materials_skeleton(tmp_path, created_second)
    scaffold_mod._create_research_skeleton(tmp_path, created_second)
    assert created_second == []


def test_get_data_path_prefers_packaged_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_root = tmp_path / "package-root"
    packaged = package_root / "_data"
    packaged.mkdir(parents=True)
    (packaged / "README.md").write_text("# bundled\n", encoding="utf-8")

    monkeypatch.setattr(
        importlib.resources,
        "files",
        lambda _package: package_root,
    )

    assert scaffold_mod._get_data_path() == packaged


def test_get_data_path_falls_back_to_repo_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_root = tmp_path / "package-root"
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "README.md").write_text("# repo\n", encoding="utf-8")
    (repo_root / "docs").mkdir(parents=True)
    fake_module = repo_root / "src" / "runops" / "cli" / "init" / "scaffold.py"
    fake_module.parent.mkdir(parents=True)
    fake_module.write_text("# stub\n", encoding="utf-8")

    monkeypatch.setattr(
        importlib.resources,
        "files",
        lambda _package: package_root,
    )
    monkeypatch.setattr(scaffold_mod, "__file__", str(fake_module))

    assert scaffold_mod._get_data_path() == repo_root


def test_copy_docs_copies_markdown_and_skips_existing_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = tmp_path / "data"
    docs_root = data_root / "docs"
    docs_root.mkdir(parents=True)
    (data_root / "README.md").write_text("# guide\n", encoding="utf-8")
    (docs_root / "alpha.md").write_text("# alpha\n", encoding="utf-8")
    (docs_root / "beta.txt").write_text("ignore\n", encoding="utf-8")
    (docs_root / "gamma.md").write_text("# gamma\n", encoding="utf-8")

    project_dir = tmp_path / "project"
    existing_docs = project_dir / "docs"
    existing_docs.mkdir(parents=True)
    (existing_docs / "gamma.md").write_text("# existing\n", encoding="utf-8")

    monkeypatch.setattr(scaffold_mod, "_get_data_path", lambda: data_root)

    created, skipped = scaffold_mod._copy_docs(project_dir)

    assert created == ["docs/runops-guide.md", "docs/alpha.md"]
    assert skipped == ["docs/gamma.md"]
    assert (existing_docs / "runops-guide.md").is_file()
    assert (existing_docs / "alpha.md").is_file()
    assert (existing_docs / "gamma.md").read_text(encoding="utf-8") == "# existing\n"
