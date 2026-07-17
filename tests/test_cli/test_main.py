"""Tests for CLI entry point."""

from __future__ import annotations

from typing import Any

from typer.testing import CliRunner

from runops import __version__
from runops.cli.main import app, runops_app

runner = CliRunner()


def _command_name(command: Any) -> str:
    name = command.name
    if name:
        return str(name)
    callback = command.callback
    assert callback is not None
    return str(callback.__name__).replace("_", "-")


def _command_paths(typer_app: Any, prefix: tuple[str, ...] = ()) -> set[str]:
    paths = {
        " ".join((*prefix, _command_name(command)))
        for command in typer_app.registered_commands
    }
    for group in typer_app.registered_groups:
        paths.update(
            _command_paths(
                group.typer_instance,
                (*prefix, str(group.name)),
            )
        )
    return paths


def test_command_tree_is_stable_for_primary_and_alias_apps() -> None:
    expected = {
        "analyze audit-story",
        "analyze collect",
        "analyze export",
        "analyze new-comparison",
        "analyze new-story",
        "analyze plot",
        "analyze summarize",
        "case new",
        "config add-launcher",
        "config add-simulator",
        "config show",
        "context",
        "demo build-codex-replay",
        "demo import-codex-session",
        "demo render-replay",
        "doctor",
        "init",
        "knowledge add-fact",
        "knowledge facts",
        "knowledge list",
        "knowledge profile disable",
        "knowledge profile enable",
        "knowledge promote-fact",
        "knowledge save",
        "knowledge show",
        "knowledge source attach",
        "knowledge source detach",
        "knowledge source list",
        "knowledge source render",
        "knowledge source status",
        "knowledge source sync",
        "lint",
        "mcp check",
        "mcp prompts",
        "mcp resources",
        "mcp serve",
        "mcp tools",
        "migrate apply",
        "migrate list",
        "migrate show",
        "plugins",
        "research append",
        "research archive",
        "research check",
        "research migrate-legacy",
        "research new-result",
        "research restore",
        "research rotate",
        "research status",
        "runs archive",
        "runs cancel",
        "runs clone",
        "runs create",
        "runs dashboard",
        "runs delete",
        "runs extend",
        "runs history",
        "runs jobs",
        "runs list",
        "runs log",
        "runs purge-work",
        "runs regenerate",
        "runs restore",
        "runs retry",
        "runs status",
        "runs submit",
        "runs sweep",
        "runs sync",
        "setup",
        "update",
        "update-harness",
        "update-refs",
    }

    assert _command_paths(app) == expected
    assert _command_paths(runops_app) == expected


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
        "research",
        "mcp",
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
        "restore",
        "purge-work",
    ]:
        assert cmd in result.output


def test_analyze_help_shows_grouped_analysis_commands() -> None:
    result = runner.invoke(app, ["analyze", "--help"])
    assert result.exit_code == 0
    for cmd in ["summarize", "collect", "plot", "export", "new-comparison"]:
        assert cmd in result.output


def test_research_help_replaces_notes_group() -> None:
    result = runner.invoke(app, ["research", "--help"])
    assert result.exit_code == 0

    removed = runner.invoke(app, ["notes", "--help"])
    assert removed.exit_code != 0
    assert "No such command" in removed.output


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
