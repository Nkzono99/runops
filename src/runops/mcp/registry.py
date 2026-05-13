"""Tool registry and conformance checks for the runops MCP provider."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from runops.core.actions.specs import ACTION_SPECS
from runops.mcp.safety import (
    DESTRUCTIVE_DISABLED,
    EXTERNAL_DISABLED,
    INSPECT,
    PLAN,
    READ,
    SafetyMetadata,
)

TOOL_NAME_RE = re.compile(r"^[a-z][a-z0-9]*(\.[a-z][a-z0-9_\-]*){1,4}$")


@dataclass(frozen=True)
class ToolSpec:
    """Contract metadata for an MCP tool."""

    name: str
    description: str
    safety: SafetyMetadata
    enabled: bool = True
    exposed: bool = True
    deprecated: bool = False
    replacement: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-serializable tool metadata."""
        data: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "enabled": self.enabled,
            "exposed": self.exposed,
            "deprecated": self.deprecated,
        }
        data.update(self.safety.to_dict())
        if self.replacement:
            data["replacement"] = self.replacement
        return data


TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec("runops.health", "Check the runops MCP server health.", READ),
    ToolSpec(
        "runops.provider.info",
        "Return provider version and contract metadata.",
        READ,
    ),
    ToolSpec(
        "runops.capabilities",
        "Return advertised runops MCP capabilities and safety metadata.",
        READ,
    ),
    ToolSpec(
        "runops.project.list",
        "List the current local runops project discovered from the server cwd.",
        READ,
    ),
    ToolSpec(
        "runops.project.status",
        "Return a compact project status bundle.",
        READ,
    ),
    ToolSpec(
        "runops.project.inspect",
        "Return detailed local project metadata and agent context.",
        INSPECT,
    ),
    ToolSpec(
        "runops.project.doctor",
        "Diagnose project configuration without mutating project files.",
        READ,
    ),
    ToolSpec("runops.run.list", "List run directories and manifest states.", READ),
    ToolSpec("runops.run.inspect", "Inspect one run manifest and readiness.", INSPECT),
    ToolSpec("runops.run.logs", "Return tail lines from the latest run log.", INSPECT),
    ToolSpec(
        "runops.slurm.queue",
        "List Slurm job records known to the project manifests.",
        INSPECT,
    ),
    ToolSpec(
        "runops.slurm.job.inspect",
        "Inspect a Slurm job status using squeue/sacct.",
        INSPECT,
    ),
    ToolSpec(
        "runops.job.plan_submit",
        "Plan an sbatch submission command without submitting it.",
        PLAN,
    ),
    ToolSpec(
        "runops.job.submit",
        "Submit a run to Slurm. Disabled by default.",
        EXTERNAL_DISABLED,
        enabled=False,
        exposed=False,
    ),
    ToolSpec(
        "runops.job.cancel",
        "Cancel a Slurm job. Disabled by default.",
        DESTRUCTIVE_DISABLED,
        enabled=False,
        exposed=False,
    ),
    ToolSpec(
        "runops.run.delete",
        "Delete a run directory. Disabled by default.",
        DESTRUCTIVE_DISABLED,
        enabled=False,
        exposed=False,
    ),
)

REQUIRED_COMMON_TOOLS = {
    "runops.health",
    "runops.provider.info",
    "runops.capabilities",
    "runops.project.list",
    "runops.project.status",
    "runops.project.inspect",
    "runops.project.doctor",
}

REQUIRED_RUNOPS_TOOLS = REQUIRED_COMMON_TOOLS | {
    "runops.run.list",
    "runops.run.inspect",
    "runops.run.logs",
    "runops.slurm.queue",
    "runops.job.plan_submit",
}


def all_tool_specs() -> list[ToolSpec]:
    """Return all known tool specs, including disabled tools."""
    return list(TOOL_SPECS)


def exposed_tool_specs() -> list[ToolSpec]:
    """Return the tools exposed by the server."""
    return [spec for spec in TOOL_SPECS if spec.exposed and spec.enabled]


