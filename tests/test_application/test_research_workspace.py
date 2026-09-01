"""Tests for quantity-bounded research workspace services."""

from __future__ import annotations

import json
import multiprocessing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from runops.application.research import workspace as workspace_module
from runops.application.research.workspace import (
    ResearchWorkspaceError,
    append_journal,
    archive_result,
    create_result,
    inspect_result_workspace,
    inspect_workspace,
    migrate_legacy_workspace,
    plan_legacy_migration,
    restore_legacy_workspace,
    restore_result,
    rotate_journal,
)
from runops.core.research.workspace import ResearchBudget


def _hold_research_workspace_lock(
    root: str,
    acquired: Any,
    release: Any,
) -> None:
    with workspace_module._research_workspace_lock(Path(root)):
        acquired.set()
        if not release.wait(10):
            raise RuntimeError("timed out waiting to release research workspace lock")


def _run_journal_mutation(
    root: str,
    action: str,
    started: Any,
    done: Any,
) -> None:
    started.set()
    if action == "append":
        append_journal(Path(root), title="concurrent", body="entry")
    else:
        rotate_journal(Path(root), force=True)
    done.set()


def _scaffold(root: Path) -> None:
    (root / "research" / "journal" / "archive").mkdir(parents=True)
    (root / "research" / "results").mkdir()
    (root / "research" / "archive" / "results").mkdir(parents=True)
    (root / "research" / "CURRENT.md").write_text("# Current\n", encoding="utf-8")
    (root / "research" / "journal" / "active.md").write_text(
        "# Research Journal\n\n",
        encoding="utf-8",
    )


