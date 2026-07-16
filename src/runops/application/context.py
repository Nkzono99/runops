"""Project context bundle: single-read summary for AI agents.

Collects project configuration, campaign intent, simulator/launcher info,
run state counts, recent failures, and latest facts into one dictionary
that agents read as their entry point.
"""

from __future__ import annotations

import logging
from importlib import metadata
from pathlib import Path
from typing import Any

import runops
from runops.core.codex_plugin import (
    CODEX_PLUGIN_CHECK_RESULT_SCHEMA_PATH,
    CODEX_PLUGIN_INVENTORY_SCHEMA_PATH,
    CODEX_PLUGIN_INVENTORY_SCHEMA_VERSION,
    codex_plugin_management_policy,
)
from runops.core.exceptions import SimctlError

logger = logging.getLogger(__name__)


def _record_diagnostic(
    diagnostics: list[dict[str, str]],
    section_status: dict[str, str],
    *,
    section: str,
    message: str,
    level: str = "error",
) -> None:
    diagnostics.append(
        {
            "section": section,
            "level": level,
            "message": message,
        }
    )
    section_status[section] = level


def build_project_context(project_root: Path) -> dict[str, Any]:
    """Build a lightweight context bundle for the current project.

    This is the canonical entry point for AI agents.  Instead of reading
    many files individually, agents call this once to get a structured
    overview of the project state.

    Args:
        project_root: Absolute path to the project root directory.

    Returns:
        JSON-serializable dictionary with project overview.
    """
    ctx: dict[str, Any] = {}
    diagnostics: list[dict[str, str]] = []
    section_status: dict[str, str] = {}

    # -- Project basics --
    ctx["project"] = _load_project_info(project_root, diagnostics, section_status)

    # -- Campaign --
    ctx["campaign"] = _load_campaign_info(project_root, diagnostics, section_status)

    # -- Quantity-bounded research workspace --
    ctx["research"] = _collect_research_workspace(
        project_root, diagnostics, section_status
    )

    # -- Simulators & Launchers --
    ctx["simulators"] = _load_simulator_names(project_root, diagnostics, section_status)
    ctx["launchers"] = _load_launcher_names(project_root, diagnostics, section_status)

    # -- Run statistics --
    ctx["runs"] = _collect_run_stats(project_root, diagnostics, section_status)

    # -- Recent failures --
    ctx["recent_failures"] = _collect_recent_failures(
        project_root, diagnostics, section_status
    )

    # -- Facts --
    ctx["facts"] = _collect_facts_summary(project_root, diagnostics, section_status)

    # -- Knowledge index --
    ctx["knowledge"] = _collect_knowledge_paths(
        project_root, diagnostics, section_status
    )

    # -- External Codex plugins --
    ctx["codex_plugins"] = _collect_codex_plugins(
        project_root, diagnostics, section_status
    )

    # -- Available actions --
    try:
        from runops.application.actions import list_actions

        ctx["available_actions"] = [a.to_dict() for a in list_actions()]
    except Exception as exc:
        _record_diagnostic(
            diagnostics,
            section_status,
            section="available_actions",
            message=f"Failed to list action registry: {exc}",
        )
        ctx["available_actions"] = []

    ctx["status"] = "degraded" if diagnostics else "ok"
    ctx["diagnostics"] = diagnostics
    ctx["section_status"] = {
        section: section_status.get(section, "ok")
        for section in (
            "project",
            "campaign",
            "research",
            "simulators",
            "launchers",
            "runs",
            "recent_failures",
            "facts",
            "knowledge",
            "codex_plugins",
            "available_actions",
        )
    }

    return ctx


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------


def _load_project_info(
    root: Path,
    diagnostics: list[dict[str, str]],
    section_status: dict[str, str],
) -> dict[str, Any]:
    try:
        from runops.core.project import load_project

        proj = load_project(root)
        return {
            "name": proj.name,
            "description": proj.description,
            "root": str(root),
            "runops_version": _installed_runops_version(),
            "runops_module": str(Path(runops.__file__).resolve()),
        }
    except SimctlError as exc:
        _record_diagnostic(
            diagnostics,
            section_status,
            section="project",
            message=f"Failed to load project metadata: {exc}",
        )
        return {"name": "", "root": str(root)}