def tool_spec(name: str) -> ToolSpec:
    """Return metadata for *name*."""
    for spec in TOOL_SPECS:
        if spec.name == name:
            return spec
    raise KeyError(name)


def capabilities_payload() -> dict[str, Any]:
    """Return the provider capability payload."""
    return {
        "supported_project_kinds": ["experiment", "simulation", "hpc"],
        "required_project_fields": ["id", "path"],
        "optional_project_fields": ["host", "scheduler", "priority"],
        "safety_modes": {
            "read_only": True,
            "write_enabled": False,
            "external_enabled": False,
            "destructive_enabled": False,
        },
        "tools": [spec.to_dict() for spec in TOOL_SPECS],
        "transports": ["stdio", "streamable-http"],
    }


def conformance_report() -> dict[str, Any]:
    """Run lightweight local conformance checks for the registry."""
    names = [spec.name for spec in TOOL_SPECS]
    specs_by_name = {spec.name: spec for spec in TOOL_SPECS}
    exposed_names = {spec.name for spec in exposed_tool_specs()}
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, message: str) -> None:
        checks.append({"name": name, "ok": ok, "message": message})

    add("tool_names_unique", len(names) == len(set(names)), "Tool names are unique.")
    invalid_names = [name for name in names if TOOL_NAME_RE.match(name) is None]
    add(
        "tool_names_conform",
        not invalid_names,
        "All tool names match the Ops MCP naming convention."
        if not invalid_names
        else f"Invalid tool names: {', '.join(invalid_names)}",
    )
    missing_required = sorted(REQUIRED_RUNOPS_TOOLS - exposed_names)
    add(
        "required_tools_exposed",
        not missing_required,
        "All required runops tools are exposed."
        if not missing_required
        else f"Missing required tools: {', '.join(missing_required)}",
    )
    mutating_exposed = [
        spec.name
        for spec in exposed_tool_specs()
        if spec.safety.level >= 3 or spec.safety.side_effects
    ]
    add(
        "mutating_tools_disabled",
        not mutating_exposed,
        "No write/external/destructive tools are exposed by default."
        if not mutating_exposed
        else f"Mutating tools exposed: {', '.join(mutating_exposed)}",
    )
    safety_missing = [
        spec.name
        for spec in TOOL_SPECS
        if spec.safety.safety_class
        not in {
            "read",
            "inspect",
            "plan",
            "write",
            "external",
            "destructive",
        }
    ]
    add(
        "safety_metadata_present",
        not safety_missing,
        "Every tool has valid safety metadata.",
    )
    action_mcp_tools = {
        tool_name
        for action_spec in ACTION_SPECS.values()
        for tool_name in action_spec.mcp_tools
    }
    missing_action_tools = sorted(action_mcp_tools - set(names))
    add(
        "action_mcp_tools_registered",
        not missing_action_tools,
        "Every MCP tool referenced by an ActionSpec is registered."
        if not missing_action_tools
        else f"Unregistered action MCP tools: {', '.join(missing_action_tools)}",
    )
    unsafe_action_tools_without_confirmation = sorted(
        tool_name
        for tool_name in action_mcp_tools
        if tool_name in specs_by_name
        and specs_by_name[tool_name].safety.level >= 3
        and (
            not specs_by_name[tool_name].safety.requires_confirmation
            or not specs_by_name[tool_name].safety.confirmation_field
        )
    )
    add(
        "unsafe_action_mcp_tools_require_confirmation",
        not unsafe_action_tools_without_confirmation,
        "Unsafe action MCP tools require explicit confirmation metadata."
        if not unsafe_action_tools_without_confirmation
        else (
            "Unsafe action MCP tools without confirmation metadata: "
            + ", ".join(unsafe_action_tools_without_confirmation)
        ),
    )

    ok = all(bool(check["ok"]) for check in checks)
    return {
        "ok": ok,
        "checks": checks,
        "tool_count": len(TOOL_SPECS),
        "exposed_tool_count": len(exposed_names),
    }
