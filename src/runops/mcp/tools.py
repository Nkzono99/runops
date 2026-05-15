"""Domain tool implementations for the runops MCP provider."""

from __future__ import annotations

import json
import re
import shutil
import sys
from collections import Counter
from pathlib import Path
from time import perf_counter
from typing import Any

import tomli_w

from runops import __version__
from runops.core.analysis.artifacts import read_artifacts_index
from runops.core.context import build_project_context
from runops.core.discovery import discover_runs, resolve_run, validate_uniqueness
from runops.core.exceptions import SimctlError
from runops.core.manifest import ManifestData, read_manifest
from runops.core.project import ProjectConfig, find_project_root, load_project
from runops.core.readiness import evaluate_run_readiness
from runops.core.state import RunState
from runops.mcp.registry import (
    capabilities_payload,
    exposed_tool_specs,
    tool_spec,
)
from runops.mcp.schemas import (
    CONTRACT_VERSION,
    EnvelopeStatus,
    blocked_envelope,
    envelope,
    error,
    now_iso,
    warning,
)
from runops.slurm.query import SlurmQueryError, query_job_status
from runops.slurm.submit import SlurmNotFoundError

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

_PAPER_REQUEST_TYPES = [
    "analysis_request",
    "figure_request",
    "experiment_request",
    "evidence_gap",
    "export_request",
]
_PAPER_REQUEST_PRIORITIES = ["low", "medium", "high", "urgent"]
_PAPER_REQUEST_STATUSES = [
    "open",
    "planned",
    "in_progress",
    "blocked",
    "done",
    "rejected",
]
_PAPER_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
_PAPER_REQUEST_REQUIRED_FIELDS = (
    "id",
    "type",
    "title",
    "paper_context",
    "desired_artifact",
    "source_link",
    "priority",
    "status",
)


def _tool_start() -> tuple[str, float]:
    return now_iso(), perf_counter()


def _path_from_arg(path: str | None) -> Path:
    return Path(path).expanduser().resolve() if path else Path.cwd().resolve()


def _resolve_project_root(project_root: str | None) -> Path:
    start = _path_from_arg(project_root)
    if (start / "runops.toml").exists():
        return start
    return find_project_root(start)


def _resolve_run_dir(run: str, project_root: Path) -> Path:
    candidate = Path(run).expanduser()
    if candidate.is_absolute() and (candidate / "manifest.toml").exists():
        return candidate.resolve()
    relative = (project_root / candidate).resolve()
    if (relative / "manifest.toml").exists():
        return relative
    cwd_relative = (Path.cwd() / candidate).resolve()
    if (cwd_relative / "manifest.toml").exists():
        return cwd_relative
    return resolve_run(run, project_root / "runs")


def _run_summary(
    run_dir: Path,
    manifest: ManifestData,
    project_root: Path,
) -> dict[str, Any]:
    tags = manifest.classification.get("tags", [])
    if not isinstance(tags, list):
        tags = []
    return {
        "run_id": str(manifest.run.get("id", run_dir.name)),
        "display_name": str(manifest.run.get("display_name", "")),
        "status": str(manifest.run.get("status", "unknown")),
        "path": str(run_dir),
        "relative_path": _relative_or_absolute(run_dir, project_root),
        "origin_case": str(manifest.origin.get("case", "")),
        "origin_survey": str(manifest.origin.get("survey", "")),
        "job_id": str(manifest.job.get("job_id", "")),
        "tags": [str(tag) for tag in tags],
    }