def _installed_runops_version() -> str:
    """Return the installed runops distribution version."""
    try:
        return metadata.version("runops")
    except metadata.PackageNotFoundError:
        return runops.__version__


def _load_campaign_info(
    root: Path,
    diagnostics: list[dict[str, str]],
    section_status: dict[str, str],
) -> dict[str, Any]:
    try:
        from runops.core.campaign import load_campaign

        camp = load_campaign(root)
        if camp is None:
            return {}
        result: dict[str, Any] = {
            "name": camp.name,
            "hypothesis": camp.hypothesis,
            "simulator": camp.simulator,
        }
        if camp.variables:
            result["variables"] = [
                {"name": v.name, "role": v.role, "unit": v.unit} for v in camp.variables
            ]
        if camp.observables:
            result["observables"] = [
                {"name": o.name, "description": o.description} for o in camp.observables
            ]
        return result
    except SimctlError as exc:
        _record_diagnostic(
            diagnostics,
            section_status,
            section="campaign",
            message=f"Failed to load campaign metadata: {exc}",
        )
        return {}


def _collect_research_workspace(
    root: Path,
    diagnostics: list[dict[str, str]],
    section_status: dict[str, str],
) -> dict[str, Any]:
    try:
        from runops.application.research.workspace import inspect_workspace
        from runops.core.project import load_project

        payload = inspect_workspace(
            root,
            budget=load_project(root).research_budget,
        ).to_dict()
        payload["exists"] = (root / "research").is_dir()
        payload["current_path"] = "research/CURRENT.md"
        payload["journal_path"] = "research/journal/active.md"
        payload["results_path"] = "research/results"
        return payload
    except Exception as exc:
        _record_diagnostic(
            diagnostics,
            section_status,
            section="research",
            message=f"Failed to inspect research workspace: {exc}",
            level="warning",
        )
        return {"exists": False, "current_path": "research/CURRENT.md"}


def _load_simulator_names(
    root: Path,
    diagnostics: list[dict[str, str]],
    section_status: dict[str, str],
) -> list[str]:
    try:
        from runops.core.project import load_project

        proj = load_project(root)
        return sorted(proj.simulators.keys())
    except SimctlError as exc:
        _record_diagnostic(
            diagnostics,
            section_status,
            section="simulators",
            message=f"Failed to load simulator list: {exc}",
        )
        return []


def _load_launcher_names(
    root: Path,
    diagnostics: list[dict[str, str]],
    section_status: dict[str, str],
) -> list[str]:
    try:
        from runops.core.project import load_project

        proj = load_project(root)
        return sorted(proj.launchers.keys())
    except SimctlError as exc:
        _record_diagnostic(
            diagnostics,
            section_status,
            section="launchers",
            message=f"Failed to load launcher list: {exc}",
        )
        return []


def _collect_run_stats(
    root: Path,
    diagnostics: list[dict[str, str]],
    section_status: dict[str, str],
) -> dict[str, Any]:
    from runops.core.state import RunState

    runs_dir = root / "runs"
    if not runs_dir.is_dir():
        return {"total": 0}

    try:
        from runops.application.execution.readiness import resolve_run_readiness
        from runops.core.discovery import discover_runs
        from runops.core.manifest import read_manifest

        run_dirs = discover_runs(runs_dir)
        counts: dict[str, int] = {s.value: 0 for s in RunState}
        analysis_ready = 0
        analysis_incomplete = 0
        analysis_unknown = 0
        analysis_problems: list[dict[str, Any]] = []
        for rd in run_dirs:
            try:
                m = read_manifest(rd)
                state = m.run.get("status", "unknown")
                counts[state] = counts.get(state, 0) + 1
                if state == RunState.COMPLETED.value:
                    readiness = resolve_run_readiness(rd, manifest=m)
                    if readiness.analysis_ready:
                        analysis_ready += 1
                    elif readiness.analysis_status == "unknown":
                        analysis_unknown += 1
                    else:
                        analysis_incomplete += 1
                    if not readiness.analysis_ready:
                        analysis_problems.append(
                            {
                                "run_id": readiness.run_id,
                                "run_dir": str(rd),
                                "analysis_status": readiness.analysis_status,
                                "missing_required_artifacts": list(
                                    readiness.missing_required_artifacts
                                ),
                                "warnings": list(readiness.warnings),
                                "reason_codes": list(readiness.reason_codes),
                                "recommended_action": readiness.recommended_action,
                                "recommended_command": readiness.recommended_command,
                                "requires_human": readiness.requires_human,
                            }
                        )
            except SimctlError:
                counts["unknown"] = counts.get("unknown", 0) + 1

        non_zero: dict[str, Any] = {k: v for k, v in counts.items() if v > 0}
        if analysis_ready:
            non_zero["analysis_ready"] = analysis_ready
        if analysis_incomplete:
            non_zero["analysis_incomplete"] = analysis_incomplete
        if analysis_unknown:
            non_zero["analysis_unknown"] = analysis_unknown
        if analysis_problems:
            non_zero["analysis_problems"] = analysis_problems[:10]
        non_zero["total"] = len(run_dirs)
        return non_zero
    except Exception as exc:
        _record_diagnostic(
            diagnostics,
            section_status,
            section="runs",
            message=f"Failed to summarize run states: {exc}",
        )
        return {"total": 0}


