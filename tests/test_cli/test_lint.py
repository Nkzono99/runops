"""Tests for the project lint CLI."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from runops.cli.main import app
from runops.harness.builder import GITIGNORE_MANAGED_END, GITIGNORE_MANAGED_START

runner = CliRunner()


def _write_project(path: Path, *, include_research: bool = True) -> None:
    (path / "runops.toml").write_text(
        '[project]\nname = "demo"\n',
        encoding="utf-8",
    )
    (path / "campaign.toml").write_text(
        '[campaign]\ngoal = "demo"\n',
        encoding="utf-8",
    )
    if include_research:
        (path / "research" / "journal").mkdir(parents=True)
        (path / "research" / "CURRENT.md").write_text(
            "# Current Research State\n", encoding="utf-8"
        )
        (path / "research" / "journal" / "active.md").write_text(
            "# Research Journal\n\n", encoding="utf-8"
        )
    (path / ".gitignore").write_text(
        f"{GITIGNORE_MANAGED_START}\nwork/\n{GITIGNORE_MANAGED_END}\n",
        encoding="utf-8",
    )


def test_lint_cli_outputs_ok(tmp_path: Path) -> None:
    _write_project(tmp_path)

    result = runner.invoke(app, ["lint", str(tmp_path), "--scope", "structure"])

    assert result.exit_code == 0
    assert "Project lint: ok" in result.output


def test_lint_cli_json_report(tmp_path: Path) -> None:
    _write_project(tmp_path, include_research=False)

    result = runner.invoke(
        app,
        ["lint", str(tmp_path), "--scope", "structure", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["status"] == "warning"
    assert payload["issues"][0]["id"] == "structure.research_current_missing"


def test_lint_cli_strict_exits_on_warning(tmp_path: Path) -> None:
    _write_project(tmp_path, include_research=False)

    result = runner.invoke(
        app,
        ["lint", str(tmp_path), "--scope", "structure", "--strict"],
    )

    assert result.exit_code == 1
    assert "structure.research_current_missing" in result.output


def test_lint_cli_rejects_unknown_scope(tmp_path: Path) -> None:
    _write_project(tmp_path)

    result = runner.invoke(app, ["lint", str(tmp_path), "--scope", "nope"])

    assert result.exit_code == 1
    assert "Unknown lint scope" in result.output


def test_lint_cli_reports_plugin_metadata_errors(tmp_path: Path) -> None:
    """The plugins scope exposes Codex plugin recommendation metadata errors."""
    _write_project(tmp_path)
    (tmp_path / "site.toml").write_text(
        '[site]\nname = "test-site"\n'
        "[site.codex_plugins.incomplete]\n"
        'display_name = "Incomplete Plugin"\n',
        encoding="utf-8",
    )

    result = runner.invoke(app, ["lint", str(tmp_path), "--scope", "plugins"])

    assert result.exit_code == 1
    assert "plugins.metadata_error" in result.output
    assert "incomplete.reason" in result.output
