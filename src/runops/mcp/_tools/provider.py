"""Provider metadata tools for the runops MCP server."""

from __future__ import annotations

from typing import Any

from runops import __version__
from runops.mcp._tools.common import _tool_start
from runops.mcp.registry import (
    CODEX_PLUGIN_POLICY,
    capabilities_payload,
    exposed_tool_specs,
    tool_spec,
)
from runops.mcp.schemas import CONTRACT_VERSION, envelope


def health() -> dict[str, Any]:
    """Check the runops MCP server health."""
    started_at, started_perf = _tool_start()
    spec = tool_spec("runops.health")
    return envelope(
        tool=spec.name,
        safety=spec.safety,
        status="ok",
        summary="runops MCP server is healthy.",
        data={"healthy": True},
        started_at=started_at,
        started_perf=started_perf,
    )


def provider_info() -> dict[str, Any]:
    """Return provider metadata."""
    started_at, started_perf = _tool_start()
    spec = tool_spec("runops.provider.info")
    return envelope(
        tool=spec.name,
        safety=spec.safety,
        status="ok",
        summary=f"runops {__version__} implements Ops MCP Contract {CONTRACT_VERSION}.",
        data={
            "provider": "runops",
            "provider_version": __version__,
            "contract_version": CONTRACT_VERSION,
            "supported_transports": ["stdio", "streamable-http"],
            "codex_plugin_policy": CODEX_PLUGIN_POLICY,
            "default_policy": {
                "read_enabled": True,
                "plan_enabled": True,
                "write_enabled": False,
                "external_enabled": False,
                "destructive_enabled": False,
            },
        },
        started_at=started_at,
        started_perf=started_perf,
    )


def capabilities() -> dict[str, Any]:
    """Return provider capabilities."""
    started_at, started_perf = _tool_start()
    spec = tool_spec("runops.capabilities")
    exposed_count = len(exposed_tool_specs())
    return envelope(
        tool=spec.name,
        safety=spec.safety,
        status="ok",
        summary=f"runops exposes {exposed_count} read/inspect/plan tools.",
        data=capabilities_payload(),
        started_at=started_at,
        started_perf=started_perf,
    )
