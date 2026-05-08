"""Tests for the migration CLI."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from runops.cli.main import app

runner = CliRunner()


def _write_project(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "runops.toml").write_text(
        """
[project]
name = "demo"
""".lstrip(),
        encoding="utf-8",
    )


def test_migrate_list_outputs_registered_migrations() -> None:
    result = runner.invoke(app, ["migrate", "list"])

    assert result.exit_code == 0
    assert "M0-0001" in result.output
    assert "Analysis artifact indexes" in result.output
    assert "M0-0002" in result.output


def test_migrate_requires_subcommand() -> None:
    result = runner.invoke(app, ["migrate"])

    assert result.exit_code == 2
    assert "Usage:" in result.output


def test_migrate_show_outputs_metadata() -> None:
    result = runner.invoke(app, ["migrate", "show", "M0-0001"])

    assert result.exit_code == 0
    assert "Analysis artifact indexes" in result.output
    assert "impact: analysis-artifact" in result.output


def test_migrate_applies_research_scaffold(tmp_path: Path) -> None:
    _write_project(tmp_path)

    result = runner.invoke(
        app,
        ["migrate", "apply", "M0-0002", "--project", str(tmp_path)],
    )

    assert result.exit_code == 0
    assert "M0-0002" in result.output
    assert "Status: applied" in result.output
    assert (tmp_path / "research" / "agenda.md").is_file()


def test_migrate_dry_run_does_not_write(tmp_path: Path) -> None:
    _write_project(tmp_path)

    result = runner.invoke(
        app,
        ["migrate", "apply", "v0", "0002", "--project", str(tmp_path), "--dry-run"],
    )

    assert result.exit_code == 0
    assert "Status: planned" in result.output
    assert "research/agenda.md" in result.output
    assert not (tmp_path / "research" / "agenda.md").exists()