def _relative_or_absolute(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _project_config_payload(project: ProjectConfig) -> dict[str, Any]:
    return {
        "name": project.name,
        "description": project.description,
        "root": str(project.root_dir),
        "simulators": sorted(project.simulators.keys()),
        "launchers": sorted(project.launchers.keys()),
        "knowledge_enabled": (
            project.knowledge.enabled if project.knowledge is not None else False
        ),
    }


def _find_latest_log(work_dir: Path, patterns: list[str]) -> Path | None:
    if not work_dir.is_dir():
        return None
    candidates: list[Path] = []
    for pattern in patterns:
        candidates.extend(path for path in work_dir.glob(pattern) if path.is_file())
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _tail_text(path: Path, lines: int) -> list[str]:
    content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return content[-lines:] if len(content) > lines else content


def _safe_limit(limit: int, *, default: int = 100, maximum: int = 1000) -> int:
    if limit <= 0:
        return default
    return min(limit, maximum)


def _load_json_object(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise SimctlError(f"Invalid JSON object at {path}")
    return data


def _load_toml_object(path: Path) -> dict[str, Any]:
    with open(path, "rb") as f:
        data = tomllib.load(f)
    if not isinstance(data, dict):
        raise SimctlError(f"Invalid TOML object at {path}")
    return data


def _slugify_token(value: str) -> str:
    text = value.strip().lower()
    chars: list[str] = []
    last_dash = False
    for ch in text:
        if ch.isalnum():
            chars.append(ch)
            last_dash = False
            continue
        if (ch in {"-", "_", ".", "/"} or ch.isspace()) and not last_dash:
            chars.append("-")
            last_dash = True
    return "".join(chars).strip("-")


def _clean_string(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text for item in value if (text := _clean_string(item))]


def _publication_manifest_row(
    project_root: Path,
    export_dir: Path,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    export_section = manifest.get("export", {})
    if not isinstance(export_section, dict):
        export_section = {}
    paper_section = manifest.get("paper", {})
    if not isinstance(paper_section, dict):
        paper_section = {}

    paper_id = str(
        manifest.get("paper_id") or paper_section.get("id") or export_dir.parent.name
    )
    export_name = str(
        manifest.get("export_name") or export_section.get("name") or export_dir.name
    )
    export_id = str(export_section.get("id") or f"{paper_id}/{export_name}")
    manifest_warnings = manifest.get("warnings", [])
    if not isinstance(manifest_warnings, list):
        manifest_warnings = []

    return {
        "id": export_id,
        "paper_id": paper_id,
        "export_name": export_name,
        "target_kind": str(manifest.get("target_kind", "")),
        "source_run_ids": _normalize_string_list(manifest.get("source_run_ids", [])),
        "created_at": str(
            manifest.get("created_at") or export_section.get("created_at") or ""
        ),
        "manifest_path": _relative_or_absolute(
            export_dir / "manifest.json", project_root
        ),
        "manifest_abspath": str(export_dir / "manifest.json"),
        "readme_path": _relative_or_absolute(export_dir / "README.md", project_root),
        "readme_abspath": str(export_dir / "README.md"),
        "warning_count": len(manifest_warnings),
        "valid": True,
    }


def _broken_publication_export_row(
    project_root: Path,
    export_dir: Path,
    message: str,
) -> dict[str, Any]:
    paper_id = export_dir.parent.name
    export_name = export_dir.name
    return {
        "id": f"{paper_id}/{export_name}",
        "paper_id": paper_id,
        "export_name": export_name,
        "target_kind": "",
        "source_run_ids": [],
        "created_at": "",
        "manifest_path": _relative_or_absolute(
            export_dir / "manifest.json", project_root
        ),
        "manifest_abspath": str(export_dir / "manifest.json"),
        "readme_path": _relative_or_absolute(export_dir / "README.md", project_root),
        "readme_abspath": str(export_dir / "README.md"),
        "warning_count": 1,
        "valid": False,
        "error": message,
    }


def _resolve_publication_export_dir(
    project_root: Path,
    *,
    export: str | None,
    paper_id: str | None,
    name: str | None,
) -> Path:
    if export:
        candidate = Path(export).expanduser()
        if candidate.is_absolute() and candidate.is_dir():
            return candidate.resolve()
        relative = (project_root / candidate).resolve()
        if relative.is_dir():
            return relative
        parts = export.replace("\\", "/").strip("/").split("/")
        if len(parts) == 2:
            return (
                project_root
                / "exports"
                / "papers"
                / _slugify_token(parts[0])
                / _slugify_token(parts[1])
            ).resolve()

    if paper_id and name:
        return (
            project_root
            / "exports"
            / "papers"
            / _slugify_token(paper_id)
            / _slugify_token(name)
        ).resolve()

    raise SimctlError("Specify export or paper_id + name.")


def _resolve_run_or_survey_target(target: str, project_root: Path) -> tuple[str, Path]:
    candidate = Path(target).expanduser()
    candidates: list[Path] = []
    if candidate.is_absolute():
        candidates.append(candidate.resolve())
    else:
        candidates.append((project_root / candidate).resolve())
        candidates.append((Path.cwd() / candidate).resolve())

    for path in candidates:
        if (path / "manifest.toml").is_file():
            return "run", path
        if path.is_dir() and discover_runs(path):
            return "survey", path

    run_dir = resolve_run(target, project_root / "runs")
    return "run", run_dir


def _resolve_survey_dir(survey: str, project_root: Path) -> Path:
    kind, path = _resolve_run_or_survey_target(survey, project_root)
    if kind != "survey":
        raise SimctlError(f"Target is not a survey directory: {survey}")
    return path


def _artifact_payload(
    project_root: Path,
    base_dir: Path,
    artifact: dict[str, Any],
) -> dict[str, Any]:
    payload = dict(artifact)
    rel_path = str(artifact.get("path", "")).strip()
    payload["relative_path"] = rel_path
    if rel_path:
        artifact_path = (base_dir / rel_path).resolve()
        payload["absolute_path"] = str(artifact_path)
        payload["project_relative_path"] = _relative_or_absolute(
            artifact_path,
            project_root,
        )
    else:
        payload["absolute_path"] = ""
        payload["project_relative_path"] = ""
    return payload


def _flatten_mapping(data: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in data.items():
        flat_key = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            flat.update(_flatten_mapping(value, flat_key))
            continue
        flat[flat_key] = value
    return flat


def _survey_plot_columns_from_aggregate(aggregate: dict[str, Any]) -> list[str]:
    columns: set[str] = set()
    runs = aggregate.get("runs", [])
    if isinstance(runs, list):
        for item in runs:
            if not isinstance(item, dict):
                continue
            row = {
                "run_id": item.get("run_id", ""),
                "display_name": item.get("display_name", ""),
                "status": item.get("status", ""),
            }
            for key in (
                "analysis_status",
                "analysis_ready",
                "simulator_status",
                "summary_available",
                "summary_status",
                "summary_partial",
                "missing_required_artifacts",
            ):
                if key in item:
                    row[key] = item[key]
            flat_metadata = item.get("flat_metadata", {})
            if isinstance(flat_metadata, dict):
                row.update(flat_metadata)
            flat_summary = item.get("flat_summary", {})
            if isinstance(flat_summary, dict):
                row.update(flat_summary)
            columns.update(row)

    preferred = [
        "run_id",
        "display_name",
        "status",
        "analysis_status",
        "analysis_ready",
        "simulator_status",
        "summary_available",
        "summary_status",
        "summary_partial",
        "missing_required_artifacts",
    ]
    return [
        *[column for column in preferred if column in columns],
        *sorted(columns - set(preferred)),
    ]


def _load_paper_requests(project_root: Path) -> tuple[Path, list[dict[str, Any]]]:
    path = project_root / "research" / "paper_requests.toml"
    data = _load_toml_object(path)
    raw_requests = data.get("requests", [])
    if not isinstance(raw_requests, list):
        raise SimctlError("research/paper_requests.toml must contain [[requests]].")
    return path, [item for item in raw_requests if isinstance(item, dict)]


def _paper_request_row(
    request: dict[str, Any],
    *,
    project_root: Path,
    schema_path: Path,
) -> dict[str, Any]:
    row = dict(request)
    row["id"] = str(request.get("id", "")).strip()
    row["type"] = str(request.get("type", "")).strip()
    row["title"] = str(request.get("title", "")).strip()
    row["priority"] = str(request.get("priority", "")).strip() or "medium"
    row["status"] = str(request.get("status", "")).strip() or "open"
    row["schema_path"] = _relative_or_absolute(schema_path, project_root)
    for key in ("related_runs", "related_surveys"):
        row[key] = _normalize_string_list(request.get(key, []))
    return row


def _next_paper_request_id(raw_requests: list[dict[str, Any]]) -> str:
    used = {str(item.get("id", "")).strip() for item in raw_requests}
    for index in range(1, 10000):
        candidate = f"PAPER-REQ-{index:04d}"
        if candidate not in used:
            return candidate
    raise SimctlError("No available paper request id in PAPER-REQ-0001..9999.")


def _paper_request_candidate(
    *,
    raw_requests: list[dict[str, Any]],
    request_id: str | None,
    request_type: str,
    title: str,
    paper_context: str,
    desired_artifact: str,
    source_link: str,
    paper_id: str | None,
    priority: str,
    status: str,
    related_runs: list[str] | None,
    related_surveys: list[str] | None,
    human_gate: bool,
) -> dict[str, Any]:
    resolved_id = _clean_string(request_id) or _next_paper_request_id(raw_requests)
    request: dict[str, Any] = {
        "id": resolved_id,
        "type": _clean_string(request_type),
        "title": _clean_string(title),
        "paper_context": _clean_string(paper_context),
        "desired_artifact": _clean_string(desired_artifact),
        "source_link": _clean_string(source_link),
        "priority": _clean_string(priority) or "medium",
        "status": _clean_string(status) or "open",
        "human_gate": bool(human_gate),
    }
    resolved_paper_id = _clean_string(paper_id)
    if resolved_paper_id:
        request["paper_id"] = resolved_paper_id
    normalized_runs = _normalize_string_list(related_runs or [])
    if normalized_runs:
        request["related_runs"] = normalized_runs
    normalized_surveys = _normalize_string_list(related_surveys or [])
    if normalized_surveys:
        request["related_surveys"] = normalized_surveys
    return request


def _validate_paper_request_candidate(
    request: dict[str, Any],
    *,
    raw_requests: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for field in _PAPER_REQUEST_REQUIRED_FIELDS:
        value = request.get(field, "")
        if not str(value).strip():
            errors.append(
                error(
                    "paper_request_missing_field",
                    f"Paper request field is required: {field}",
                )
            )

    request_id = str(request.get("id", ""))
    if request_id and _PAPER_REQUEST_ID_RE.match(request_id) is None:
        errors.append(
            error(
                "paper_request_invalid_id",
                f"Invalid paper request id: {request_id}",
                hint="Use letters, digits, underscore, dot, colon, or dash.",
            )
        )

    request_type = str(request.get("type", ""))
    if request_type and request_type not in _PAPER_REQUEST_TYPES:
        errors.append(
            error(
                "paper_request_invalid_type",
                f"Invalid paper request type: {request_type}",
                hint="Allowed values: " + ", ".join(_PAPER_REQUEST_TYPES),
            )
        )

    priority = str(request.get("priority", ""))
    if priority and priority not in _PAPER_REQUEST_PRIORITIES:
        errors.append(
            error(
                "paper_request_invalid_priority",
                f"Invalid paper request priority: {priority}",
                hint="Allowed values: " + ", ".join(_PAPER_REQUEST_PRIORITIES),
            )
        )

    status = str(request.get("status", ""))
    if status and status not in _PAPER_REQUEST_STATUSES:
        errors.append(
            error(
                "paper_request_invalid_status",
                f"Invalid paper request status: {status}",
                hint="Allowed values: " + ", ".join(_PAPER_REQUEST_STATUSES),
            )
        )

    duplicate = any(
        str(item.get("id", "")).strip() == request_id for item in raw_requests
    )
    if duplicate:
        warnings.append(
            warning(
                "paper_request_duplicate_id",
                f"Paper request id already exists: {request_id}",
            )
        )
    return errors, warnings


def _paper_request_toml_snippet(request: dict[str, Any]) -> str:
    return tomli_w.dumps({"requests": [request]}).strip() + "\n"


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


def analysis_artifacts(
    target: str,
    project_root: str | None = None,
    kind: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Inspect run or survey analysis artifact rows without collecting outputs."""
    started_at, started_perf = _tool_start()
    spec = tool_spec("runops.analysis.artifacts")
    inputs = {
        "target": target,
        "project_root": project_root,
        "kind": kind,
        "limit": limit,
    }
    try:
        root = _resolve_project_root(project_root)
        target_kind, target_dir = _resolve_run_or_survey_target(target, root)
    except SimctlError as exc:
        return blocked_envelope(
            tool=spec.name,
            safety=spec.safety,
            code="target_not_found",
            message=str(exc),
            inputs=inputs,
        )

    if target_kind == "run":
        index_path = target_dir / "analysis" / "artifacts.toml"
        base_dir = target_dir / "analysis"
    else:
        index_path = target_dir / "summary" / "artifacts.toml"
        base_dir = target_dir / "summary"

    if not index_path.is_file():
        message = f"Artifact index not found: {_relative_or_absolute(index_path, root)}"
        return envelope(
            tool=spec.name,
            safety=spec.safety,
            status="warning",
            summary=message,
            data={
                "target_kind": target_kind,
                "target_path": _relative_or_absolute(target_dir, root),
                "artifacts": [],
                "matched_count": 0,
                "index_path": _relative_or_absolute(index_path, root),
            },
            project_root=root,
            warnings=[warning("artifacts_missing", message)],
            started_at=started_at,
            started_perf=started_perf,
            inputs=inputs,
        )

    try:
        raw_artifacts = read_artifacts_index(index_path)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        message = f"Invalid artifact index {index_path}: {exc}"
        return envelope(
            tool=spec.name,
            safety=spec.safety,
            status="warning",
            summary=message,
            data={"artifacts": [], "matched_count": 0},
            project_root=root,
            warnings=[warning("artifacts_invalid", message)],
            errors=[error("artifacts_invalid", message)],
            started_at=started_at,
            started_perf=started_perf,
            inputs=inputs,
        )

    normalized_kind = kind.strip() if kind else ""
    artifacts = [
        _artifact_payload(root, base_dir, item)
        for item in raw_artifacts
        if not normalized_kind or str(item.get("kind", "")) == normalized_kind
    ]
    safe_limit = _safe_limit(limit)
    clipped = artifacts[:safe_limit]
    warnings = []
    if len(artifacts) > len(clipped):
        warnings.append(
            warning(
                "result_limited",
                f"Returned {len(clipped)} of {len(artifacts)} artifacts.",
                severity="low",
            )
        )
    return envelope(
        tool=spec.name,
        safety=spec.safety,
        status="warning" if warnings else "ok",
        summary=f"{len(artifacts)} artifact(s) matched.",
        data={
            "target_kind": target_kind,
            "target_path": _relative_or_absolute(target_dir, root),
            "index_path": _relative_or_absolute(index_path, root),
            "artifacts": clipped,
            "matched_count": len(artifacts),
        },
        project_root=root,
        warnings=warnings,
        started_at=started_at,
        started_perf=started_perf,
        inputs=inputs,
    )


def survey_summary(
    survey: str,
    project_root: str | None = None,
    include_runs: bool = False,
    limit: int = 100,
) -> dict[str, Any]:
    """Inspect an existing survey_summary.json without collecting summaries."""
    started_at, started_perf = _tool_start()
    spec = tool_spec("runops.survey.summary")
    inputs = {
        "survey": survey,
        "project_root": project_root,
        "include_runs": include_runs,
        "limit": limit,
    }
    try:
        root = _resolve_project_root(project_root)
        survey_dir = _resolve_survey_dir(survey, root)
    except SimctlError as exc:
        return blocked_envelope(
            tool=spec.name,
            safety=spec.safety,
            code="survey_not_found",
            message=str(exc),
            inputs=inputs,
        )

    summary_path = survey_dir / "summary" / "survey_summary.json"
    if not summary_path.is_file():
        message = (
            f"Survey summary not found: {_relative_or_absolute(summary_path, root)}"
        )
        return envelope(
            tool=spec.name,
            safety=spec.safety,
            status="warning",
            summary=message,
            data={
                "survey_path": _relative_or_absolute(survey_dir, root),
                "summary_path": _relative_or_absolute(summary_path, root),
                "runs": [],
            },
            project_root=root,
            warnings=[warning("survey_summary_missing", message)],
            started_at=started_at,
            started_perf=started_perf,
            inputs=inputs,
        )

    try:
        aggregate = _load_json_object(summary_path)
    except (OSError, json.JSONDecodeError, SimctlError) as exc:
        message = f"Invalid survey summary {summary_path}: {exc}"
        return envelope(
            tool=spec.name,
            safety=spec.safety,
            status="warning",
            summary=message,
            data={"runs": []},
            project_root=root,
            warnings=[warning("survey_summary_invalid", message)],
            errors=[error("survey_summary_invalid", message)],
            started_at=started_at,
            started_perf=started_perf,
            inputs=inputs,
        )

    runs = aggregate.get("runs", [])
    if not isinstance(runs, list):
        runs = []
    safe_limit = _safe_limit(limit)
    summary_warnings = aggregate.get("warnings", [])
    if not isinstance(summary_warnings, list):
        summary_warnings = []
    warnings = [
        warning("survey_summary_warning", str(item), severity="low")
        for item in summary_warnings
    ]
    data = {
        "survey_path": _relative_or_absolute(survey_dir, root),
        "summary_path": _relative_or_absolute(summary_path, root),
        "total_runs": aggregate.get("total_runs", len(runs)),
        "summaries_collected": aggregate.get("summaries_collected", 0),
        "missing_summaries": aggregate.get("missing_summaries", 0),
        "state_counts": aggregate.get("state_counts", {}),
        "readiness_counts": aggregate.get("readiness_counts", {}),
        "numeric_stats": aggregate.get("numeric_stats", {}),
        "readiness_issues": aggregate.get("readiness_issues", []),
        "warning_count": len(summary_warnings),
        "run_count": len(runs),
    }
    if include_runs:
        data["runs"] = runs[:safe_limit]
        if len(runs) > safe_limit:
            warnings.append(
                warning(
                    "result_limited",
                    f"Returned {safe_limit} of {len(runs)} survey runs.",
                    severity="low",
                )
            )
    return envelope(
        tool=spec.name,
        safety=spec.safety,
        status="warning" if warnings else "ok",
        summary=f"Survey summary has {len(runs)} run row(s).",
        data=data,
        project_root=root,
        warnings=warnings,
        started_at=started_at,
        started_perf=started_perf,
        inputs=inputs,
    )


def analysis_plot_columns(
    survey: str,
    project_root: str | None = None,
) -> dict[str, Any]:
    """List plot columns from an existing survey_summary.json without collecting."""
    started_at, started_perf = _tool_start()
    spec = tool_spec("runops.analysis.plot_columns")
    inputs = {"survey": survey, "project_root": project_root}
    try:
        root = _resolve_project_root(project_root)
        survey_dir = _resolve_survey_dir(survey, root)
    except SimctlError as exc:
        return blocked_envelope(
            tool=spec.name,
            safety=spec.safety,
            code="survey_not_found",
            message=str(exc),
            inputs=inputs,
        )

    summary_path = survey_dir / "summary" / "survey_summary.json"
    if not summary_path.is_file():
        message = (
            f"Survey summary not found: {_relative_or_absolute(summary_path, root)}"
        )
        return envelope(
            tool=spec.name,
            safety=spec.safety,
            status="warning",
            summary=message,
            data={"columns": []},
            project_root=root,
            warnings=[warning("survey_summary_missing", message)],
            started_at=started_at,
            started_perf=started_perf,
            inputs=inputs,
        )

    try:
        aggregate = _load_json_object(summary_path)
    except (OSError, json.JSONDecodeError, SimctlError) as exc:
        message = f"Invalid survey summary {summary_path}: {exc}"
        return envelope(
            tool=spec.name,
            safety=spec.safety,
            status="warning",
            summary=message,
            data={"columns": []},
            project_root=root,
            warnings=[warning("survey_summary_invalid", message)],
            errors=[error("survey_summary_invalid", message)],
            started_at=started_at,
            started_perf=started_perf,
            inputs=inputs,
        )

    columns = _survey_plot_columns_from_aggregate(aggregate)
    return envelope(
        tool=spec.name,
        safety=spec.safety,
        status="ok",
        summary=f"{len(columns)} plot column(s) available.",
        data={
            "survey_path": _relative_or_absolute(survey_dir, root),
            "summary_path": _relative_or_absolute(summary_path, root),
            "columns": columns,
        },
        project_root=root,
        started_at=started_at,
        started_perf=started_perf,
        inputs=inputs,
    )


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
    duplicate_id = any(
        item["code"] == "paper_request_duplicate_id" for item in validation_warnings
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


def run_list(
    project_root: str | None = None,
    status_filter: str | None = None,
    tag: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    """List runs under a project."""
    started_at, started_perf = _tool_start()
    spec = tool_spec("runops.run.list")
    inputs = {
        "project_root": project_root,
        "status_filter": status_filter,
        "tag": tag,
        "limit": limit,
    }
    try:
        root = _resolve_project_root(project_root)
        run_dirs = discover_runs(root / "runs")
    except SimctlError as exc:
        return blocked_envelope(
            tool=spec.name,
            safety=spec.safety,
            code="run_list_failed",
            message=str(exc),
            inputs=inputs,
        )

    rows: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for run_dir in run_dirs:
        try:
            manifest = read_manifest(run_dir)
        except SimctlError:
            continue
        summary = _run_summary(run_dir, manifest, root)
        counts[str(summary["status"])] += 1
        if status_filter and summary["status"] != status_filter:
            continue
        if tag and tag not in summary["tags"]:
            continue
        rows.append(summary)

    rows.sort(key=lambda item: str(item["run_id"]))
    clipped = rows[: max(limit, 0)]
    warnings = []
    if len(rows) > len(clipped):
        warnings.append(
            warning(
                "result_limited",
                f"Returned {len(clipped)} of {len(rows)} matching runs.",
                severity="low",
            )
        )
    return envelope(
        tool=spec.name,
        safety=spec.safety,
        status="ok",
        summary=f"{len(rows)} run(s) matched.",
        data={
            "runs": clipped,
            "matched_count": len(rows),
            "total_count": len(run_dirs),
            "state_counts": dict(counts),
        },
        project_root=root,
        warnings=warnings,
        started_at=started_at,
        started_perf=started_perf,
        inputs=inputs,
    )


def run_inspect(run: str, project_root: str | None = None) -> dict[str, Any]:
    """Inspect one run."""
    started_at, started_perf = _tool_start()
    spec = tool_spec("runops.run.inspect")
    inputs = {"run": run, "project_root": project_root}
    try:
        root = _resolve_project_root(project_root)
        run_dir = _resolve_run_dir(run, root)
        manifest = read_manifest(run_dir)
    except SimctlError as exc:
        return blocked_envelope(
            tool=spec.name,
            safety=spec.safety,
            code="run_inspect_failed",
            message=str(exc),
            inputs=inputs,
        )

    readiness: dict[str, Any] | None = None
    if manifest.run.get("status") == RunState.COMPLETED.value:
        try:
            details = evaluate_run_readiness(run_dir, manifest=manifest)
            readiness = {
                "analysis_status": details.analysis_status,
                "analysis_ready": details.analysis_ready,
                "missing_required_artifacts": list(details.missing_required_artifacts),
                "warnings": list(details.warnings),
            }
        except SimctlError:
            readiness = None

    return envelope(
        tool=spec.name,
        safety=spec.safety,
        status="ok",
        summary=f"Run {manifest.run.get('id', run_dir.name)} inspected.",
        data={
            "run": _run_summary(run_dir, manifest, root),
            "manifest": manifest.to_dict(),
            "readiness": readiness,
        },
        project_root=root,
        started_at=started_at,
        started_perf=started_perf,
        inputs=inputs,
    )


def run_logs(
    run: str,
    project_root: str | None = None,
    lines: int = 50,
    stderr: bool = False,
) -> dict[str, Any]:
    """Return tail lines from the latest run log."""
    started_at, started_perf = _tool_start()
    spec = tool_spec("runops.run.logs")
    inputs = {
        "run": run,
        "project_root": project_root,
        "lines": lines,
        "stderr": stderr,
    }
    try:
        root = _resolve_project_root(project_root)
        run_dir = _resolve_run_dir(run, root)
        manifest = read_manifest(run_dir)
    except SimctlError as exc:
        return blocked_envelope(
            tool=spec.name,
            safety=spec.safety,
            code="run_logs_failed",
            message=str(exc),
            inputs=inputs,
        )

    job_id = str(manifest.job.get("job_id", ""))
    if stderr:
        patterns = [f"stderr.{job_id}.log", f"*.{job_id}.err", "*.err", "stderr*"]
        stream = "stderr"
    else:
        patterns = [
            f"stdout.{job_id}.log",
            f"*.{job_id}.out",
            "*.out",
            "stdout*",
            "*.log",
        ]
        stream = "stdout"
    log_file = _find_latest_log(run_dir / "work", patterns)
    if log_file is None:
        return blocked_envelope(
            tool=spec.name,
            safety=spec.safety,
            code="log_not_found",
            message=(
                f"No {stream} log found for {manifest.run.get('id', run_dir.name)}."
            ),
            project_root=root,
            inputs=inputs,
        )

    safe_lines = max(1, min(lines, 500))
    try:
        tail = _tail_text(log_file, safe_lines)
    except OSError as exc:
        return blocked_envelope(
            tool=spec.name,
            safety=spec.safety,
            code="log_read_failed",
            message=str(exc),
            project_root=root,
            inputs=inputs,
        )

    return envelope(
        tool=spec.name,
        safety=spec.safety,
        status="ok",
        summary=f"Last {len(tail)} line(s) from {log_file.name}.",
        data={
            "run_id": str(manifest.run.get("id", run_dir.name)),
            "stream": stream,
            "log_file": str(log_file),
            "lines": tail,
        },
        project_root=root,
        started_at=started_at,
        started_perf=started_perf,
        inputs=inputs,
    )


def slurm_queue(
    project_root: str | None = None,
    all_states: bool = False,
    live: bool = False,
) -> dict[str, Any]:
    """List Slurm job records known to project manifests."""
    started_at, started_perf = _tool_start()
    spec = tool_spec("runops.slurm.queue")
    inputs = {"project_root": project_root, "all_states": all_states, "live": live}
    try:
        root = _resolve_project_root(project_root)
        run_dirs = discover_runs(root / "runs")
    except SimctlError as exc:
        return blocked_envelope(
            tool=spec.name,
            safety=spec.safety,
            code="slurm_queue_failed",
            message=str(exc),
            inputs=inputs,
        )

    active_states = {RunState.SUBMITTED.value, RunState.RUNNING.value}
    jobs: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for run_dir in run_dirs:
        try:
            manifest = read_manifest(run_dir)
        except SimctlError:
            continue
        run_status = str(manifest.run.get("status", "unknown"))
        job_id = str(manifest.job.get("job_id", ""))
        if not all_states and run_status not in active_states:
            continue
        if not job_id and not all_states:
            continue
        job: dict[str, Any] = {
            "job_id": job_id,
            "run_id": str(manifest.run.get("id", run_dir.name)),
            "run_status": run_status,
            "run_dir": str(run_dir),
            "submitted_at": str(manifest.job.get("submitted_at", "")),
            "partition": str(
                manifest.job.get("partition", manifest.job.get("queue", ""))
            ),
            "qos": str(manifest.job.get("qos", "")),
            "last_slurm_state": str(manifest.run.get("last_slurm_state", "")),
        }
        if live and job_id:
            try:
                live_status = query_job_status(job_id)
                job["live_slurm_state"] = live_status.slurm_state
                job["live_run_state"] = live_status.run_state.value
            except (SlurmNotFoundError, SlurmQueryError) as exc:
                warnings.append(
                    warning(
                        "slurm_query_failed",
                        f"{job_id}: {exc}",
                        severity="medium",
                    )
                )
        jobs.append(job)

    jobs.sort(key=lambda item: str(item["run_id"]))
    active = sum(1 for job in jobs if job["run_status"] in active_states)
    return envelope(
        tool=spec.name,
        safety=spec.safety,
        status="warning" if warnings else "ok",
        summary=f"{active} active job(s), {len(jobs)} listed.",
        data={"jobs": jobs, "active_count": active, "total_listed": len(jobs)},
        project_root=root,
        warnings=warnings,
        started_at=started_at,
        started_perf=started_perf,
        inputs=inputs,
    )


def slurm_job_inspect(job_id: str) -> dict[str, Any]:
    """Inspect a Slurm job through squeue/sacct."""
    started_at, started_perf = _tool_start()
    spec = tool_spec("runops.slurm.job.inspect")
    inputs = {"job_id": job_id}
    try:
        job_status = query_job_status(job_id)
    except (SlurmNotFoundError, SlurmQueryError) as exc:
        return blocked_envelope(
            tool=spec.name,
            safety=spec.safety,
            code="slurm_job_query_failed",
            message=str(exc),
            inputs=inputs,
        )

    return envelope(
        tool=spec.name,
        safety=spec.safety,
        status="ok",
        summary=f"Job {job_id} is {job_status.slurm_state}.",
        data={
            "job_id": job_id,
            "slurm_state": job_status.slurm_state,
            "run_state": job_status.run_state.value,
            "failure_reason": job_status.failure_reason,
            "exit_code": job_status.exit_code,
        },
        started_at=started_at,
        started_perf=started_perf,
        inputs=inputs,
    )


def job_plan_submit(
    run: str,
    project_root: str | None = None,
    queue_name: str | None = None,
    qos: str | None = None,
    afterok: str | None = None,
) -> dict[str, Any]:
    """Plan an sbatch submission command without submitting it."""
    started_at, started_perf = _tool_start()
    spec = tool_spec("runops.job.plan_submit")
    inputs = {
        "run": run,
        "project_root": project_root,
        "queue_name": queue_name,
        "qos": qos,
        "afterok": afterok,
    }
    try:
        root = _resolve_project_root(project_root)
        run_dir = _resolve_run_dir(run, root)
        manifest = read_manifest(run_dir)
    except SimctlError as exc:
        return blocked_envelope(
            tool=spec.name,
            safety=spec.safety,
            code="plan_submit_failed",
            message=str(exc),
            inputs=inputs,
        )

    preconditions: list[dict[str, Any]] = []

    def add_precondition(name: str, ok: bool, message: str) -> None:
        preconditions.append({"name": name, "ok": ok, "message": message})

    status = str(manifest.run.get("status", ""))
    add_precondition(
        "state_created",
        status == RunState.CREATED.value,
        f"run status is {status!r}",
    )
    job_script = run_dir / "submit" / "job.sh"
    add_precondition(
        "job_script_exists",
        job_script.is_file(),
        f"job script: {job_script}",
    )
    if job_script.is_file():
        try:
            job_text = job_script.read_text(encoding="utf-8")
            add_precondition(
                "job_script_has_sbatch",
                "#SBATCH" in job_text,
                "job.sh contains #SBATCH directives"
                if "#SBATCH" in job_text
                else "job.sh does not contain #SBATCH directives",
            )
        except OSError as exc:
            add_precondition("job_script_readable", False, str(exc))
    input_dir = run_dir / "input"
    input_ready = input_dir.is_dir() and any(input_dir.iterdir())
    add_precondition(
        "input_ready",
        input_ready,
        f"input directory: {input_dir}",
    )

    work_dir = run_dir / "work"
    if not work_dir.is_dir():
        work_dir = run_dir
    command = ["sbatch", f"--chdir={work_dir}"]
    if afterok:
        command.append(f"--dependency=afterok:{afterok}")
    if queue_name:
        command.append(f"--partition={queue_name}")
    if qos:
        command.append(f"--qos={qos}")
    command.append(str(job_script))

    failed = [item for item in preconditions if not item["ok"]]
    data = {
        "run_id": str(manifest.run.get("id", run_dir.name)),
        "run_dir": str(run_dir),
        "job_script": str(job_script),
        "work_dir": str(work_dir),
        "command": command,
        "preconditions": preconditions,
        "dry_run": True,
        "will_submit": not failed,
    }
    if failed:
        return envelope(
            tool=spec.name,
            safety=spec.safety,
            status="blocked",
            summary=f"Submission plan is blocked by {len(failed)} precondition(s).",
            data=data,
            project_root=root,
            errors=[
                error(
                    "precondition_failed",
                    f"{item['name']}: {item['message']}",
                )
                for item in failed
            ],
            started_at=started_at,
            started_perf=started_perf,
            inputs=inputs,
        )

    return envelope(
        tool=spec.name,
        safety=spec.safety,
        status="ok",
        summary=f"Run {manifest.run.get('id', run_dir.name)} is ready to submit.",
        data=data,
        project_root=root,
        next_actions=[
            {
                "title": "Submit the planned job",
                "kind": "apply",
                "tool": "runops.job.submit",
                "arguments": {
                    "run": str(manifest.run.get("id", run_dir.name)),
                    "confirm": True,
                    "dry_run": False,
                },
                "requires_user": True,
            }
        ],
        started_at=started_at,
        started_perf=started_perf,
        inputs=inputs,
    )
