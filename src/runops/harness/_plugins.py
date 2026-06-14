"""Codex plugin recommendation helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from runops.core.codex_plugin import CodexPluginRecommendation
from runops.core.plugins import (
    collect_codex_plugin_recommendations,
)
from runops.core.site import SiteProfile, load_site_profile


def load_site_profile_for_recommendations(project_dir: Path) -> SiteProfile | None:
    """Load site profile metadata for plugin recommendations if possible."""
    try:
        return load_site_profile(project_dir)
    except (OSError, ValueError):
        return None


def collect_plugin_recommendations(
    simulator_names: list[str],
    *,
    simulator_configs: dict[str, dict[str, Any]] | None = None,
    site_profile: SiteProfile | None = None,
    extra_plugins: list[CodexPluginRecommendation] | None = None,
) -> list[CodexPluginRecommendation]:
    """Collect unique plugin recommendations for simulator and site choices."""
    return collect_codex_plugin_recommendations(
        simulator_names,
        simulator_configs=simulator_configs,
        site_profile=site_profile,
        extra_plugins=extra_plugins,
    )


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
        if plugin.capabilities:
            typer.echo(f"    Capabilities: {', '.join(plugin.capabilities)}")
        if plugin.install_hint:
            typer.echo("    Install:")
            for line in plugin.install_hint.strip().splitlines():
                typer.echo(f"      {line}")
        if plugin.activation_hint:
            typer.echo(f"    Activate: {plugin.activation_hint}")
