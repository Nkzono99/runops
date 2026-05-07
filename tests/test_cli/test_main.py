"""Tests for CLI entry point."""

from __future__ import annotations

from typer.testing import CliRunner

from runops import __version__
from runops.cli.main import app, runops_app

runner = CliRunner()


def test_help_shows_primary_commands() -> None:
    result = runner.invoke(
        app,
        ["--help"],
        env={"COLUMNS": "160", "TERM": "dumb", "NO_COLOR": "1"},
    )
    normalized_output = " ".join(result.output.split())
    assert result.exit_code == 0
    assert app.info.name == "runo"
    assert "Preferred command: runo" in normalized_output
    assert "Stable alias: runops" in normalized_output
    for cmd in [
        "init",
        "setup",
        "doctor",
        "context",
        "config",
        "knowledge",
        "case",
        "runs",
        "analyze",
        "demo",
        "update",
        "update-refs",
    ]:
        assert cmd in result.output


def test_runops_compatibility_app_keeps_legacy_name() -> None:
    result = runner.invoke(
        runops_app,
        ["--help"],
        env={"COLUMNS": "120", "TERM": "dumb", "NO_COLOR": "1"},
    )
    assert result.exit_code == 0
    assert runops_app.info.name == "runops"
    assert "Usage: runops" in result.output


def test_version_option_reports_runo_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.output.strip() == f"runo {__version__}"


def test_version_option_reports_runops_alias_version() -> None:
    result = runner.invoke(runops_app, ["--version"])

    assert result.exit_code == 0
    assert result.output.strip() == f"runops {__version__}"


def test_case_help_shows_grouped_case_commands() -> None:
    result = runner.invoke(app, ["case", "--help"])
    assert result.exit_code == 0
    assert "new" in result.output


def test_runs_help_shows_grouped_run_commands() -> None:
    result = runner.invoke(app, ["runs", "--help"])
    assert result.exit_code == 0
    for cmd in [
        "create",
        "submit",
        "status",
        "sync",
        "log",
        "list",
        "jobs",
        "history",
        "clone",
        "extend",
        "archive",
        "purge-work",
    ]:
        assert cmd in result.output


def test_analyze_help_shows_grouped_analysis_commands() -> None:
    result = runner.invoke(app, ["analyze", "--help"])
    assert result.exit_code == 0
    for cmd in ["summarize", "collect", "plot", "export", "new-comparison"]:
        assert cmd in result.output


def test_runs_submit_help_is_available() -> None:
    # Force a wide, plain terminal so typer/rich does not wrap or
    # elide the ``--afterok`` flag.  In CI the default column width
    # is narrower than locally and rich was breaking the option
    # token across lines, causing the substring check to fail.
    result = runner.invoke(
        app,
        ["runs", "submit", "--help"],
        env={"COLUMNS": "200", "TERM": "dumb", "NO_COLOR": "1"},
    )
    assert result.exit_code == 0
    # Match the bare option name (no leading dashes): rich may emit
    # soft wraps inside long help text, but the flag itself is one
    # token and survives any rendering width.
    assert "afterok" in result.output


def test_removed_top_level_create_command_is_unavailable() -> None:
    result = runner.invoke(app, ["create", "--help"])
    assert result.exit_code != 0
    assert "No such command" in result.output


def test_removed_top_level_run_command_is_unavailable() -> None:
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code != 0
    assert "No such command" in result.output


def test_removed_top_level_submit_command_is_unavailable() -> None:
    result = runner.invoke(app, ["submit", "--help"])
    assert result.exit_code != 0
    assert "No such command" in result.output
