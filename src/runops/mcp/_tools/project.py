"""Project discovery and diagnostic tools for the runops MCP server."""

from __future__ import annotations

import shutil
from typing import Any

from runops.application.context import build_project_context
from runops.application.gateway.plugins import check_project_codex_plugins
from runops.core.discovery import validate_uniqueness
from runops.core.exceptions import SimctlError
from runops.core.project import load_project
from runops.mcp._tools.common import (
    _project_config_payload,
    _resolve_project_root,
    _tool_start,
)
from runops.mcp.registry import tool_spec
from runops.mcp.schemas import (
    EnvelopeStatus,
    blocked_envelope,
    envelope,
    error,
    warning,
)


def project_list(project_root: str | None = None) -> dict[str, Any]:
    """List the current local runops project."""
    started_at, started_perf = _tool_start()
    spec = tool_spec("runops.project.list")
    inputs = {"project_root": project_root}
    try:
        root = _resolve_project_root(project_root)
        project = load_project(root)
    except SimctlError as exc:
        return blocked_envelope(
            tool=spec.name,
            safety=spec.safety,
            code="project_not_found",
            message=str(exc),
            inputs=inputs,
        )

    return envelope(
        tool=spec.name,
        safety=spec.safety,
        status="ok",
        summary=f"Found project {project.name!r}.",
        data={"projects": [_project_config_payload(project)]},
        project_root=root,
        started_at=started_at,
        started_perf=started_perf,
        inputs=inputs,
    )


def project_status(project_root: str | None = None) -> dict[str, Any]:
    """Return a compact project status bundle."""
    started_at, started_perf = _tool_start()
    spec = tool_spec("runops.project.status")
    inputs = {"project_root": project_root}
    try:
        root = _resolve_project_root(project_root)
        context = build_project_context(root)
    except Exception as exc:
        return blocked_envelope(
            tool=spec.name,
            safety=spec.safety,
            code="project_status_failed",
            message=str(exc),
            inputs=inputs,
        )

    runs = context.get("runs", {})
    total_runs = runs.get("total", 0) if isinstance(runs, dict) else 0
    status: EnvelopeStatus = "warning" if context.get("diagnostics") else "ok"
    summary = f"{total_runs} run(s); project status is {context.get('status', 'ok')}."
    warnings = [
        warning("diagnostic", str(item.get("message", "")))
        for item in context.get("diagnostics", [])
        if isinstance(item, dict)
    ]
    return envelope(
        tool=spec.name,
        safety=spec.safety,
        status=status,
        summary=summary,
        data={
            "project": context.get("project", {}),
            "status": context.get("status", "ok"),
            "runs": runs,
            "recent_failures": context.get("recent_failures", []),
            "section_status": context.get("section_status", {}),
        },
        project_root=root,
        warnings=warnings,
        started_at=started_at,
        started_perf=started_perf,
        inputs=inputs,
    )


def project_inspect(project_root: str | None = None) -> dict[str, Any]:
    """Return detailed project metadata and agent context."""
    started_at, started_perf = _tool_start()
    spec = tool_spec("runops.project.inspect")
    inputs = {"project_root": project_root}
    try:
        root = _resolve_project_root(project_root)
        project = load_project(root)
        context = build_project_context(root)
    except Exception as exc:
        return blocked_envelope(
            tool=spec.name,
            safety=spec.safety,
            code="project_inspect_failed",
            message=str(exc),
            inputs=inputs,
        )

    return envelope(
        tool=spec.name,
        safety=spec.safety,
        status="ok",
        summary=f"Project {project.name!r} inspected.",
        data={
            "project": _project_config_payload(project),
            "context": context,
        },
        project_root=root,
        started_at=started_at,
        started_perf=started_perf,
        inputs=inputs,
    )


