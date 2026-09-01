"""CLI tests for the quantity-bounded research workspace."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from runops.application.run_creation.workflow import directory_content_hash
from runops.cli.main import app
from runops.core.manifest import ManifestData, write_manifest

runner = CliRunner()


def _project(
    root: Path,
    *,
    current_chars: int = 20_000,
    active_results: int = 8,
    result_readme_chars: int = 30_000,
) -> None:
    (root / "runops.toml").write_text(
        (
            '[project]\nname = "demo"\n\n'
            "[research.workspace]\n"
            f"current_chars = {current_chars}\n"
            "journal_segment_chars = 64000\n"
            f"result_readme_chars = {result_readme_chars}\n"
            f"active_results = {active_results}\n"
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
        "check-result",
        "seal",
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
        [
            "research",
            "append",
            "Observation",
            "stable",
            "--kind",
            "observation",
            "--subject",
            "E0001",
            "--path",
            str(tmp_path),
        ],
    )
    assert append.exit_code == 0
    assert "research/journal/active.md" in append.output
    journal = (tmp_path / "research/journal/active.md").read_text(encoding="utf-8")
    assert "- Kind: `observation`" in journal
    assert "- Subject: `E0001`" in journal

    rotate = runner.invoke(
        app,
        ["research", "rotate", str(tmp_path), "--force"],
    )

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


def test_research_result_create_and_restore_use_project_budget(
    tmp_path: Path,
) -> None:
    _project(tmp_path, active_results=1)
    first = runner.invoke(
        app,
        ["research", "new-result", "First", "--path", str(tmp_path)],
    )
    blocked_create = runner.invoke(
        app,
        ["research", "new-result", "Second", "--path", str(tmp_path)],
    )
    archived = runner.invoke(
        app,
        ["research", "archive", "R0001-first", "--path", str(tmp_path)],
    )
    second = runner.invoke(
        app,
        ["research", "new-result", "Second", "--path", str(tmp_path)],
    )
    blocked_restore = runner.invoke(
        app,
        ["research", "restore", "R0001-first", "--path", str(tmp_path)],
    )

    assert first.exit_code == 0, first.output
    assert blocked_create.exit_code == 2
    assert "active Result limit" in blocked_create.output
    assert archived.exit_code == 0, archived.output
    assert second.exit_code == 0, second.output
    assert blocked_restore.exit_code == 2
    assert "active Result limit" in blocked_restore.output


def test_research_seal_and_check_result(tmp_path: Path) -> None:
    _project(tmp_path)
    run_id = "R20260801-0001"
    run_dir = tmp_path / "runs" / run_id
    (run_dir / "input").mkdir(parents=True)
    (run_dir / "input" / "params.toml").write_text("nx = 64\n", encoding="utf-8")
    write_manifest(
        run_dir,
        ManifestData(
            run={"id": run_id, "status": "completed"},
            simulator_source={
                "git_commit": "abc123",
                "git_dirty": False,
                "exe_hash": "sha256:" + "a" * 64,
                "package_version": "1.0.0",
            },
            files={"input_dir": "input"},
            intent={"baseline_reason": "No compatible baseline exists."},
            identity={
                "condition_hash": "sha256:" + "b" * 64,
                "input_hash": directory_content_hash(run_dir / "input"),
                "execution_hash": "sha256:" + "c" * 64,
                "provenance_hash": "sha256:" + "d" * 64,
            },
            curation={
                "review_status": "reviewed",
                "reviewed_at": "2026-09-01T00:00:00+00:00",
                "reviewed_by": "human",
                "reason": "accepted for evidence",
            },
        ),
    )
    created = runner.invoke(
        app,
        ["research", "new-result", "Dust release", "--path", str(tmp_path)],
    )

    sealed = runner.invoke(
        app,
        [
            "research",
            "seal",
            "R0001-dust-release",
            "--claim",
            "Release rises.",
            "--outcome",
            "supported",
            "--evidence-run",
            run_id,
            "--selection-reason",
            "completed reviewed source",
            "--path",
            str(tmp_path),
        ],
    )
    checked = runner.invoke(
        app,
        [
            "research",
            "check-result",
            "R0001-dust-release",
            "--path",
            str(tmp_path),
            "--json",
        ],
    )

    assert created.exit_code == 0
    assert sealed.exit_code == 0, sealed.output
    assert "Sealed" in sealed.output
    assert checked.exit_code == 0, checked.output
    payload = json.loads(checked.stdout)
    assert payload["sealed"] is True
    assert payload["ok"] is True


def test_research_check_and_seal_use_project_result_budget(tmp_path: Path) -> None:
    _project(tmp_path, result_readme_chars=8)
    created = runner.invoke(
        app,
        ["research", "new-result", "Bounded", "--path", str(tmp_path)],
    )
    artifact = tmp_path / "research/results/R0001-bounded/artifacts/value.csv"
    artifact.write_text("value\n1\n", encoding="utf-8")

    checked = runner.invoke(
        app,
        [
            "research",
            "check-result",
            "R0001-bounded",
            "--path",
            str(tmp_path),
            "--json",
        ],
    )
    sealed = runner.invoke(
        app,
        [
            "research",
            "seal",
            "R0001-bounded",
            "--claim",
            "A bounded claim.",
            "--outcome",
            "supported",
            "--evidence-path",
            artifact.relative_to(tmp_path).as_posix(),
            "--selection-reason",
            "selected Result artifact",
            "--path",
            str(tmp_path),
        ],
    )

    assert created.exit_code == 0, created.output
    assert checked.exit_code == 1, checked.output
    assert "result.readme_too_large" in checked.output
    assert sealed.exit_code == 2, sealed.output
    assert "result.readme_too_large" in sealed.output
    assert 'status = "draft"' in (
        tmp_path / "research/results/R0001-bounded/manifest.toml"
    ).read_text(encoding="utf-8")


def test_research_seal_requires_selection_reason(tmp_path: Path) -> None:
    _project(tmp_path)

    result = runner.invoke(
        app,
        [
            "research",
            "seal",
            "R0001-missing",
            "--claim",
            "A scoped claim.",
            "--outcome",
            "inconclusive",
            "--evidence-run",
            "R20260801-0001",
            "--path",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 2
    assert "--selection-reason" in result.output


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