def _collect_recent_failures(
    root: Path,
    diagnostics: list[dict[str, str]],
    section_status: dict[str, str],
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    runs_dir = root / "runs"
    if not runs_dir.is_dir():
        return []

    try:
        from runops.core.discovery import discover_runs
        from runops.core.manifest import read_manifest

        failures: list[dict[str, Any]] = []
        for rd in discover_runs(runs_dir):
            try:
                m = read_manifest(rd)
                if m.run.get("status") == "failed":
                    partial_outputs = m.run.get("partial_outputs", {})
                    partial_outputs_data = (
                        partial_outputs if isinstance(partial_outputs, dict) else {}
                    )
                    failures.append(
                        {
                            "run_id": m.run.get("id", ""),
                            "reason": m.run.get("failure_reason", ""),
                            "display_name": m.run.get("display_name", ""),
                            "retry_status": m.run.get("retry_status", ""),
                            "partial_outputs": partial_outputs_data,
                        }
                    )
            except SimctlError:
                continue
        return failures[:limit]
    except Exception as exc:
        _record_diagnostic(
            diagnostics,
            section_status,
            section="recent_failures",
            message=f"Failed to collect recent failures: {exc}",
        )
        return []


def _collect_facts_summary(
    root: Path,
    diagnostics: list[dict[str, str]],
    section_status: dict[str, str],
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    try:
        from runops.core.knowledge import query_facts

        facts = query_facts(root, include_candidates=True)
        return [
            {
                "id": f.id,
                "claim": f.claim,
                "confidence": f.confidence,
                "fact_type": getattr(f, "fact_type", ""),
                "simulator": getattr(f, "simulator", ""),
                "source_run": getattr(f, "source_run", ""),
                "evidence_ref": getattr(f, "evidence_ref", ""),
                "storage": getattr(f, "storage", "local"),
                "transport_source": getattr(f, "transport_source", ""),
            }
            for f in facts[:limit]
        ]
    except Exception as exc:
        _record_diagnostic(
            diagnostics,
            section_status,
            section="facts",
            message=f"Failed to summarize facts: {exc}",
        )
        return []


def _collect_knowledge_paths(
    root: Path,
    diagnostics: list[dict[str, str]],
    section_status: dict[str, str],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    knowledge_dir = root / ".runops" / "knowledge"

    refs_dir = root / "refs"
    if refs_dir.is_dir():
        result["refs_dir"] = str(refs_dir)
        result["refs_repos"] = [p.name for p in refs_dir.iterdir() if p.is_dir()]

    if knowledge_dir.is_dir():
        result["knowledge_dir"] = str(knowledge_dir)
        imports_file = knowledge_dir / "enabled" / "imports.md"
        result["imports_file"] = str(imports_file)
        result["imports_ready"] = imports_file.is_file()

    insights_dir = root / ".runops" / "insights"
    if insights_dir.is_dir():
        from runops.core.knowledge import list_insights

        insights = list_insights(root)
        result["insights_count"] = len(insights)
        recent = sorted(
            insights,
            key=lambda insight: insight.created or "",
            reverse=True,
        )[:5]
        result["recent_insights"] = [
            {
                "name": insight.name,
                "type": insight.type,
                "simulator": insight.simulator,
                "created": insight.created,
            }
            for insight in recent
        ]

    facts_file = root / ".runops" / "facts.toml"
    if facts_file.is_file():
        result["facts_file"] = str(facts_file)

    candidate_facts_dir = knowledge_dir / "candidates" / "facts"
    if candidate_facts_dir.is_dir():
        result["candidate_facts_dir"] = str(candidate_facts_dir)
        result["candidate_fact_sources"] = len(list(candidate_facts_dir.glob("*.toml")))

    try:
        from runops.core.knowledge_source import (
            collect_external_knowledge,
            load_knowledge_config,
        )

        config = load_knowledge_config(root)
        if config is not None:
            result["knowledge_enabled"] = config.enabled
        external_entries = collect_external_knowledge(root)
        if external_entries:
            result["external_knowledge"] = [
                {
                    "name": entry.name,
                    "type": entry.source_type,
                    "kind": entry.kind,
                    "path": str(entry.path),
                    "display_path": entry.display_path,
                    "exists": entry.exists,
                    "profiles_enabled": list(entry.profiles_enabled),
                    "profiles_available": list(entry.profiles_available),
                }
                for entry in external_entries
            ]
            result["knowledge_sources"] = [
                {
                    "name": entry.name,
                    "type": entry.source_type,
                    "kind": entry.kind,
                    "location": entry.display_path,
                    "available": entry.exists,
                    "profiles_enabled": list(entry.profiles_enabled),
                    "profiles_available": list(entry.profiles_available),
                }
                for entry in external_entries
            ]
    except Exception as exc:
        _record_diagnostic(
            diagnostics,
            section_status,
            section="knowledge",
            message=f"Failed to collect knowledge integration details: {exc}",
            level="warning",
        )
        logger.debug("Failed to collect knowledge integration details", exc_info=True)

    return result


def _collect_codex_plugins(
    root: Path,
    diagnostics: list[dict[str, str]],
    section_status: dict[str, str],
) -> dict[str, Any]:
    """Collect advisory Codex plugin recommendations for the project."""
    try:
        from runops.application.gateway.plugins import (
            build_project_codex_plugin_inventory,
            check_codex_plugin_inventory,
        )
        from runops.core.project import load_project

        inventory = build_project_codex_plugin_inventory(load_project(root))
        check_result = check_codex_plugin_inventory(inventory)
        payload = check_result.to_dict()
        issue_level = "error" if not check_result.ok else "warning"
        if check_result.issues:
            _record_diagnostic(
                diagnostics,
                section_status,
                section="codex_plugins",
                level=issue_level,
                message=(
                    "Codex plugin metadata has "
                    f"{payload['summary']['errors']} error(s) and "
                    f"{payload['summary']['warnings']} warning(s); "
                    "inspect runo plugins --check."
                ),
            )
        inventory_payload = payload["inventory"]
        return {
            "schema_version": payload["schema_version"],
            "inventory_schema": inventory_payload["$schema"],
            "check_result_schema": payload["$schema"],
            "ok": payload["ok"],
            "strict_ok": payload["strict_ok"],
            "summary": payload["summary"],
            "simulators": inventory_payload["simulators"],
            "site": inventory_payload["site"],
            "management": inventory_payload["management"],
            "recommendations": inventory_payload["recommendations"],
            "delegated_capabilities": inventory_payload["delegated_capabilities"],
            "collection_issues": inventory_payload["collection_issues"],
            "issues": payload["issues"],
        }
    except Exception as exc:
        _record_diagnostic(
            diagnostics,
            section_status,
            section="codex_plugins",
            message=f"Failed to collect Codex plugin recommendations: {exc}",
            level="warning",
        )
        logger.debug("Failed to collect Codex plugin recommendations", exc_info=True)
        return {
            "schema_version": CODEX_PLUGIN_INVENTORY_SCHEMA_VERSION,
            "inventory_schema": CODEX_PLUGIN_INVENTORY_SCHEMA_PATH,
            "check_result_schema": CODEX_PLUGIN_CHECK_RESULT_SCHEMA_PATH,
            "ok": False,
            "strict_ok": False,
            "summary": {
                "recommendations": 0,
                "errors": 0,
                "warnings": 1,
            },
            "simulators": [],
            "site": "",
            "management": codex_plugin_management_policy(),
            "recommendations": [],
            "delegated_capabilities": {},
            "collection_issues": [],
            "issues": [],
        }