def project_plugins(
    project_root: str | None = None,
    strict: bool = False,
) -> dict[str, Any]:
    """Return advisory Codex plugin recommendations and metadata checks."""
    started_at, started_perf = _tool_start()
    spec = tool_spec("runops.project.plugins")
    inputs = {"project_root": project_root, "strict": strict}
    try:
        root = _resolve_project_root(project_root)
        check_result = check_project_codex_plugins(root)
    except Exception as exc:
        return blocked_envelope(
            tool=spec.name,
            safety=spec.safety,
            code="project_plugins_failed",
            message=str(exc),
            inputs=inputs,
        )

    errors_count = sum(1 for issue in check_result.issues if issue.severity == "error")
    warnings_count = sum(
        1 for issue in check_result.issues if issue.severity == "warning"
    )
    data = check_result.to_dict()
    data["strict"] = strict

    mcp_errors: list[dict[str, Any]] = []
    mcp_warnings: list[dict[str, Any]] = []
    for issue in check_result.issues:
        message = f"{issue.plugin_name}.{issue.field}: {issue.message}"
        if issue.source:
            message += f" Source: {issue.source}."
        if issue.severity == "error":
            mcp_errors.append(error("codex_plugin_metadata_error", message))
        else:
            mcp_warnings.append(
                warning(
                    "codex_plugin_metadata_warning",
                    message,
                    severity="high" if strict else "medium",
                )
            )

    if errors_count:
        status: EnvelopeStatus = "error"
        summary = (
            "Codex plugin recommendation metadata has "
            f"{errors_count} error(s) and {warnings_count} warning(s)."
        )
    elif warnings_count:
        status = "warning"
        summary = (
            f"Codex plugin recommendation metadata has {warnings_count} warning(s)."
        )
        if strict:
            summary += " Strict metadata check is not clean."
    else:
        status = "ok"
        recommendation_count = len(check_result.inventory.recommendations)
        summary = (
            f"{recommendation_count} Codex plugin recommendation(s); metadata is OK."
        )

    return envelope(
        tool=spec.name,
        safety=spec.safety,
        status=status,
        summary=summary,
        data=data,
        project_root=root,
        warnings=mcp_warnings,
        errors=mcp_errors,
        started_at=started_at,
        started_perf=started_perf,
        inputs=inputs,
    )


def project_doctor(project_root: str | None = None) -> dict[str, Any]:
    """Diagnose project configuration without mutating files."""
    started_at, started_perf = _tool_start()
    spec = tool_spec("runops.project.doctor")
    inputs = {"project_root": project_root}
    try:
        root = _resolve_project_root(project_root)
    except SimctlError as exc:
        return blocked_envelope(
            tool=spec.name,
            safety=spec.safety,
            code="project_not_found",
            message=str(exc),
            inputs=inputs,
        )

    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, message: str, *, severity: str = "error") -> None:
        checks.append(
            {
                "name": name,
                "ok": ok,
                "message": message,
                "severity": "low" if ok else severity,
            }
        )

    try:
        project = load_project(root)
        add("runops.toml", True, f"Project config is valid: {project.name}")
    except SimctlError as exc:
        add("runops.toml", False, str(exc))

    add(
        "simulators.toml",
        (root / "simulators.toml").is_file(),
        "simulators.toml found"
        if (root / "simulators.toml").is_file()
        else "simulators.toml not found",
    )
    add(
        "launchers.toml",
        (root / "launchers.toml").is_file(),
        "launchers.toml found"
        if (root / "launchers.toml").is_file()
        else "launchers.toml not found",
    )
    add(
        "sbatch",
        shutil.which("sbatch") is not None,
        "sbatch is available"
        if shutil.which("sbatch") is not None
        else "sbatch not found in PATH",
        severity="medium",
    )
    try:
        validate_uniqueness(root / "runs")
        add("run_id_uniqueness", True, "No duplicate run_ids")
    except SimctlError as exc:
        add("run_id_uniqueness", False, str(exc))

    if (root / "campaign.toml").is_file():
        add("campaign.toml", True, "campaign.toml found")
    else:
        add("campaign.toml", True, "campaign.toml is optional and missing")

    try:
        plugin_check = check_project_codex_plugins(root)
        errors_count = sum(
            1 for issue in plugin_check.issues if issue.severity == "error"
        )
        warnings_count = sum(
            1 for issue in plugin_check.issues if issue.severity == "warning"
        )
        if errors_count:
            add(
                "codex_plugins",
                False,
                "Codex plugin recommendation metadata has "
                f"{errors_count} error(s) and {warnings_count} warning(s).",
                severity="medium",
            )
        elif warnings_count:
            add(
                "codex_plugins",
                True,
                "Codex plugin recommendation metadata has "
                f"{warnings_count} warning(s); inspect runops.project.plugins.",
            )
        else:
            add(
                "codex_plugins",
                True,
                "Codex plugin recommendation metadata is OK.",
            )
    except Exception as exc:
        add(
            "codex_plugins",
            False,
            f"Codex plugin recommendation metadata check failed: {exc}",
            severity="medium",
        )

    failed = [check for check in checks if not check["ok"]]
    summary = "All checks passed." if not failed else f"{len(failed)} check(s) failed."
    status: EnvelopeStatus = "ok" if not failed else "warning"
    return envelope(
        tool=spec.name,
        safety=spec.safety,
        status=status,
        summary=summary,
        data={"checks": checks, "failed_count": len(failed)},
        project_root=root,
        warnings=[
            warning(str(check["name"]), str(check["message"]), severity="medium")
            for check in failed
        ],
        started_at=started_at,
        started_perf=started_perf,
        inputs=inputs,
    )
