"""CLI commands for serving and checking the runops MCP provider."""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal

import typer

from runops.mcp.registry import (
    all_tool_specs,
    conformance_report,
    exposed_tool_specs,
)
from runops.mcp.server import serve as serve_mcp

mcp_app = typer.Typer(
    name="mcp",
    help="RunOps MCP provider commands.",
    no_args_is_help=True,
)

TransportOption = Literal["stdio", "streamable-http"]


def _json_echo(payload: Any) -> None:
    typer.echo(json.dumps(payload, indent=2, sort_keys=True))


@mcp_app.command("serve")
def serve(
    transport: Annotated[
        TransportOption,
        typer.Option(
            "--transport",
            help="MCP transport to serve: stdio or streamable-http.",
            case_sensitive=False,
        ),
    ] = "stdio",
    host: Annotated[
        str,
        typer.Option(
            "--host",
            help="Host for streamable-http transport. Defaults to localhost.",
        ),
    ] = "127.0.0.1",
    port: Annotated[
        int,
        typer.Option("--port", help="Port for streamable-http transport."),
    ] = 8000,
    allow_remote: Annotated[
        bool,
        typer.Option(
            "--allow-remote",
            help="Allow binding streamable-http to a non-localhost interface.",
        ),
    ] = False,
) -> None:
    """Start the runops MCP server."""
    if transport == "stdio" and (host != "127.0.0.1" or port != 8000):
        typer.echo(
            "Warning: --host/--port are ignored for stdio transport.",
            err=True,
        )
    if (
        transport == "streamable-http"
        and host not in {"127.0.0.1", "localhost"}
        and not allow_remote
    ):
        typer.echo(
            "Error: non-localhost HTTP bind requires --allow-remote.",
            err=True,
        )
        raise typer.Exit(code=2)

    serve_mcp(transport=transport, host=host, port=port)


@mcp_app.command("tools")
def tools(
    json_output: Annotated[
        bool,
        typer.Option("--json/--no-json", help="Emit JSON output."),
    ] = True,
    include_disabled: Annotated[
        bool,
        typer.Option("--include-disabled", help="Include disabled tools."),
    ] = False,
) -> None:
    """List runops MCP tools."""
    specs = all_tool_specs() if include_disabled else exposed_tool_specs()
    payload = {"tools": [spec.to_dict() for spec in specs]}
    if json_output:
        _json_echo(payload)
        return
    for spec in specs:
        marker = "enabled" if spec.enabled and spec.exposed else "disabled"
        typer.echo(f"{spec.name}\t{spec.safety.safety_class}\t{marker}")


@mcp_app.command("resources")
def resources(
    json_output: Annotated[
        bool,
        typer.Option("--json/--no-json", help="Emit JSON output."),
    ] = True,
) -> None:
    """List runops MCP resources."""
    payload: dict[str, list[dict[str, Any]]] = {"resources": []}
    if json_output:
        _json_echo(payload)
    else:
        typer.echo("No MCP resources are exposed yet.")


@mcp_app.command("prompts")
def prompts(
    json_output: Annotated[
        bool,
        typer.Option("--json/--no-json", help="Emit JSON output."),
    ] = True,
) -> None:
    """List runops MCP prompts."""
    payload: dict[str, list[dict[str, Any]]] = {"prompts": []}
    if json_output:
        _json_echo(payload)
    else:
        typer.echo("No MCP prompts are exposed yet.")


@mcp_app.command("check")
def check(
    json_output: Annotated[
        bool,
        typer.Option("--json/--no-json", help="Emit JSON output."),
    ] = False,
) -> None:
    """Run lightweight Ops MCP conformance checks."""
    report = conformance_report()
    if json_output:
        _json_echo(report)
    else:
        typer.echo("runops MCP conformance")
        for item in report["checks"]:
            status = "PASS" if item["ok"] else "FAIL"
            typer.echo(f"[{status}] {item['name']}: {item['message']}")
        typer.echo(
            f"\n{report['exposed_tool_count']} exposed tool(s), "
            f"{report['tool_count']} registered tool(s)."
        )

    if not report["ok"]:
        raise typer.Exit(code=1)
