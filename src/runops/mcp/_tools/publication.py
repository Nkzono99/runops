"""Publication export tools for the runops MCP server."""

from __future__ import annotations

import json
from typing import Any

from runops.core.exceptions import SimctlError
from runops.mcp._tools.common import (
    _broken_publication_export_row,
    _load_json_object,
    _publication_manifest_row,
    _resolve_project_root,
    _resolve_publication_export_dir,
    _safe_limit,
    _slugify_token,
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


def publication_exports_list(
    project_root: str | None = None,
    paper_id: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """List existing publication export manifests without creating files."""
    started_at, started_perf = _tool_start()
    spec = tool_spec("runops.publication.exports.list")
    inputs = {"project_root": project_root, "paper_id": paper_id, "limit": limit}
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

    paper_root = root / "exports" / "papers"
    if not paper_root.is_dir():
        return envelope(
            tool=spec.name,
            safety=spec.safety,
            status="ok",
            summary="No publication exports found.",
            data={"exports": [], "matched_count": 0, "total_count": 0},
            project_root=root,
            started_at=started_at,
            started_perf=started_perf,
            inputs=inputs,
        )

    paper_dirs = [path for path in sorted(paper_root.iterdir()) if path.is_dir()]
    if paper_id:
        token = _slugify_token(paper_id)
        paper_dirs = [path for path in paper_dirs if path.name == token]

    rows: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for paper_dir in paper_dirs:
        for export_dir in sorted(path for path in paper_dir.iterdir() if path.is_dir()):
            manifest_path = export_dir / "manifest.json"
            if not manifest_path.is_file():
                message = (
                    f"Missing manifest.json for {paper_dir.name}/{export_dir.name}"
                )
                rows.append(_broken_publication_export_row(root, export_dir, message))
                warnings.append(warning("manifest_missing", message, severity="low"))
                continue
            try:
                manifest = _load_json_object(manifest_path)
            except (OSError, json.JSONDecodeError, SimctlError) as exc:
                message = f"Invalid manifest {manifest_path}: {exc}"
                rows.append(_broken_publication_export_row(root, export_dir, message))
                warnings.append(warning("manifest_invalid", message))
                continue
            rows.append(_publication_manifest_row(root, export_dir, manifest))

    safe_limit = _safe_limit(limit)
    clipped = rows[:safe_limit]
    if len(rows) > len(clipped):
        warnings.append(
            warning(
                "result_limited",
                f"Returned {len(clipped)} of {len(rows)} publication exports.",
                severity="low",
            )
        )
    status: EnvelopeStatus = "warning" if warnings else "ok"
    return envelope(
        tool=spec.name,
        safety=spec.safety,
        status=status,
        summary=f"{len(rows)} publication export(s) matched.",
        data={
            "exports": clipped,
            "matched_count": len(rows),
            "total_count": sum(
                1
                for paper_dir in paper_dirs
                for path in paper_dir.iterdir()
                if path.is_dir()
            ),
        },
        project_root=root,
        warnings=warnings,
        started_at=started_at,
        started_perf=started_perf,
        inputs=inputs,
    )


def publication_export_inspect(
    project_root: str | None = None,
    export: str | None = None,
    paper_id: str | None = None,
    name: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    """Inspect one publication export manifest without mutating files."""
    started_at, started_perf = _tool_start()
    spec = tool_spec("runops.publication.export.inspect")
    inputs = {
        "project_root": project_root,
        "export": export,
        "paper_id": paper_id,
        "name": name,
        "limit": limit,
    }
    try:
        root = _resolve_project_root(project_root)
        export_dir = _resolve_publication_export_dir(
            root,
            export=export,
            paper_id=paper_id,
            name=name,
        )
    except SimctlError as exc:
        return blocked_envelope(
            tool=spec.name,
            safety=spec.safety,
            code="export_not_found",
            message=str(exc),
            inputs=inputs,
        )

    manifest_path = export_dir / "manifest.json"
    if not export_dir.is_dir() or not manifest_path.is_file():
        return blocked_envelope(
            tool=spec.name,
            safety=spec.safety,
            code="manifest_not_found",
            message=f"Publication export manifest not found: {manifest_path}",
            project_root=root,
            inputs=inputs,
        )

    try:
        manifest = _load_json_object(manifest_path)
    except (OSError, json.JSONDecodeError, SimctlError) as exc:
        message = f"Invalid manifest {manifest_path}: {exc}"
        return envelope(
            tool=spec.name,
            safety=spec.safety,
            status="warning",
            summary=message,
            data={
                "export": _broken_publication_export_row(root, export_dir, message),
                "manifest": {},
                "files": [],
                "file_count": 0,
                "source": {},
            },
            project_root=root,
            warnings=[warning("manifest_invalid", message)],
            errors=[error("manifest_invalid", message)],
            started_at=started_at,
            started_perf=started_perf,
            inputs=inputs,
        )

    files = manifest.get("files", [])
    if not isinstance(files, list):
        files = []
    safe_limit = _safe_limit(limit, default=200)
    clipped_files = [item for item in files if isinstance(item, dict)][:safe_limit]
    warnings = []
    if len(files) > len(clipped_files):
        warnings.append(
            warning(
                "result_limited",
                f"Returned {len(clipped_files)} of {len(files)} exported files.",
                severity="low",
            )
        )
    manifest_warnings = manifest.get("warnings", [])
    if not isinstance(manifest_warnings, list):
        manifest_warnings = []
    for item in manifest_warnings:
        warnings.append(warning("manifest_warning", str(item), severity="low"))

    source = manifest.get("source", {})
    if not isinstance(source, dict):
        source = {}
    return envelope(
        tool=spec.name,
        safety=spec.safety,
        status="warning" if warnings else "ok",
        summary=(
            f"Publication export {export_dir.parent.name}/{export_dir.name} inspected."
        ),
        data={
            "export": _publication_manifest_row(root, export_dir, manifest),
            "manifest": manifest,
            "files": clipped_files,
            "file_count": len(files),
            "source": source,
            "manifest_warnings": manifest_warnings,
        },
        project_root=root,
        warnings=warnings,
        started_at=started_at,
        started_perf=started_perf,
        inputs=inputs,
    )
