"""Tests for the project lint CLI."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from runops.cli.main import app
from runops.harness.builder import GITIGNORE_MANAGED_END, GITIGNORE_MANAGED_START

runner = CliRunner()


def _write_project(path: Path, *, include_agenda: bool = True) -> None:
    (path / "runops.toml").write_text(
        '[project]\nname = "demo"\n',
        encoding="utf-8",
    )
    (path / "campaign.toml").write_text(
        '[campaign]\ngoal = "demo"\n',
        encoding="utf-8",
    )
    notes_dir = path / "notes"
    notes_dir.mkdir(parents=True)
    (notes_dir / "README.md").write_text("# Notes\n", encoding="utf-8")
    if include_agenda:
        research_dir = path / "research"
        research_dir.mkdir(parents=True)
        (research_dir / "agenda.md").write_text(
            """
# Research Agenda

## Current Decision

- Decision: Keep the current plan.

## Next Actions

1. Action: inspect latest run.
   - Evidence path to produce: notes/2026-05-08.md
""".lstrip(),
            encoding="utf-8",
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
    _write_project(tmp_path, include_agenda=False)

    result = runner.invoke(
        app,
        ["lint", str(tmp_path), "--scope", "structure", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["status"] == "warning"
    assert payload["issues"][0]["id"] == "structure.research_agenda_missing"


def test_lint_cli_strict_exits_on_warning(tmp_path: Path) -> None:
    _write_project(tmp_path, include_agenda=False)

    result = runner.invoke(
        app,
        ["lint", str(tmp_path), "--scope", "structure", "--strict"],
    )

    assert result.exit_code == 1
    assert "structure.research_agenda_missing" in result.output


def test_lint_cli_rejects_unknown_scope(tmp_path: Path) -> None:
    _write_project(tmp_path)

    result = runner.invoke(app, ["lint", str(tmp_path), "--scope", "nope"])

    assert result.exit_code == 1
    assert "Unknown lint scope" in result.output
