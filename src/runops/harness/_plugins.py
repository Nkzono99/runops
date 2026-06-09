"""Codex plugin recommendation helpers."""

from __future__ import annotations

import shlex
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from runops.core.codex_plugin import (
    CodexPluginRecommendation,
    unique_codex_plugins,
)
from runops.core.site import SiteProfile, load_site_profile
from runops.harness._adapters import collect_codex_plugins

CodexPluginCommandRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class CodexPluginInstallSummary:
    """Summary of best-effort Codex plugin installation."""

    attempted: int = 0
    succeeded: int = 0
    failed: int = 0
    manual_lines: tuple[str, ...] = ()
    skipped_reason: str = ""


@dataclass(frozen=True)
class _CodexPluginCommand:
    """One safe Codex plugin command parsed from install_hint."""

    argv: list[str]
    display: str


def load_site_profile_for_recommendations(project_dir: Path) -> SiteProfile | None:
    """Load site profile metadata for plugin recommendations if possible."""
    try:
        return load_site_profile(project_dir)
    except (OSError, ValueError):
        return None


def collect_plugin_recommendations(
    simulator_names: list[str],
    *,
    site_profile: SiteProfile | None = None,
    extra_plugins: list[CodexPluginRecommendation] | None = None,
) -> list[CodexPluginRecommendation]:
    """Collect unique plugin recommendations for simulator and site choices."""
    recommendations: list[CodexPluginRecommendation] = []
    if simulator_names:
        recommendations.extend(collect_codex_plugins(simulator_names))
    if site_profile is not None:
        recommendations.extend(site_profile.codex_plugins)
    if extra_plugins:
        recommendations.extend(extra_plugins)
    return unique_codex_plugins(recommendations)


def echo_plugin_recommendations(
    recommendations: list[CodexPluginRecommendation],
) -> None:
    """Print plugin recommendations for ``runo init`` / ``runo setup``."""
    if not recommendations:
        return

    import typer

    typer.echo("\nRecommended Codex plugins:")
    typer.echo(
        "  Install these in your user-local Codex environment when you want "
        "simulator/site skills outside this runops project."
    )
    for plugin in recommendations:
        visibility = f" [{plugin.visibility}]" if plugin.visibility != "public" else ""
        typer.echo(f"  - {plugin.display_name} (`{plugin.name}`){visibility}")
        if plugin.reason:
            typer.echo(f"    Why: {plugin.reason}")
        if plugin.install_hint:
            typer.echo("    Install:")
            for line in plugin.install_hint.strip().splitlines():
                typer.echo(f"      {line}")
        if plugin.activation_hint:
            typer.echo(f"    Activate: {plugin.activation_hint}")


def install_codex_plugin_recommendations(
    recommendations: list[CodexPluginRecommendation],
    *,
    codex_executable: str | None = None,
    runner: CodexPluginCommandRunner | None = None,
) -> CodexPluginInstallSummary:
    """Install recommended plugins with safe ``codex plugin ...`` commands.

    ``install_hint`` is human-authored free text, so runops only executes lines
    that parse to ``codex plugin ...``. Other lines are reported as manual
    follow-up steps.
    """
    if not recommendations:
        return CodexPluginInstallSummary()

    codex = codex_executable or shutil.which("codex")
    if codex is None:
        return CodexPluginInstallSummary(
            skipped_reason="codex CLI not found on PATH",
        )

    import typer

    run = runner or _run_codex_plugin_command
    attempted = 0
    succeeded = 0
    failed = 0
    manual_lines: list[str] = []

    typer.echo("\nInstalling recommended Codex plugins:")
    for plugin in recommendations:
        commands, manual = _parse_codex_plugin_install_hint(
            plugin.install_hint,
            codex_executable=codex,
        )
        manual_lines.extend(manual)
        if not commands:
            typer.echo(
                f"  - {plugin.display_name}: no auto-installable "
                "`codex plugin ...` commands"
            )
            continue

        typer.echo(f"  - {plugin.display_name}")
        for command in commands:
            attempted += 1
            typer.echo(f"    $ {command.display}")
            result = run(command.argv)
            if result.returncode == 0:
                succeeded += 1
                continue

            failed += 1
            stderr = (result.stderr or result.stdout or "").strip()
            if stderr:
                typer.echo(f"      Warning: command failed: {stderr}")
            else:
                typer.echo(
                    f"      Warning: command failed with exit {result.returncode}"
                )

    if manual_lines:
        typer.echo("  Manual follow-up steps not run automatically:")
        for line in manual_lines:
            typer.echo(f"    {line}")

    if attempted:
        typer.echo(
            "  Plugin install commands finished. Enable installed plugins in "
            "Codex /plugins or start a new Codex thread as needed."
        )

    return CodexPluginInstallSummary(
        attempted=attempted,
        succeeded=succeeded,
        failed=failed,
        manual_lines=tuple(manual_lines),
    )


def _parse_codex_plugin_install_hint(
    install_hint: str,
    *,
    codex_executable: str,
) -> tuple[list[_CodexPluginCommand], list[str]]:
    commands: list[_CodexPluginCommand] = []
    manual_lines: list[str] = []

    for raw_line in install_hint.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            parts = shlex.split(line)
        except ValueError:
            manual_lines.append(line)
            continue
        if len(parts) >= 3 and parts[:2] == ["codex", "plugin"]:
            commands.append(
                _CodexPluginCommand(
                    argv=[codex_executable, *parts[1:]],
                    display=" ".join(shlex.quote(part) for part in parts),
                )
            )
        else:
            manual_lines.append(line)

    return commands, manual_lines


def _run_codex_plugin_command(
    argv: list[str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
