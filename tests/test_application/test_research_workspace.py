"""Tests for quantity-bounded research workspace services."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from runops.application.research.workspace import (
    ResearchWorkspaceError,
    append_journal,
    archive_result,
    create_result,
    inspect_workspace,
    migrate_legacy_workspace,
    plan_legacy_migration,
    restore_legacy_workspace,
    restore_result,
    rotate_journal,
)
from runops.core.research.workspace import ResearchBudget


def _scaffold(root: Path) -> None:
    (root / "research" / "journal" / "archive").mkdir(parents=True)
    (root / "research" / "results").mkdir()
    (root / "research" / "archive" / "results").mkdir(parents=True)
    (root / "research" / "CURRENT.md").write_text("# Current\n", encoding="utf-8")
    (root / "research" / "journal" / "active.md").write_text(
        "# Research Journal\n\n",
        encoding="utf-8",
    )


def test_append_rotates_by_character_count_not_date(tmp_path: Path) -> None:
    _scaffold(tmp_path)
    active = tmp_path / "research" / "journal" / "active.md"
    active.write_text("# Research Journal\n\n" + "a" * 70, encoding="utf-8")
    budget = ResearchBudget(journal_segment_chars=100)

    result = append_journal(
        tmp_path,
        title="new observation",
        body="b" * 40,
        budget=budget,
        now=datetime(2026, 7, 15, 3, 4, tzinfo=timezone.utc),
    )

    assert result.rotated_to == tmp_path / "research/journal/archive/J0001.md"
    assert result.rotated_to.read_text(encoding="utf-8").endswith("a" * 70)
    text = active.read_text(encoding="utf-8")
    assert "## 12:04 new observation" in text
    assert text.endswith("b" * 40 + "\n\n")


def test_rotate_journal_is_noop_below_budget_unless_forced(tmp_path: Path) -> None:
    _scaffold(tmp_path)
    budget = ResearchBudget(journal_segment_chars=100)

    assert rotate_journal(tmp_path, budget=budget) is None
    archived = rotate_journal(tmp_path, budget=budget, force=True)

    assert archived == tmp_path / "research/journal/archive/J0001.md"
    assert (tmp_path / "research/journal/active.md").is_file()


def test_inspection_reports_narrative_and_artifact_budget_issues(
    tmp_path: Path,
) -> None:
    _scaffold(tmp_path)
    (tmp_path / "research/CURRENT.md").write_text("x" * 11, encoding="utf-8")
    result_dir = tmp_path / "research/results/R0001-test"
    artifacts = result_dir / "artifacts"
    artifacts.mkdir(parents=True)
    (result_dir / "README.md").write_text("y" * 13, encoding="utf-8")
    (result_dir / "manifest.toml").write_text(
        'schema_version = 1\nid = "R0001-test"\nstatus = "active"\n',
        encoding="utf-8",
    )
    (artifacts / "table.md").write_text("prose", encoding="utf-8")
    (artifacts / "table.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (artifacts / "table.json").write_text("{}\n", encoding="utf-8")
    budget = ResearchBudget(
        current_chars=10,
        result_readme_chars=12,
        result_artifact_files=2,
        result_artifact_bytes=5,
    )

    status = inspect_workspace(tmp_path, budget=budget)
    codes = {issue.code for issue in status.issues}

    assert status.current_chars == 11
    assert status.active_result_count == 1
    assert "current.too_large" in codes
    assert "result.readme_too_large" in codes
    assert "artifact.markdown_forbidden" in codes
    assert "artifact.too_many_files" in codes
    assert "artifact.too_large" in codes
    assert "artifact.duplicate_formats" in codes


def test_create_archive_and_restore_result_without_semantic_judgment(
    tmp_path: Path,
) -> None:
    _scaffold(tmp_path)

    created = create_result(tmp_path, "Dust release")

    assert created.result_id == "R0001-dust-release"
    assert created.path == tmp_path / "research/results/R0001-dust-release"
    assert (created.path / "README.md").is_file()
    assert (created.path / "manifest.toml").is_file()
    assert (created.path / "artifacts").is_dir()

    archived = archive_result(tmp_path, created.result_id)
    assert archived == tmp_path / "research/archive/results/R0001-dust-release"
    assert not created.path.exists()

    restored = restore_result(tmp_path, created.result_id)
    assert restored == created.path
    assert not archived.exists()


def test_result_operations_reject_symlink_roots(tmp_path: Path) -> None:
    _scaffold(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    results = tmp_path / "research/results"
    results.rmdir()
    results.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ResearchWorkspaceError, match="unsafe results directory"):
        create_result(tmp_path, "must stay local")


def test_legacy_migration_is_deterministic_and_reversible(tmp_path: Path) -> None:
    _scaffold(tmp_path)
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes/2026-01-01.md").write_text("important", encoding="utf-8")
    (tmp_path / "analysis/data").mkdir(parents=True)
    (tmp_path / "analysis/data/note.md").write_text("evidence", encoding="utf-8")
    (tmp_path / "analysis/data/table.csv").write_text("a,b\n", encoding="utf-8")
    (tmp_path / ".harnessops").mkdir()
    (tmp_path / ".harnessops/project.toml").write_text("x=1\n", encoding="utf-8")

    planned = plan_legacy_migration(tmp_path)
    assert [item.source.relative_to(tmp_path).as_posix() for item in planned] == [
        "notes",
        ".harnessops",
        "analysis/data/note.md",
    ]

    moved = migrate_legacy_workspace(tmp_path)
    assert moved == planned
    assert not (tmp_path / "notes").exists()
    assert (tmp_path / "analysis/data/table.csv").is_file()
    assert (tmp_path / "research/archive/legacy/notes/2026-01-01.md").is_file()
    assert (tmp_path / "research/archive/legacy/MIGRATION.json").is_file()

    restored = restore_legacy_workspace(tmp_path)
    assert restored == moved
    assert (tmp_path / "notes/2026-01-01.md").read_text(encoding="utf-8") == "important"
    assert (tmp_path / "analysis/data/note.md").read_text(
        encoding="utf-8"
    ) == "evidence"
    assert not (tmp_path / "research/archive/legacy/MIGRATION.json").exists()
