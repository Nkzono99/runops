"""Tests for Codex plugin recommendation helpers."""

from __future__ import annotations

import subprocess

from runops.core.codex_plugin import CodexPluginRecommendation
from runops.harness._plugins import install_codex_plugin_recommendations


def test_install_codex_plugin_recommendations_runs_only_codex_plugin_commands(
    capsys,
) -> None:
    """Only safe ``codex plugin ...`` lines are executed from install_hint."""
    plugin = CodexPluginRecommendation(
        name="demo-plugin",
        display_name="Demo Plugin",
        reason="test",
        install_hint=(
            "gh auth status\n"
            "codex plugin marketplace add owner/demo --ref main\n"
            "codex plugin add demo-plugin@demo\n"
        ),
    )
    calls: list[list[str]] = []

    def fake_runner(argv: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    summary = install_codex_plugin_recommendations(
        [plugin],
        codex_executable="/usr/bin/codex",
        runner=fake_runner,
    )

    assert calls == [
        [
            "/usr/bin/codex",
            "plugin",
            "marketplace",
            "add",
            "owner/demo",
            "--ref",
            "main",
        ],
        ["/usr/bin/codex", "plugin", "add", "demo-plugin@demo"],
    ]
    assert summary.attempted == 2
    assert summary.succeeded == 2
    assert summary.failed == 0
    assert summary.manual_lines == ("gh auth status",)
    assert "Manual follow-up" in capsys.readouterr().out


def test_install_codex_plugin_recommendations_skips_when_codex_missing(
    monkeypatch,
) -> None:
    plugin = CodexPluginRecommendation(
        name="demo-plugin",
        display_name="Demo Plugin",
        reason="test",
        install_hint="codex plugin add demo-plugin@demo",
    )

    monkeypatch.setattr("runops.harness._plugins.shutil.which", lambda _cmd: None)

    summary = install_codex_plugin_recommendations([plugin])

    assert summary.skipped_reason == "codex CLI not found on PATH"
