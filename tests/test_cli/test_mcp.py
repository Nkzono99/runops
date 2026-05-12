"""Tests for the ``runo mcp`` CLI commands."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from runops.cli.main import app

runner = CliRunner()


def test_mcp_help_shows_commands() -> None:
    result = runner.invoke(app, ["mcp", "--help"])

    assert result.exit_code == 0
    for command in ["serve", "check", "tools", "resources", "prompts"]:
        assert command in result.output


def test_mcp_tools_outputs_json() -> None:
    result = runner.invoke(app, ["mcp", "tools", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    names = {tool["name"] for tool in payload["tools"]}
    assert "runops.health" in names
    assert "runops.job.plan_submit" in names
    assert "runops.job.submit" not in names


def test_mcp_check_passes() -> None:
    result = runner.invoke(app, ["mcp", "check"])

    assert result.exit_code == 0
    assert "[PASS] required_tools_exposed" in result.output


def test_mcp_streamable_http_rejects_remote_bind_without_flag() -> None:
    result = runner.invoke(
        app,
        [
            "mcp",
            "serve",
            "--transport",
            "streamable-http",
            "--host",
            "0.0.0.0",
        ],
    )

    assert result.exit_code == 2
    assert "requires --allow-remote" in result.output
