"""Shared result envelope helpers for Ops MCP Contract v0.1."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Literal

from runops import __version__
from runops.core.exceptions import SimctlError
from runops.core.project import load_project
from runops.mcp.safety import SafetyMetadata

CONTRACT_VERSION = "0.1"
PROVIDER = "runops"
EnvelopeStatus = Literal["ok", "warning", "error", "blocked"]


def now_iso() -> str:
    """Return the current local time as an ISO-8601 timestamp."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def new_operation_id() -> str:
    """Create a short, sortable-enough operation identifier."""
    return f"op_{uuid.uuid4().hex}"


def warning(code: str, message: str, *, severity: str = "medium") -> dict[str, str]:
    """Build a contract warning object."""
    return {"code": code, "message": message, "severity": severity}


def error(code: str, message: str, *, hint: str = "") -> dict[str, object]:
    """Build a contract error object."""
    result: dict[str, object] = {"code": code, "message": message}
    if hint:
        result["hint"] = hint
    return result


def inputs_hash(inputs: dict[str, Any]) -> str:
    """Hash sanitized input arguments for audit metadata."""
    payload = json.dumps(inputs, sort_keys=True, default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def outputs_hash(output: dict[str, Any]) -> str:
    """Hash sanitized output payload for audit metadata."""
    payload = json.dumps(output, sort_keys=True, default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def project_ref(project_root: Path | None) -> dict[str, str] | None:
    """Build the envelope project reference for a local runops project."""
    if project_root is None:
        return None
    try:
        project = load_project(project_root)
        project_id = project.name or project_root.name
    except SimctlError:
        project_id = project_root.name
    return {
        "id": project_id,
        "kind": "experiment",
        "root": str(project_root),
        "location": "local",
    }


def envelope(
    *,
    tool: str,
    safety: SafetyMetadata,
    status: EnvelopeStatus,
    summary: str,
    data: dict[str, Any] | None = None,
    project_root: Path | None = None,
    warnings: list[dict[str, Any]] | None = None,
    errors: list[dict[str, Any]] | None = None,
    next_actions: list[dict[str, Any]] | None = None,
    resources: list[dict[str, Any]] | None = None,
    operation_id: str | None = None,
    started_at: str | None = None,
    started_perf: float | None = None,
    inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a standard Ops MCP result envelope."""
    op_id = operation_id or new_operation_id()
    start_iso = started_at or now_iso()
    completed_at = now_iso()
    duration_ms = 0
    if started_perf is not None:
        duration_ms = int((perf_counter() - started_perf) * 1000)
    payload = data or {}
    audit: dict[str, Any] = {
        "started_at": start_iso,
        "completed_at": completed_at,
        "duration_ms": duration_ms,
        "inputs_hash": inputs_hash(inputs or {}),
        "outputs_hash": outputs_hash(payload),
        "changed_files": [],
        "external_side_effects": [],
    }
    return {
        "contract_version": CONTRACT_VERSION,
        "provider": PROVIDER,
        "provider_version": __version__,
        "tool": tool,
        "operation_id": op_id,
        "status": status,
        "safety": {
            "level": safety.level,
            "class": safety.safety_class,
            "side_effects": safety.side_effects,
        },
        "project": project_ref(project_root),
        "summary": summary,
        "data": payload,
        "warnings": warnings or [],
        "errors": errors or [],
        "next_actions": next_actions or [],
        "resources": resources or [],
        "audit": audit,
    }


def blocked_envelope(
    *,
    tool: str,
    safety: SafetyMetadata,
    code: str,
    message: str,
    project_root: Path | None = None,
    inputs: dict[str, Any] | None = None,
    hint: str = "",
) -> dict[str, Any]:
    """Build a blocked result envelope."""
    return envelope(
        tool=tool,
        safety=safety,
        status="blocked",
        summary=message,
        data={},
        project_root=project_root,
        errors=[error(code, message, hint=hint)],
        inputs=inputs,
    )
