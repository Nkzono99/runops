"""Paper-facing request tools for the runops MCP server."""

from __future__ import annotations

import sys
from typing import Any

from runops.core.exceptions import SimctlError
from runops.mcp._tools.common import (
    _PAPER_REQUEST_PRIORITIES,
    _PAPER_REQUEST_STATUSES,
    _PAPER_REQUEST_TYPES,
    _load_paper_requests,
    _next_paper_request_id,
    _paper_request_candidate,
    _paper_request_row,
    _paper_request_toml_snippet,
    _relative_or_absolute,
    _resolve_project_root,
    _safe_limit,
    _tool_start,
    _validate_paper_request_candidate,
)
from runops.mcp.registry import tool_spec
from runops.mcp.schemas import blocked_envelope, envelope, error, warning

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


def paper_requests_list(
    project_root: str | None = None,
    paper_id: str | None = None,
    status_filter: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """List paper-facing requests from research/paper_requests.toml."""
    started_at, started_perf = _tool_start()
    spec = tool_spec("runops.paper.requests.list")
    inputs = {
        "project_root": project_root,
        "paper_id": paper_id,
        "status_filter": status_filter,
        "limit": limit,
    }
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

    schema_path = root / "research" / "paper_requests.toml"
    if not schema_path.is_file():
        message = "research/paper_requests.toml not found."
        return envelope(
            tool=spec.name,
            safety=spec.safety,
            status="warning",
            summary=message,
            data={
                "requests": [],
                "matched_count": 0,
                "schema_path": _relative_or_absolute(schema_path, root),
            },
            project_root=root,
            warnings=[warning("paper_requests_missing", message, severity="low")],
            started_at=started_at,
            started_perf=started_perf,
            inputs=inputs,
        )

    try:
        schema_path, raw_requests = _load_paper_requests(root)
    except (OSError, tomllib.TOMLDecodeError, SimctlError) as exc:
        message = f"Invalid paper request file {schema_path}: {exc}"
        return envelope(
            tool=spec.name,
            safety=spec.safety,
            status="warning",
            summary=message,
            data={"requests": [], "matched_count": 0},
            project_root=root,
            warnings=[warning("paper_requests_invalid", message)],
            errors=[error("paper_requests_invalid", message)],
            started_at=started_at,
            started_perf=started_perf,
            inputs=inputs,
        )

    rows = [
        _paper_request_row(item, project_root=root, schema_path=schema_path)
        for item in raw_requests
    ]
    if paper_id:
        rows = [row for row in rows if str(row.get("paper_id", "")) == paper_id]
    if status_filter:
        rows = [row for row in rows if row["status"] == status_filter]
    safe_limit = _safe_limit(limit)
    clipped = rows[:safe_limit]
    warnings = []
    if len(rows) > safe_limit:
        warnings.append(
            warning(
                "result_limited",
                f"Returned {safe_limit} of {len(rows)} paper requests.",
                severity="low",
            )
        )
    return envelope(
        tool=spec.name,
        safety=spec.safety,
        status="warning" if warnings else "ok",
        summary=f"{len(rows)} paper request(s) matched.",
        data={
            "requests": clipped,
            "matched_count": len(rows),
            "schema_path": _relative_or_absolute(schema_path, root),
        },
        project_root=root,
        warnings=warnings,
        started_at=started_at,
        started_perf=started_perf,
        inputs=inputs,
    )


def paper_request_draft(
    project_root: str | None = None,
    request_id: str | None = None,
    request_type: str = "analysis_request",
    title: str = "",
    paper_context: str = "",
    desired_artifact: str = "",
    source_link: str = "",
    paper_id: str | None = None,
    priority: str = "medium",
    status: str = "open",
    related_runs: list[str] | None = None,
    related_surveys: list[str] | None = None,
    human_gate: bool = True,
) -> dict[str, Any]:
    """Draft and validate a paper-facing request without mutating files."""
    started_at, started_perf = _tool_start()
    spec = tool_spec("runops.paper.request.draft")
    inputs = {
        "project_root": project_root,
        "request_id": request_id,
        "request_type": request_type,
        "title": title,
        "paper_context": paper_context,
        "desired_artifact": desired_artifact,
        "source_link": source_link,
        "paper_id": paper_id,
        "priority": priority,
        "status": status,
        "related_runs": related_runs,
        "related_surveys": related_surveys,
        "human_gate": human_gate,
    }
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

    schema_path = root / "research" / "paper_requests.toml"
    queue_exists = schema_path.is_file()
    raw_requests: list[dict[str, Any]] = []
    if queue_exists:
        try:
            _, raw_requests = _load_paper_requests(root)
        except (OSError, tomllib.TOMLDecodeError, SimctlError) as exc:
            message = f"Invalid paper request file {schema_path}: {exc}"
            return envelope(
                tool=spec.name,
                safety=spec.safety,
                status="warning",
                summary=message,
                data={
                    "valid": False,
                    "request": {},
                    "toml_snippet": "",
                    "target_path": _relative_or_absolute(schema_path, root),
                    "existing_queue": {
                        "exists": True,
                        "request_count": 0,
                        "duplicate_id": False,
                    },
                    "will_mutate_files": False,
                },
                project_root=root,
                warnings=[warning("paper_requests_invalid", message)],
                errors=[error("paper_requests_invalid", message)],
                started_at=started_at,
                started_perf=started_perf,
                inputs=inputs,
            )

    try:
        request = _paper_request_candidate(
            raw_requests=raw_requests,
            request_id=request_id,
            request_type=request_type,
            title=title,
            paper_context=paper_context,
            desired_artifact=desired_artifact,
            source_link=source_link,
            paper_id=paper_id,
            priority=priority,
            status=status,
            related_runs=related_runs,
            related_surveys=related_surveys,
            human_gate=human_gate,
        )
    except SimctlError as exc:
        return blocked_envelope(
            tool=spec.name,
            safety=spec.safety,
            code="paper_request_id_unavailable",
            message=str(exc),
            project_root=root,
            inputs=inputs,
        )

    validation_errors, validation_warnings = _validate_paper_request_candidate(
        request,
        raw_requests=raw_requests,
    )
    validation_items = [*validation_errors, *validation_warnings]
    duplicate_id = any(
        item["code"] == "paper_request_duplicate_id" for item in validation_items
    )
    suggested_request_id = (
        _next_paper_request_id(raw_requests) if duplicate_id else request["id"]
    )
    is_valid = not validation_errors
    snippet = _paper_request_toml_snippet(request) if is_valid else ""
    summary = (
        f"Paper request {request['id']} is ready to append without side effects."
        if is_valid
        else f"Paper request {request['id']} has validation errors."
    )
    next_actions = []
    if is_valid:
        next_actions.append(
            {
                "title": "Append the TOML snippet to research/paper_requests.toml",
                "kind": "plan",
                "target": _relative_or_absolute(schema_path, root),
                "requires_user": True,
            }
        )
    return envelope(
        tool=spec.name,
        safety=spec.safety,
        status="warning" if validation_errors or validation_warnings else "ok",
        summary=summary,
        data={
            "valid": is_valid,
            "request": request,
            "suggested_request_id": suggested_request_id,
            "toml_snippet": snippet,
            "target_path": _relative_or_absolute(schema_path, root),
            "existing_queue": {
                "exists": queue_exists,
                "request_count": len(raw_requests),
                "duplicate_id": duplicate_id,
            },
            "allowed_values": {
                "type": _PAPER_REQUEST_TYPES,
                "priority": _PAPER_REQUEST_PRIORITIES,
                "status": _PAPER_REQUEST_STATUSES,
            },
            "will_mutate_files": False,
        },
        project_root=root,
        warnings=validation_warnings,
        errors=validation_errors,
        next_actions=next_actions,
        started_at=started_at,
        started_perf=started_perf,
        inputs=inputs,
    )


def paper_request_plan(
    request_id: str,
    project_root: str | None = None,
) -> dict[str, Any]:
    """Plan how to route one paper-facing request without mutating files."""
    started_at, started_perf = _tool_start()
    spec = tool_spec("runops.paper.request.plan")
    inputs = {"request_id": request_id, "project_root": project_root}
    try:
        root = _resolve_project_root(project_root)
        schema_path, raw_requests = _load_paper_requests(root)
    except (OSError, tomllib.TOMLDecodeError, SimctlError) as exc:
        return blocked_envelope(
            tool=spec.name,
            safety=spec.safety,
            code="paper_requests_unavailable",
            message=str(exc),
            inputs=inputs,
        )

    rows = [
        _paper_request_row(item, project_root=root, schema_path=schema_path)
        for item in raw_requests
    ]
    request = next((row for row in rows if row["id"] == request_id), None)
    if request is None:
        return blocked_envelope(
            tool=spec.name,
            safety=spec.safety,
            code="paper_request_not_found",
            message=f"Paper request not found: {request_id}",
            project_root=root,
            inputs=inputs,
        )

    request_type = str(request.get("type", ""))
    proposal_needed = request_type in {"experiment_request", "evidence_gap"}
    route = "research/agenda.md"
    if proposal_needed or request.get("human_gate"):
        route = "research/proposals/"
    planned_actions = [
        {
            "title": "Review the paper request",
            "kind": "plan",
            "target": request["id"],
            "requires_user": True,
        },
        {
            "title": f"Record current decision in {route}",
            "kind": "plan",
            "target": route,
            "requires_user": True,
        },
    ]
    if request_type == "export_request":
        planned_actions.append(
            {
                "title": "Inspect available publication exports",
                "kind": "plan",
                "tool": "runops.publication.exports.list",
                "requires_user": False,
            }
        )
    elif request_type in {"analysis_request", "figure_request"}:
        planned_actions.append(
            {
                "title": "Inspect analysis artifacts and survey summaries",
                "kind": "plan",
                "tool": "runops.analysis.artifacts",
                "requires_user": False,
            }
        )
    elif request_type == "experiment_request":
        planned_actions.append(
            {
                "title": "Design a case or survey; do not submit jobs automatically",
                "kind": "plan",
                "requires_user": True,
            }
        )

    return envelope(
        tool=spec.name,
        safety=spec.safety,
        status="ok",
        summary=f"Paper request {request_id} planned without side effects.",
        data={
            "request": request,
            "route": route,
            "will_submit": False,
            "will_mutate_files": False,
        },
        project_root=root,
        next_actions=planned_actions,
        started_at=started_at,
        started_perf=started_perf,
        inputs=inputs,
    )
