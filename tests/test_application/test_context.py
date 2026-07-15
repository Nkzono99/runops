"""Tests for project context bundles exposed to AI agents."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import tomli_w

from runops.application.context import (
    _collect_codex_plugins,
    _collect_facts_summary,
    _collect_knowledge_paths,
    _collect_recent_failures,
    _collect_research_workspace,
    _collect_run_stats,
    _load_campaign_info,
    _load_launcher_names,
    _load_project_info,
    _load_simulator_names,
    build_project_context,
)
from runops.core.exceptions import SimctlError


def _write_toml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        tomli_w.dump(data, f)


def test_context_includes_knowledge_integration_details(tmp_path: Path) -> None:
    _write_toml(
        tmp_path / "runops.toml",
        {
            "project": {"name": "test-project"},
            "knowledge": {
                "enabled": True,
                "mount_dir": "refs/knowledge",
                "derived_dir": ".runops/knowledge",
                "sources": [
                    {
                        "name": "shared-kb",
                        "type": "path",
                        "kind": "profiles",
                        "path": "../shared-kb",
                        "mount": "refs/knowledge/shared-kb",
                        "profiles": ["common"],
                    },
                    {
                        "name": "other-project",
                        "type": "path",
                        "kind": "project",
                        "path": "../other-project",
                    },
                ],
            },
        },
    )

    mounted_kb = tmp_path / "refs" / "knowledge" / "shared-kb"
    (mounted_kb / "profiles").mkdir(parents=True)
    (mounted_kb / "profiles" / "common.md").write_text("# Common\n", encoding="utf-8")

    imports_path = tmp_path / ".runops" / "knowledge" / "enabled" / "imports.md"
    imports_path.parent.mkdir(parents=True, exist_ok=True)
    imports_path.write_text("@refs/knowledge/shared-kb/profiles/common.md\n")

    insight_path = tmp_path / ".runops" / "insights" / "result_note.md"
    insight_path.parent.mkdir(parents=True, exist_ok=True)
    insight_path.write_text(
        "---\n"
        "type: result\n"
        "simulator: emses\n"
        "created: 2026-04-01\n"
        "---\n\n"
        "Survey summary.\n",
        encoding="utf-8",
    )

    other_project = tmp_path.parent / "other-project"
    other_project.mkdir(parents=True, exist_ok=True)

    _write_toml(
        tmp_path / ".runops" / "facts.toml",
        {
            "facts": [
                {
                    "id": "f001",
                    "claim": "initial fact",
                    "fact_type": "observation",
                    "confidence": "low",
                },
                {
                    "id": "f002",
                    "claim": "refined fact",
                    "fact_type": "constraint",
                    "confidence": "high",
                    "supersedes": "f001",
                    "source_run": "R20260401-0001",
                    "evidence_ref": "run:R20260401-0001",
                },
            ]
        },
    )

    ctx = build_project_context(tmp_path)

    assert ctx["project"]["name"] == "test-project"
    assert [fact["id"] for fact in ctx["facts"]] == ["f002"]
    assert ctx["facts"][0]["source_run"] == "R20260401-0001"

    knowledge = ctx["knowledge"]
    assert knowledge["imports_ready"] is True
    assert knowledge["knowledge_enabled"] is True
    assert knowledge["insights_count"] == 1
    assert knowledge["recent_insights"][0]["name"] == "result_note"
    assert len(knowledge["external_knowledge"]) == 2
    assert knowledge["external_knowledge"][0]["kind"] == "project"
    shared = next(
        source
        for source in knowledge["knowledge_sources"]
        if source["name"] == "shared-kb"
    )
    assert shared["kind"] == "profiles"
    assert shared["available"] is True
    assert shared["profiles_available"] == ["common"]
    other = next(
        source
        for source in knowledge["knowledge_sources"]
        if source["name"] == "other-project"
    )
    assert other["kind"] == "project"

    actions = {action["name"]: action for action in ctx["available_actions"]}
    assert actions["submit_run"]["required_params"] == ["run_dir"]
    assert actions["submit_run"]["preconditions"] == [
        "run state == created",
        "job.sh exists",
    ]
    assert actions["archive_run"]["destructive"] is True
    assert actions["purge_work"]["state_change"] == "archived -> purged"
    assert actions["archive_run"]["requires_confirmation"] is True
    assert actions["submit_run"]["risk_level"] == "high"
    assert "confirmation_conditions" in actions["retry_run"]
    assert actions["save_insight"]["required_params"] == [
        "project_root",
        "name",
        "content",
    ]


def test_context_includes_codex_plugin_recommendations(tmp_path: Path) -> None:
    """Agent context includes advisory external Codex plugin inventory."""
    _write_toml(
        tmp_path / "runops.toml",
        {
            "project": {
                "name": "plugin-context",
                "codex_plugins": {
                    "analysis-context": {
                        "display_name": "Analysis Context",
                        "reason": "Team analysis workflow guidance.",
                        "install_hint": "codex plugin add analysis-context@project",
                    }
                },
            },
        },
    )
    _write_toml(
        tmp_path / "simulators.toml",
        {
            "simulators": {
                "production": {
                    "adapter": "emses",
                    "resolver_mode": "package",
                    "executable": "mpiemses3D",
                }
            }
        },
    )
    _write_toml(
        tmp_path / "site.toml",
        {
            "site": {
                "name": "test-site",
                "codex_plugins": {
                    "site-context": {
                        "display_name": "Site Context",
                        "reason": "Site-local workflow guidance.",
                        "install_hint": "codex plugin add site-context@test",
                    }
                },
            }
        },
    )

    ctx = build_project_context(tmp_path)

    plugins = ctx["codex_plugins"]
    assert plugins["schema_version"] == 1
    assert plugins["inventory_schema"] == "schemas/codex-plugin-inventory.json"
    assert plugins["check_result_schema"] == "schemas/codex-plugin-check-result.json"
    assert plugins["ok"] is True
    assert plugins["strict_ok"] is True
    assert plugins["summary"] == {
        "recommendations": 4,
        "errors": 0,
        "warnings": 0,
    }
    assert plugins["management"]["runops_installs_plugins"] is False
    assert plugins["simulators"] == ["production"]
    assert plugins["site"] == "test-site"
    assert [plugin["name"] for plugin in plugins["recommendations"]] == [
        "mpiemses3d-context",
        "emout-context",
        "analysis-context",
        "site-context",
    ]
    assert plugins["recommendations"][0]["sources"] == [
        "simulator:emses",
        "simulator:production",
    ]
    assert "parameter-design" in plugins["recommendations"][0]["capabilities"]
    assert plugins["delegated_capabilities"]["parameter-design"] == [
        "mpiemses3d-context"
    ]
    assert plugins["delegated_capabilities"]["output-analysis"] == [
        "mpiemses3d-context",
        "emout-context",
    ]
    assert plugins["collection_issues"] == []
    assert plugins["issues"] == []
    assert ctx["section_status"]["codex_plugins"] == "ok"


def test_context_surfaces_codex_plugin_metadata_warnings(tmp_path: Path) -> None:
    """Agent context keeps plugin collection warnings visible."""
    _write_toml(tmp_path / "runops.toml", {"project": {"name": "plugin-context"}})
    (tmp_path / "site.toml").write_text(
        '[site]\nname = "test-site"\ncodex_plugins = ["broken"]\n',
        encoding="utf-8",
    )

    ctx = build_project_context(tmp_path)

    plugins = ctx["codex_plugins"]
    assert ctx["status"] == "degraded"
    assert ctx["section_status"]["codex_plugins"] == "warning"
    assert plugins["ok"] is True
    assert plugins["strict_ok"] is False
    assert plugins["summary"] == {
        "recommendations": 0,
        "errors": 0,
        "warnings": 1,
    }
    assert plugins["collection_issues"][0]["source"] == "site:test-site"
    assert plugins["issues"][0]["field"] == "codex_plugins"
    assert any(
        "runo plugins --check" in diagnostic["message"]
        for diagnostic in ctx["diagnostics"]
        if diagnostic["section"] == "codex_plugins"
    )


def test_context_surfaces_codex_plugin_metadata_errors(tmp_path: Path) -> None:
    """Agent context marks incomplete plugin metadata as an error."""
    _write_toml(tmp_path / "runops.toml", {"project": {"name": "plugin-context"}})
    (tmp_path / "site.toml").write_text(
        '[site]\nname = "test-site"\n'
        "[site.codex_plugins.incomplete]\n"
        'display_name = "Incomplete Plugin"\n',
        encoding="utf-8",
    )

    ctx = build_project_context(tmp_path)

    plugins = ctx["codex_plugins"]
    assert ctx["status"] == "degraded"
    assert ctx["section_status"]["codex_plugins"] == "error"
    assert plugins["ok"] is False
    assert plugins["strict_ok"] is False
    assert plugins["summary"] == {
        "recommendations": 1,
        "errors": 2,
        "warnings": 0,
    }
    assert [issue["field"] for issue in plugins["issues"]] == [
        "reason",
        "install_hint",
    ]


def test_collect_codex_plugins_reports_warning_on_broken_project(
    tmp_path: Path,
) -> None:
    """Broken project config degrades context instead of hiding other sections."""
    diagnostics: list[dict[str, str]] = []
    section_status: dict[str, str] = {}

    plugins = _collect_codex_plugins(tmp_path, diagnostics, section_status)

    assert plugins["schema_version"] == 1
    assert plugins["inventory_schema"] == "schemas/codex-plugin-inventory.json"
    assert plugins["check_result_schema"] == "schemas/codex-plugin-check-result.json"
    assert plugins["ok"] is False
    assert plugins["strict_ok"] is False
    assert plugins["summary"] == {
        "recommendations": 0,
        "errors": 0,
        "warnings": 1,
    }
    assert plugins["simulators"] == []
    assert plugins["site"] == ""
    assert plugins["management"]["runops_installs_plugins"] is False
    assert plugins["recommendations"] == []
    assert plugins["delegated_capabilities"] == {}
    assert plugins["collection_issues"] == []
    assert plugins["issues"] == []
    assert section_status["codex_plugins"] == "warning"
    assert diagnostics[0]["section"] == "codex_plugins"


def test_context_includes_bounded_research_workspace(tmp_path: Path) -> None:
    _write_toml(tmp_path / "runops.toml", {"project": {"name": "research-project"}})
    (tmp_path / "research/journal/archive").mkdir(parents=True)
    (tmp_path / "research/results").mkdir()
    (tmp_path / "research/archive/results").mkdir(parents=True)
    (tmp_path / "research/CURRENT.md").write_text("# Current\n", encoding="utf-8")
    (tmp_path / "research/journal/active.md").write_text(
        "# Research Journal\n\n", encoding="utf-8"
    )

    ctx = build_project_context(tmp_path)

    assert ctx["research"]["exists"] is True
    assert ctx["research"]["current_chars"] == len("# Current\n")
    assert ctx["research"]["journal_chars"] == len("# Research Journal\n\n")
    assert ctx["research"]["active_result_count"] == 0
    assert ctx["section_status"]["research"] == "ok"


def test_context_reports_diagnostics_for_broken_sections(tmp_path: Path) -> None:
    _write_toml(
        tmp_path / "runops.toml",
        {
            "project": {"name": "broken-project"},
        },
    )
    facts_path = tmp_path / ".runops" / "facts.toml"
    facts_path.parent.mkdir(parents=True, exist_ok=True)
    facts_path.write_text("not valid toml", encoding="utf-8")

    ctx = build_project_context(tmp_path)

    assert ctx["status"] == "degraded"
    assert ctx["facts"] == []
    assert ctx["section_status"]["facts"] == "error"
    assert any(diagnostic["section"] == "facts" for diagnostic in ctx["diagnostics"])


def test_context_research_helper_reports_missing_state(
    tmp_path: Path,
) -> None:
    diagnostics: list[dict[str, str]] = []
    section_status: dict[str, str] = {}

    _write_toml(tmp_path / "runops.toml", {"project": {"name": "empty"}})
    research = _collect_research_workspace(tmp_path, diagnostics, section_status)

    assert research["exists"] is False
    assert research["current_chars"] == 0
    assert research["journal_chars"] == 0
    assert diagnostics == []
    assert section_status == {}


def test_collect_run_stats_counts_states_and_broken_manifests(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    _write_toml(
        runs_dir / "R20260409-0001" / "manifest.toml",
        {"run": {"id": "R20260409-0001", "status": "running"}},
    )
    _write_toml(
        runs_dir / "R20260409-0002" / "manifest.toml",
        {"run": {"id": "R20260409-0002", "status": "failed"}},
    )
    broken_run = runs_dir / "R20260409-0003"
    broken_run.mkdir(parents=True, exist_ok=True)
    (broken_run / "manifest.toml").write_text("not valid toml", encoding="utf-8")

    diagnostics: list[dict[str, str]] = []
    section_status: dict[str, str] = {}

    stats = _collect_run_stats(tmp_path, diagnostics, section_status)

    assert stats["running"] == 1
    assert stats["failed"] == 1
    assert stats["unknown"] == 1
    assert stats["total"] == 3
    assert diagnostics == []


def test_collect_run_stats_includes_completed_readiness_problems(
    tmp_path: Path,
) -> None:
    runs_dir = tmp_path / "runs"
    run_dir = runs_dir / "R20260507-0001"
    _write_toml(
        run_dir / "manifest.toml",
        {
            "run": {"id": "R20260507-0001", "status": "completed"},
            "simulator": {"name": "emses", "adapter": "emses"},
        },
    )
    _write_toml(run_dir / "input" / "plasma.toml", {"jobcon": {"nstep": 100}})
    (run_dir / "work").mkdir(parents=True, exist_ok=True)
    (run_dir / "work" / "energy").write_text("100 1.0 2.0\n", encoding="utf-8")

    diagnostics: list[dict[str, str]] = []
    section_status: dict[str, str] = {}

    stats = _collect_run_stats(tmp_path, diagnostics, section_status)

    assert stats["completed"] == 1
    assert stats["analysis_incomplete"] == 1
    assert stats["analysis_problems"][0]["run_id"] == "R20260507-0001"
    assert stats["analysis_problems"][0]["missing_required_artifacts"] == [
        "hdf5_fields"
    ]


def test_collect_recent_failures_returns_only_failed_runs(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    _write_toml(
        runs_dir / "R20260409-0001" / "manifest.toml",
        {
            "run": {
                "id": "R20260409-0001",
                "status": "failed",
                "failure_reason": "timeout",
                "display_name": "first",
            }
        },
    )
    _write_toml(
        runs_dir / "R20260409-0002" / "manifest.toml",
        {
            "run": {
                "id": "R20260409-0002",
                "status": "completed",
                "display_name": "second",
            }
        },
    )
    _write_toml(
        runs_dir / "R20260409-0003" / "manifest.toml",
        {
            "run": {
                "id": "R20260409-0003",
                "status": "failed",
                "failure_reason": "oom",
                "display_name": "third",
            }
        },
    )

    failures = _collect_recent_failures(tmp_path, [], {}, limit=1)

    assert failures == [
        {
            "run_id": "R20260409-0001",
            "reason": "timeout",
            "display_name": "first",
            "retry_status": "",
            "partial_outputs": {},
        }
    ]


def test_collect_facts_summary_serializes_local_and_candidate_fields(
    tmp_path: Path,
) -> None:
    diagnostics: list[dict[str, str]] = []
    section_status: dict[str, str] = {}
    facts = [
        SimpleNamespace(
            id="f001",
            claim="keep dt small",
            confidence="high",
            fact_type="constraint",
            simulator="emses",
            source_run="R20260409-0001",
            evidence_ref="run:R20260409-0001",
            storage="local",
            transport_source="",
        ),
        SimpleNamespace(
            id="cand:shared:f002",
            claim="candidate fact",
            confidence="medium",
            fact_type="observation",
            simulator="beach",
            source_run="",
            evidence_ref="fact:shared:f002",
            storage="candidate",
            transport_source="shared",
        ),
    ]

    with patch("runops.core.knowledge.query_facts", return_value=facts):
        summary = _collect_facts_summary(tmp_path, diagnostics, section_status)

    assert summary[0]["id"] == "f001"
    assert summary[0]["storage"] == "local"
    assert summary[1]["id"] == "cand:shared:f002"
    assert summary[1]["transport_source"] == "shared"


def test_collect_knowledge_paths_records_warning_on_integration_failure(
    tmp_path: Path,
) -> None:
    refs_repo = tmp_path / "refs" / "emses-docs"
    refs_repo.mkdir(parents=True)
    imports_file = tmp_path / ".runops" / "knowledge" / "enabled" / "imports.md"
    imports_file.parent.mkdir(parents=True, exist_ok=True)
    imports_file.write_text("@refs/emses-docs/README.md\n", encoding="utf-8")
    facts_file = tmp_path / ".runops" / "facts.toml"
    facts_file.parent.mkdir(parents=True, exist_ok=True)
    facts_file.write_text("", encoding="utf-8")
    candidate_dir = tmp_path / ".runops" / "knowledge" / "candidates" / "facts"
    candidate_dir.mkdir(parents=True, exist_ok=True)
    (candidate_dir / "shared.toml").write_text("", encoding="utf-8")
    insight_dir = tmp_path / ".runops" / "insights"
    insight_dir.mkdir(parents=True, exist_ok=True)
    (insight_dir / "latest.md").write_text(
        "---\ncreated: 2026-04-09\ntype: result\n---\n\ncontent\n",
        encoding="utf-8",
    )

    diagnostics: list[dict[str, str]] = []
    section_status: dict[str, str] = {}

    with (
        patch(
            "runops.core.knowledge_source.load_knowledge_config",
            return_value=SimpleNamespace(enabled=True),
        ),
        patch(
            "runops.core.knowledge_source.collect_external_knowledge",
            side_effect=RuntimeError("integration unavailable"),
        ),
    ):
        knowledge = _collect_knowledge_paths(tmp_path, diagnostics, section_status)

    assert knowledge["refs_repos"] == ["emses-docs"]
    assert knowledge["imports_ready"] is True
    assert knowledge["facts_file"] == str(facts_file)
    assert knowledge["candidate_fact_sources"] == 1
    assert knowledge["knowledge_enabled"] is True
    assert knowledge["insights_count"] == 1
    assert section_status["knowledge"] == "warning"
    assert diagnostics[0]["section"] == "knowledge"


def test_build_project_context_marks_available_actions_as_degraded_on_error(
    tmp_path: Path,
) -> None:
    _write_toml(tmp_path / "runops.toml", {"project": {"name": "demo"}})

    with patch(
        "runops.application.actions.list_actions",
        side_effect=RuntimeError("boom"),
    ):
        ctx = build_project_context(tmp_path)

    assert ctx["available_actions"] == []
    assert ctx["status"] == "degraded"
    assert ctx["section_status"]["available_actions"] == "error"
    assert any(
        diagnostic["section"] == "available_actions"
        for diagnostic in ctx["diagnostics"]
    )


def test_context_section_helpers_record_runops_errors(tmp_path: Path) -> None:
    diagnostics: list[dict[str, str]] = []
    section_status: dict[str, str] = {}

    with patch("runops.core.project.load_project", side_effect=SimctlError("broken")):
        project = _load_project_info(tmp_path, diagnostics, section_status)
        simulators = _load_simulator_names(tmp_path, diagnostics, section_status)
        launchers = _load_launcher_names(tmp_path, diagnostics, section_status)

    with patch(
        "runops.core.campaign.load_campaign", side_effect=SimctlError("missing")
    ):
        campaign = _load_campaign_info(tmp_path, diagnostics, section_status)

    assert project == {"name": "", "root": str(tmp_path)}
    assert simulators == []
    assert launchers == []
    assert campaign == {}
    assert section_status["project"] == "error"
    assert section_status["campaign"] == "error"
    assert section_status["simulators"] == "error"
    assert section_status["launchers"] == "error"
