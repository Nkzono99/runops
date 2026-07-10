"""CLI command for external Codex plugin recommendations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from runops.application.gateway.plugins import (
    CodexPluginCheckResult,
    CodexPluginInventory,
    CodexPluginIssue,
)
from runops.core.exceptions import SimctlError


def plugins(
    directory: Annotated[
        Path,
        typer.Argument(
            help="Project directory or a path inside one (default: cwd).",
            exists=True,
        ),
    ] = Path("."),
    output_json: Annotated[
        bool,
        typer.Option("--json/--no-json", help="Emit JSON output."),
    ] = False,
    check: Annotated[
        bool,
        typer.Option(
            "--check",
            help=(
                "Validate recommendation metadata. Does not inspect or mutate "
                "user-local Codex plugin installation state."
            ),
        ),
    ] = False,
    strict: Annotated[
        bool,
        typer.Option(
            "--strict",
            help="With --check, fail on warnings as well as errors.",
        ),
    ] = False,
) -> None:
    """List or check external Codex plugins recommended for the project."""
    from runops.application.gateway.plugins import (
        check_project_codex_plugins,
        load_project_codex_plugin_inventory,
    )

    try:
        if check:
            result = check_project_codex_plugins(directory)
            inventory = result.inventory
        else:
            result = None
            inventory = load_project_codex_plugin_inventory(directory)
    except SimctlError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from None
    except (OSError, ValueError) as exc:
        typer.echo(f"Error loading plugin recommendations: {exc}", err=True)
        raise typer.Exit(code=1) from None

    if output_json:
        payload = result.to_dict() if result is not None else inventory.to_dict()
        typer.echo(json.dumps(payload, indent=2, ensure_ascii=False))
        if result is not None and not _check_passed(result, strict=strict):
            raise typer.Exit(code=1)
        return

    _echo_plugin_inventory(inventory)
    if result is not None:
        _echo_plugin_check_result(result)
        if not _check_passed(result, strict=strict):
            raise typer.Exit(code=1)


def _echo_plugin_inventory(inventory: CodexPluginInventory) -> None:
    """Print a human-readable plugin recommendation summary."""
    typer.echo(
        f"Codex plugin recommendations for {inventory.project_name} "
        f"({inventory.project_dir})"
    )
    typer.echo(
        "runops does not install or enable these plugins; manage them in your "
        "user-local Codex environment."
    )
    if inventory.simulator_names:
        typer.echo(f"Simulators: {', '.join(inventory.simulator_names)}")
    typer.echo(f"Site: {inventory.site_name}")
    delegated_capabilities = inventory.delegated_capabilities()
    if delegated_capabilities:
        typer.echo("Delegated capabilities:")
        for capability, plugin_names in delegated_capabilities.items():
            typer.echo(f"  - {capability}: {', '.join(plugin_names)}")

    if not inventory.recommendations:
        typer.echo("\nNo recommended Codex plugins.")
        return

    typer.echo("\nRecommended Codex plugins:")
    for plugin in inventory.recommendations:
        visibility = f" [{plugin.visibility}]" if plugin.visibility != "public" else ""
        typer.echo(f"  - {plugin.display_name} (`{plugin.name}`){visibility}")
        if plugin.source:
            typer.echo(f"    Source: {plugin.source}")
        if plugin.capabilities:
            typer.echo(f"    Capabilities: {', '.join(plugin.capabilities)}")
        if plugin.reason:
            typer.echo(f"    Why: {plugin.reason}")
        if plugin.install_hint:
            typer.echo("    Install:")
            for line in plugin.install_hint.strip().splitlines():
                typer.echo(f"      {line}")
        if plugin.activation_hint:
            typer.echo(f"    Activate: {plugin.activation_hint}")


def _check_passed(result: CodexPluginCheckResult, *, strict: bool) -> bool:
    """Return whether a check result should pass for the requested strictness."""
    return result.ok_with_strict() if strict else result.ok


def _echo_plugin_check_result(result: CodexPluginCheckResult) -> None:
    """Print a human-readable plugin metadata check result."""
    if not result.issues:
        typer.echo("\nPlugin recommendation metadata: OK")
        return

    errors = [issue for issue in result.issues if issue.severity == "error"]
    warnings = [issue for issue in result.issues if issue.severity == "warning"]
    typer.echo(
        "\nPlugin recommendation metadata: "
        f"{len(errors)} error(s), {len(warnings)} warning(s)"
    )
    for issue in result.issues:
        _echo_plugin_issue(issue)


def _echo_plugin_issue(issue: CodexPluginIssue) -> None:
    """Print one plugin metadata issue."""
    source = f" source={issue.source}" if issue.source else ""
    typer.echo(
        f"  - [{issue.severity}] {issue.plugin_name}.{issue.field}:{source} "
        f"{issue.message}"
    )