def _install_result_destination_race(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_move = workspace_module.move_path_noreplace

    def race(source: Path, destination: Path) -> None:
        destination.mkdir()
        (destination / "competitor.txt").write_text("keep", encoding="utf-8")
        real_move(source, destination)

    monkeypatch.setattr(workspace_module, "move_path_noreplace", race)


def test_append_rotates_by_character_count_not_date(tmp_path: Path) -> None:
    _scaffold(tmp_path)
    active = tmp_path / "research" / "journal" / "active.md"
    active.write_text("# Research Journal\n\n" + "a" * 70, encoding="utf-8")
    budget = ResearchBudget(journal_segment_chars=120)

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
    assert "## 2026-07-15T12:04:00+09:00 new observation" in text
    assert text.endswith("b" * 40 + "\n\n")


def test_append_journal_records_optional_kind_and_subject(tmp_path: Path) -> None:
    _scaffold(tmp_path)

    append_journal(
        tmp_path,
        title="Pilot review",
        body="Proceed with the selected points.",
        kind="decision",
        subject="E20260801-dust-release",
        now=datetime(2026, 8, 1, 0, 2, 3, tzinfo=timezone.utc),
    )

    text = (tmp_path / "research/journal/active.md").read_text(encoding="utf-8")
    assert "## 2026-08-01T09:02:03+09:00 Pilot review" in text
    assert "- Kind: `decision`" in text
    assert "- Subject: `E20260801-dust-release`" in text


def test_rotate_journal_is_noop_below_budget_unless_forced(tmp_path: Path) -> None:
    _scaffold(tmp_path)
    budget = ResearchBudget(journal_segment_chars=100)

    assert rotate_journal(tmp_path, budget=budget) is None
    archived = rotate_journal(tmp_path, budget=budget, force=True)

    assert archived == tmp_path / "research/journal/archive/J0001.md"
    assert (tmp_path / "research/journal/active.md").is_file()


@pytest.mark.parametrize("action", ["append", "rotate"])
def test_journal_mutations_wait_for_the_persistent_workspace_lock(
    tmp_path: Path,
    action: str,
) -> None:
    _scaffold(tmp_path)
    context = multiprocessing.get_context("fork")
    acquired = context.Event()
    release = context.Event()
    started = context.Event()
    done = context.Event()
    holder = context.Process(
        target=_hold_research_workspace_lock,
        args=(str(tmp_path), acquired, release),
    )
    mutation = context.Process(
        target=_run_journal_mutation,
        args=(str(tmp_path), action, started, done),
    )
    try:
        holder.start()
        assert acquired.wait(5)
        mutation.start()
        assert started.wait(5)
        assert not done.wait(0.25)
        release.set()
        assert done.wait(5)
        holder.join(5)
        mutation.join(5)
        assert holder.exitcode == 0
        assert mutation.exitcode == 0
    finally:
        release.set()
        for process in (holder, mutation):
            if process.pid is None:
                continue
            if process.is_alive():
                process.terminate()
            process.join(5)


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
    result_status = inspect_result_workspace(
        tmp_path,
        result_dir,
        budget=budget,
    )
    codes = {issue.code for issue in status.issues}
    result_codes = {issue.code for issue in result_status.issues}

    assert status.current_chars == 11
    assert status.active_result_count == 1
    assert "current.too_large" in codes
    assert "result.readme_too_large" in codes
    assert "artifact.markdown_forbidden" in codes
    assert "artifact.too_many_files" in codes
    assert "artifact.too_large" in codes
    assert "artifact.duplicate_formats" in codes
    assert result_status.readme_chars == 13
    assert result_status.artifact_files == 3
    assert result_status.artifact_bytes == sum(
        path.stat().st_size for path in artifacts.iterdir()
    )
    assert result_codes == codes - {"current.too_large"}


def test_inspection_warns_when_current_state_becomes_a_history_or_path_ledger(
    tmp_path: Path,
) -> None:
    _scaffold(tmp_path)
    (tmp_path / "research/CURRENT.md").write_text(
        "# Current\n"
        "## 2026-07-14\n"
        "- `runs/a/output.h5`\n"
        "## 2026-07-15\n"
        "- [details](research/results/R0001-a/README.md)\n",
        encoding="utf-8",
    )
    budget = ResearchBudget(
        current_lines=4,
        current_path_references=1,
        current_chronological_headings=1,
    )

    status = inspect_workspace(tmp_path, budget=budget)
    issues = {issue.code: issue for issue in status.issues}

    assert status.current_lines == 5
    assert status.current_path_references == 2
    assert status.current_chronological_headings == 2
    assert issues["current.too_many_lines"].severity == "warning"
    assert issues["current.too_many_paths"].severity == "warning"
    assert issues["current.looks_chronological"].severity == "warning"
    assert status.ok is True


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


def test_create_result_destination_race_does_not_replace_competitor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _scaffold(tmp_path)
    _install_result_destination_race(monkeypatch)

    with pytest.raises(ResearchWorkspaceError):
        create_result(tmp_path, "Racing result")

    destination = tmp_path / "research/results/R0001-racing-result"
    assert (destination / "competitor.txt").read_text(encoding="utf-8") == "keep"
    assert not list((tmp_path / "research/results").glob(".tmp-result-*"))


def test_archive_result_destination_race_preserves_source_and_competitor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _scaffold(tmp_path)
    created = create_result(tmp_path, "Racing archive")
    _install_result_destination_race(monkeypatch)

    with pytest.raises(ResearchWorkspaceError):
        archive_result(tmp_path, created.result_id)

    competitor = tmp_path / "research/archive/results" / created.result_id
    assert created.path.is_dir()
    assert (competitor / "competitor.txt").read_text(encoding="utf-8") == "keep"


def test_restore_result_destination_race_preserves_archive_and_competitor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _scaffold(tmp_path)
    created = create_result(tmp_path, "Racing restore")
    archived = archive_result(tmp_path, created.result_id)
    _install_result_destination_race(monkeypatch)

    with pytest.raises(ResearchWorkspaceError):
        restore_result(tmp_path, created.result_id)

    assert archived.is_dir()
    assert (created.path / "competitor.txt").read_text(encoding="utf-8") == "keep"


def test_result_operations_reject_symlink_roots(tmp_path: Path) -> None:
    _scaffold(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    results = tmp_path / "research/results"
    results.rmdir()
    results.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ResearchWorkspaceError, match="unsafe results directory"):
        create_result(tmp_path, "must stay local")


def test_create_result_rejects_symlinked_research_parent_without_external_writes(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "research").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ResearchWorkspaceError, match="unsafe results directory"):
        create_result(tmp_path, "must stay project-local")

    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("operation", ["archive", "restore"])
