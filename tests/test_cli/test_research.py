"""CLI tests for the quantity-bounded research workspace."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from runops.cli.main import app

runner = CliRunner()


def _project(root: Path, *, current_chars: int = 20_000) -> None:
    (root / "runops.toml").write_text(
        (
            '[project]\nname = "demo"\n\n'
            "[research.workspace]\n"
            f"current_chars = {current_chars}\n"
            "journal_segment_chars = 64000\n"
            "result_readme_chars = 30000\n"
            "active_results = 8\n"
            "result_artifact_files = 50\n"
            "result_artifact_bytes = 209715200\n"
        ),
        encoding="utf-8",
    )
    (root / "research" / "journal" / "archive").mkdir(parents=True)
    (root / "research" / "results").mkdir()
    (root / "research" / "archive" / "results").mkdir(parents=True)
    (root / "research" / "CURRENT.md").write_text("# Current\n", encoding="utf-8")
    (root / "research" / "journal" / "active.md").write_text(
        "# Research Journal\n\n",
        encoding="utf-8",
    )


def test_research_help_lists_workspace_commands() -> None:
    result = runner.invoke(app, ["research", "--help"])

    assert result.exit_code == 0
    for command in [
        "status",
        "check",
        "append",
        "rotate",
        "new-result",
        "archive",
        "restore",
        "migrate-legacy",
    ]:
        assert command in result.output


def test_research_status_json_uses_project_budget(tmp_path: Path) -> None:
    _project(tmp_path, current_chars=8)

    result = runner.invoke(app, ["research", "status", str(tmp_path), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["budget"]["current_chars"] == 8
    assert payload["current_chars"] == len("# Current\n")
    assert payload["current_lines"] == 1
    assert payload["current_path_references"] == 0
    assert payload["current_chronological_headings"] == 0
    assert payload["ok"] is False
    assert payload["issues"][0]["code"] == "current.too_large"


def test_research_check_exits_one_for_budget_errors(tmp_path: Path) -> None:
    _project(tmp_path, current_chars=8)

    result = runner.invoke(app, ["research", "check", str(tmp_path)])

    assert result.exit_code == 1
    assert "current.too_large" in result.output


def test_research_append_and_force_rotate(tmp_path: Path) -> None:
    _project(tmp_path)

    append = runner.invoke(
        app,
        ["research", "append", "Observation", "stable", "--path", str(tmp_path)],
    )
    rotate = runner.invoke(
        app,
        ["research", "rotate", str(tmp_path), "--force"],
    )

    assert append.exit_code == 0
    assert "research/journal/active.md" in append.output
    assert rotate.exit_code == 0
    assert "research/journal/archive/J0001.md" in rotate.output


def test_research_result_lifecycle(tmp_path: Path) -> None:
    _project(tmp_path)

    created = runner.invoke(
        app,
        ["research", "new-result", "Dust release", "--path", str(tmp_path)],
    )
    archived = runner.invoke(
        app,
        ["research", "archive", "R0001-dust-release", "--path", str(tmp_path)],
    )
    restored = runner.invoke(
        app,
        ["research", "restore", "R0001-dust-release", "--path", str(tmp_path)],
    )

    assert created.exit_code == 0
    assert "R0001-dust-release" in created.output
    assert archived.exit_code == 0
    assert restored.exit_code == 0
    assert (tmp_path / "research/results/R0001-dust-release").is_dir()


def test_research_migrate_legacy_dry_run_apply_and_restore(tmp_path: Path) -> None:
    _project(tmp_path)
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes/old.md").write_text("old", encoding="utf-8")

    preview = runner.invoke(
        app, ["research", "migrate-legacy", str(tmp_path), "--dry-run"]
    )
    applied = runner.invoke(app, ["research", "migrate-legacy", str(tmp_path)])
    restored = runner.invoke(
        app, ["research", "migrate-legacy", str(tmp_path), "--restore"]
    )

    assert preview.exit_code == 0
    assert "notes -> research/archive/legacy/notes" in preview.output
    assert applied.exit_code == 0
    assert restored.exit_code == 0
    assert (tmp_path / "notes/old.md").is_file()
