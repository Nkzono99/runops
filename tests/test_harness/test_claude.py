"""Tests for Claude harness settings generation."""

from __future__ import annotations

import json

from runops.harness import build_claude_settings


def test_build_claude_settings_exposes_expected_policy() -> None:
    """Claude settings include the expected allow/ask/deny policy."""
    data = json.loads(build_claude_settings())

    assert "permissions" in data
    assert "allow" in data["permissions"]
    assert "ask" in data["permissions"]
    assert "deny" in data["permissions"]
    assert "Bash(runo analyze plot*)" in data["permissions"]["allow"]
    assert "Bash(runo analyze export*)" in data["permissions"]["allow"]
    assert "Bash(uvx --from runops runo analyze plot*)" in data["permissions"]["allow"]
    assert (
        "Bash(uvx --from runops runo analyze export*)" in data["permissions"]["allow"]
    )
    assert "Bash(runops analyze plot*)" in data["permissions"]["allow"]
    assert "Bash(runops analyze export*)" in data["permissions"]["allow"]
    assert "Edit(/campaign.toml)" in data["permissions"]["allow"]
    assert "Edit(/.agents/skills/**)" in data["permissions"]["allow"]
    assert "Edit(/.codex/README.md)" in data["permissions"]["allow"]
    assert "Write(/runops.toml)" in data["permissions"]["ask"]
    assert "Write(/.codex/config.toml)" in data["permissions"]["ask"]
    assert "Write(/.codex/rules/**)" in data["permissions"]["ask"]
    assert "Write(/**/AGENTS.md)" in data["permissions"]["ask"]
    assert "Write(/SITE.md)" in data["permissions"]["deny"]
    assert "Edit(/runs/**/manifest.toml)" in data["permissions"]["deny"]
    assert data["permissions"]["disableBypassPermissionsMode"] == "disable"


def test_settings_do_not_allow_tools_runops_writes() -> None:
    """tools/runops/** is not allow-listed by default."""
    data = json.loads(build_claude_settings())
    assert "Edit(/tools/runops/**)" not in data["permissions"]["allow"]
    assert "Write(/tools/runops/**)" not in data["permissions"]["allow"]
    assert "Edit(/tools/runops/**)" not in data["permissions"]["ask"]
    assert "Write(/tools/runops/**)" not in data["permissions"]["ask"]


def test_runs_submit_is_allow_listed() -> None:
    """runo/runops submit is allowed; workflow rules require review first."""
    data = json.loads(build_claude_settings())
    assert "Bash(runo runs submit*)" in data["permissions"]["allow"]
    assert "Bash(uvx --from runops runo runs submit*)" in data["permissions"]["allow"]
    assert "Bash(runops runs submit*)" in data["permissions"]["allow"]
    assert "Bash(runo runs submit*)" not in data["permissions"]["ask"]
    assert "Bash(uvx --from runops runo runs submit*)" not in data["permissions"]["ask"]
    assert "Bash(runops runs submit*)" not in data["permissions"]["ask"]


def test_settings_does_not_install_pretooluse_hooks() -> None:
    """Settings.json must not declare PreToolUse hooks (moved to rules)."""
    data = json.loads(build_claude_settings())
    assert "hooks" not in data