def test_result_moves_reject_symlinked_research_parent(
    tmp_path: Path,
    operation: str,
) -> None:
    _scaffold(tmp_path)
    created = create_result(tmp_path, "must not move through symlink")
    if operation == "restore":
        archive_result(tmp_path, created.result_id)
    outside = tmp_path / "outside"
    outside.mkdir()
    relocated = outside / "research-data"
    (tmp_path / "research").rename(relocated)
    (tmp_path / "research").symlink_to(relocated, target_is_directory=True)

    with pytest.raises(
        ResearchWorkspaceError,
        match=r"unsafe (results|result archive)",
    ):
        if operation == "archive":
            archive_result(tmp_path, created.result_id)
        else:
            restore_result(tmp_path, created.result_id)

    active = relocated / "results" / created.result_id
    archived = relocated / "archive" / "results" / created.result_id
    assert active.is_dir() is (operation == "archive")
    assert archived.is_dir() is (operation == "restore")


def test_create_and_restore_enforce_active_result_limit_without_mutation(
    tmp_path: Path,
) -> None:
    _scaffold(tmp_path)
    budget = ResearchBudget(active_results=1)
    first = create_result(tmp_path, "First", budget=budget)

    with pytest.raises(ResearchWorkspaceError, match="active Result limit"):
        create_result(tmp_path, "Second", budget=budget)
    assert sorted(path.name for path in (tmp_path / "research/results").iterdir()) == [
        first.result_id
    ]

    archived = archive_result(tmp_path, first.result_id)
    replacement = create_result(tmp_path, "Replacement", budget=budget)
    with pytest.raises(ResearchWorkspaceError, match="active Result limit"):
        restore_result(tmp_path, first.result_id, budget=budget)

    assert archived.is_dir()
    assert replacement.path.is_dir()


def test_legacy_migration_is_deterministic_and_reversible(tmp_path: Path) -> None:
    _scaffold(tmp_path)
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes/2026-01-01.md").write_text("important", encoding="utf-8")
    (tmp_path / "analysis/data").mkdir(parents=True)
    (tmp_path / "analysis/data/note.md").write_text("evidence", encoding="utf-8")
    (tmp_path / "analysis/data/table.csv").write_text("a,b\n", encoding="utf-8")
    (tmp_path / ".harnessops").mkdir()
    (tmp_path / ".harnessops/project.toml").write_text("x=1\n", encoding="utf-8")
    (tmp_path / "_handoff").mkdir()
    (tmp_path / "_handoff/new_rules.md").write_text(
        "handoff document", encoding="utf-8"
    )

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
    assert (tmp_path / "_handoff/new_rules.md").is_file()
    assert (tmp_path / "research/archive/legacy/notes/2026-01-01.md").is_file()
    assert (tmp_path / "research/archive/legacy/MIGRATION.json").is_file()

    restored = restore_legacy_workspace(tmp_path)
    assert restored == moved
    assert (tmp_path / "notes/2026-01-01.md").read_text(encoding="utf-8") == "important"
    assert (tmp_path / "analysis/data/note.md").read_text(
        encoding="utf-8"
    ) == "evidence"
    assert not (tmp_path / "research/archive/legacy/MIGRATION.json").exists()


def test_legacy_migration_resumes_from_per_move_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _scaffold(tmp_path)
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes/note.md").write_text("note", encoding="utf-8")
    (tmp_path / "exports").mkdir()
    (tmp_path / "exports/data.txt").write_text("data", encoding="utf-8")
    planned = plan_legacy_migration(tmp_path)
    real_move = workspace_module.move_path_noreplace
    calls = 0

    def fail_second_move(source: Path, destination: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected migration failure")
        real_move(source, destination)

    monkeypatch.setattr(
        workspace_module,
        "move_path_noreplace",
        fail_second_move,
    )
    with pytest.raises(ResearchWorkspaceError, match="migration stopped"):
        migrate_legacy_workspace(tmp_path)

    manifest = tmp_path / "research/archive/legacy/MIGRATION.json"
    interrupted = json.loads(manifest.read_text(encoding="utf-8"))
    assert interrupted["status"] == "moving"
    assert len(interrupted["completed"]) == 1

    monkeypatch.setattr(workspace_module, "move_path_noreplace", real_move)
    resumed = migrate_legacy_workspace(tmp_path)

    assert resumed == planned
    completed = json.loads(manifest.read_text(encoding="utf-8"))
    assert completed["status"] == "complete"
    assert len(completed["completed"]) == 2
    assert (tmp_path / "research/archive/legacy/notes/note.md").is_file()
    assert (tmp_path / "research/archive/legacy/exports/data.txt").is_file()


def test_legacy_restore_resumes_after_move_before_checkpoint_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _scaffold(tmp_path)
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes/note.md").write_text("note", encoding="utf-8")
    (tmp_path / "exports").mkdir()
    (tmp_path / "exports/data.txt").write_text("data", encoding="utf-8")
    moved = migrate_legacy_workspace(tmp_path)
    manifest = tmp_path / "research/archive/legacy/MIGRATION.json"
    real_write = workspace_module._write_json_replace

    def fail_second_restore_checkpoint(path: Path, payload: object) -> None:
        if (
            isinstance(payload, dict)
            and payload.get("status") == "restoring"
            and len(payload.get("restored", [])) == 2
        ):
            raise OSError("injected checkpoint failure")
        real_write(path, payload)

    monkeypatch.setattr(
        workspace_module,
        "_write_json_replace",
        fail_second_restore_checkpoint,
    )
    with pytest.raises(ResearchWorkspaceError, match="restore stopped"):
        restore_legacy_workspace(tmp_path)

    interrupted = json.loads(manifest.read_text(encoding="utf-8"))
    assert interrupted["status"] == "restoring"
    assert len(interrupted["restored"]) == 1
    assert (tmp_path / "notes/note.md").is_file()
    assert (tmp_path / "exports/data.txt").is_file()

    monkeypatch.setattr(workspace_module, "_write_json_replace", real_write)
    real_move = workspace_module.move_path_noreplace
    resume_moves: list[tuple[Path, Path]] = []

    def record_resume_move(source: Path, destination: Path) -> None:
        resume_moves.append((source, destination))
        real_move(source, destination)

    monkeypatch.setattr(
        workspace_module,
        "move_path_noreplace",
        record_resume_move,
    )
    restored = restore_legacy_workspace(tmp_path)

    assert restored == moved
    assert resume_moves == []
    assert not manifest.exists()


def test_legacy_migration_destination_race_does_not_clobber_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _scaffold(tmp_path)
    source = tmp_path / "analysis/data/note.md"
    source.parent.mkdir(parents=True)
    source.write_text("original", encoding="utf-8")
    destination = tmp_path / "research/archive/legacy/analysis/data/note.md"
    real_move = workspace_module.move_path_noreplace

    def race(move_source: Path, move_destination: Path) -> None:
        move_destination.parent.mkdir(parents=True, exist_ok=True)
        move_destination.write_text("competitor", encoding="utf-8")
        real_move(move_source, move_destination)

    monkeypatch.setattr(workspace_module, "move_path_noreplace", race)
    with pytest.raises(ResearchWorkspaceError, match="migration stopped"):
        migrate_legacy_workspace(tmp_path)

    assert source.read_text(encoding="utf-8") == "original"
    assert destination.read_text(encoding="utf-8") == "competitor"
    payload = json.loads(
        (tmp_path / "research/archive/legacy/MIGRATION.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["completed"] == []
