"""Tests for Codex plugin recommendation inventory."""

from __future__ import annotations

from pathlib import Path

from runops.application.gateway.plugins import (
    adapter_lookup_entries,
    adapter_lookup_names,
    check_codex_plugin_inventory,
    delegated_codex_plugin_capabilities,
    load_project_codex_plugin_inventory,
)
from runops.core.codex_plugin import (
    CODEX_PLUGIN_ACTIVATION_SCOPE,
    CODEX_PLUGIN_INVENTORY_SCHEMA_VERSION,
    CodexPluginRecommendation,
    codex_plugin_management_policy,
)


def _write_project(
    project_dir: Path,
    *,
    simulators_toml: str,
    project_toml: str | None = None,
    site_toml: str | None = None,
) -> None:
    project_dir.joinpath("runops.toml").write_text(
        project_toml or '[project]\nname = "plugin-demo"\ndescription = ""\n',
        encoding="utf-8",
    )
    project_dir.joinpath("simulators.toml").write_text(
        simulators_toml,
        encoding="utf-8",
    )
    if site_toml is not None:
        project_dir.joinpath("site.toml").write_text(site_toml, encoding="utf-8")


def test_adapter_lookup_names_prefers_configured_adapter() -> None:
    """Simulator aliases resolve to their configured adapter registry key."""
    names = adapter_lookup_names(
        ["production"],
        {"production": {"adapter": "emses"}},
    )

    assert names == ["emses"]


def test_adapter_lookup_entries_keep_simulator_and_adapter_names() -> None:
    """Lookup entries preserve the project name while resolving adapter aliases."""
    entries = adapter_lookup_entries(
        ["production", "baseline"],
        {
            "production": {"adapter": "emses"},
            "baseline": {"adapter": "emses"},
        },
    )

    assert entries == [("production", "emses")]


def test_codex_plugin_recommendation_serializes_common_payloads() -> None:
    """Recommendation serialization stays centralized for JSON and site TOML."""
    plugin = CodexPluginRecommendation(
        name="site-context",
        display_name="Site Context",
        reason="Site-local workflow guidance.",
        install_hint="codex plugin add site-context@test",
        activation_hint="Start a new Codex thread.",
        visibility="private-or-gated",
        source="site:test-site",
        capabilities=("host-role-routing", "slurm-jobs"),
    )

    assert plugin.to_dict() == {
        "name": "site-context",
        "display_name": "Site Context",
        "reason": "Site-local workflow guidance.",
        "install_hint": "codex plugin add site-context@test",
        "activation_hint": "Start a new Codex thread.",
        "visibility": "private-or-gated",
        "source": "site:test-site",
        "sources": ["site:test-site"],
        "capabilities": ["host-role-routing", "slurm-jobs"],
    }
    assert plugin.to_site_mapping() == {
        "display_name": "Site Context",
        "visibility": "private-or-gated",
        "reason": "Site-local workflow guidance.",
        "install_hint": "codex plugin add site-context@test",
        "activation_hint": "Start a new Codex thread.",
        "capabilities": ["host-role-routing", "slurm-jobs"],
    }

    with_project_source = plugin.with_additional_source("simulator:production")
    assert with_project_source.source == "site:test-site, simulator:production"
    assert with_project_source.to_dict()["sources"] == [
        "site:test-site",
        "simulator:production",
    ]


def test_codex_plugin_management_policy_is_user_local() -> None:
    policy = codex_plugin_management_policy()

    assert policy == {
        "runops_installs_plugins": False,
        "runops_enables_plugins": False,
        "runops_inspects_user_install_state": False,
        "activation_scope": CODEX_PLUGIN_ACTIVATION_SCOPE,
    }


def test_delegated_capability_index_maps_roles_to_plugins() -> None:
    """Capability index lets tools find delegated plugin roles without parsing prose."""
    index = delegated_codex_plugin_capabilities(
        [
            CodexPluginRecommendation(
                name="site-context",
                display_name="Site Context",
                reason="Site-local workflow guidance.",
                install_hint="codex plugin add site-context@test",
                source="site:test",
                capabilities=("slurm-jobs", "host-role-routing", "slurm-jobs"),
            ),
            CodexPluginRecommendation(
                name="analysis-context",
                display_name="Analysis Context",
                reason="Analysis workflow guidance.",
                install_hint="codex plugin add analysis-context@test",
                source="project:test",
                capabilities=("analysis-workflow", "slurm-jobs"),
            ),
        ]
    )

    assert index == {
        "analysis-workflow": ["analysis-context"],
        "host-role-routing": ["site-context"],
        "slurm-jobs": ["site-context", "analysis-context"],
    }


def test_project_inventory_json_has_schema_version(tmp_path: Path) -> None:
    """Machine-readable plugin inventory exposes a stable schema version."""
    _write_project(
        tmp_path,
        simulators_toml="[simulators]\n",
    )

    inventory = load_project_codex_plugin_inventory(tmp_path)
    check_result = check_codex_plugin_inventory(inventory)

    assert inventory.to_dict()["$schema"] == "schemas/codex-plugin-inventory.json"
    assert inventory.to_dict()["schema_version"] == (
        CODEX_PLUGIN_INVENTORY_SCHEMA_VERSION
    )
    assert inventory.to_dict()["delegated_capabilities"] == {}
    assert check_result.to_dict()["$schema"] == (
        "schemas/codex-plugin-check-result.json"
    )
    assert check_result.to_dict()["schema_version"] == (
        CODEX_PLUGIN_INVENTORY_SCHEMA_VERSION
    )
    assert check_result.to_dict()["strict_ok"] is True
    assert check_result.to_dict()["inventory"]["schema_version"] == (
        CODEX_PLUGIN_INVENTORY_SCHEMA_VERSION
    )


def test_project_inventory_uses_adapter_alias_for_recommendations(
    tmp_path: Path,
) -> None:
    """Plugin recommendations work when simulator key and adapter name differ."""
    _write_project(
        tmp_path,
        simulators_toml=(
            "[simulators.production]\n"
            'adapter = "emses"\n'
            'resolver_mode = "package"\n'
            'executable = "mpiemses3D"\n'
        ),
    )

    inventory = load_project_codex_plugin_inventory(tmp_path)

    assert inventory.simulator_names == ("production",)
    assert [plugin.name for plugin in inventory.recommendations] == [
        "mpiemses3d-context",
        "emout-context",
    ]
    assert inventory.recommendations[0].source_labels() == (
        "simulator:emses",
        "simulator:production",
    )


def test_project_inventory_includes_beach_adapter_recommendation(
    tmp_path: Path,
) -> None:
    """BEACH projects recommend the BEACH Context plugin."""
    _write_project(
        tmp_path,
        simulators_toml=(
            "[simulators.beach]\n"
            'adapter = "beach"\n'
            'resolver_mode = "package"\n'
            'executable = "beach"\n'
        ),
    )

    result = check_codex_plugin_inventory(load_project_codex_plugin_inventory(tmp_path))

    assert result.ok is True
    assert result.ok_with_strict() is True
    assert [plugin.name for plugin in result.inventory.recommendations] == [
        "beach-context"
    ]
    assert result.inventory.delegated_capabilities()["run-diagnose"] == [
        "beach-context"
    ]
    plugin_payload = result.to_dict()["inventory"]["recommendations"][0]
    assert plugin_payload["display_name"] == "BEACH Context"
    assert plugin_payload["source"] == "simulator:beach"
    assert plugin_payload["sources"] == ["simulator:beach"]
    assert "run-diagnose" in plugin_payload["capabilities"]
    assert "output-analysis" in plugin_payload["capabilities"]
    assert "cookbook" in plugin_payload["capabilities"]
    assert result.to_dict()["inventory"]["delegated_capabilities"]["cookbook"] == [
        "beach-context"
    ]
    assert result.to_dict()["inventory"]["delegated_capabilities"]["run-diagnose"] == [
        "beach-context"
    ]


def test_project_inventory_includes_site_recommendations(tmp_path: Path) -> None:
    """Site profile Codex plugin recommendations are included."""
    _write_project(
        tmp_path,
        simulators_toml="[simulators]\n",
        site_toml=(
            '[site]\nname = "test-site"\n'
            "[site.codex_plugins.site-context]\n"
            'display_name = "Site Context"\n'
            'reason = "Site-local workflow guidance."\n'
            'install_hint = "codex plugin add site-context@test"\n'
        ),
    )

    inventory = load_project_codex_plugin_inventory(tmp_path)

    assert inventory.site_name == "test-site"
    assert [plugin.name for plugin in inventory.recommendations] == ["site-context"]
    assert inventory.to_dict()["management"]["runops_installs_plugins"] is False


def test_project_inventory_includes_simulator_config_recommendations(
    tmp_path: Path,
) -> None:
    """Project simulator config can recommend plugins without adapter changes."""
    _write_project(
        tmp_path,
        simulators_toml=(
            "[simulators.production]\n"
            'adapter = "generic"\n'
            'resolver_mode = "package"\n'
            'executable = "solver"\n'
            "\n[simulators.production.codex_plugins.production-context]\n"
            'display_name = "Production Context"\n'
            'reason = "Project-specific production workflow guidance."\n'
            'install_hint = "codex plugin add production-context@project"\n'
            'capabilities = ["case-design", "analysis-workflow"]\n'
            'activation_hint = "Start a new Codex thread."\n'
            'visibility = "private-or-gated"\n'
        ),
    )

    result = check_codex_plugin_inventory(load_project_codex_plugin_inventory(tmp_path))

    assert result.ok is True
    assert result.ok_with_strict() is True
    assert [plugin.name for plugin in result.inventory.recommendations] == [
        "production-context"
    ]
    plugin_payload = result.to_dict()["inventory"]["recommendations"][0]
    assert plugin_payload["source"] == "simulator:production"
    assert plugin_payload["sources"] == ["simulator:production"]
    assert plugin_payload["visibility"] == "private-or-gated"
    assert plugin_payload["capabilities"] == ["case-design", "analysis-workflow"]


def test_project_inventory_includes_project_config_recommendations(
    tmp_path: Path,
) -> None:
    """runops.toml can recommend project-wide plugins without adapter changes."""
    _write_project(
        tmp_path,
        project_toml=(
            '[project]\nname = "plugin-demo"\ndescription = ""\n'
            "\n[project.codex_plugins.analysis-context]\n"
            'display_name = "Analysis Context"\n'
            'reason = "Team analysis workflow guidance."\n'
            'install_hint = "codex plugin add analysis-context@project"\n'
            'capabilities = ["survey-design", "report-writing"]\n'
            'activation_hint = "Start a new Codex thread."\n'
            'visibility = "private-or-gated"\n'
        ),
        simulators_toml="[simulators]\n",
    )

    result = check_codex_plugin_inventory(load_project_codex_plugin_inventory(tmp_path))

    assert result.ok is True
    assert result.ok_with_strict() is True
    assert [plugin.name for plugin in result.inventory.recommendations] == [
        "analysis-context"
    ]
    plugin_payload = result.to_dict()["inventory"]["recommendations"][0]
    assert plugin_payload["source"] == "project:plugin-demo"
    assert plugin_payload["sources"] == ["project:plugin-demo"]
    assert plugin_payload["visibility"] == "private-or-gated"
    assert plugin_payload["capabilities"] == ["survey-design", "report-writing"]


def test_project_inventory_accepts_single_capability_string(
    tmp_path: Path,
) -> None:
    """A single capability label may be written as a string."""
    _write_project(
        tmp_path,
        project_toml=(
            '[project]\nname = "plugin-demo"\ndescription = ""\n'
            "\n[project.codex_plugins.analysis-context]\n"
            'display_name = "Analysis Context"\n'
            'reason = "Team analysis workflow guidance."\n'
            'install_hint = "codex plugin add analysis-context@project"\n'
            'capabilities = "report-writing"\n'
        ),
        simulators_toml="[simulators]\n",
    )

    result = check_codex_plugin_inventory(load_project_codex_plugin_inventory(tmp_path))

    assert result.ok is True
    assert result.ok_with_strict() is True
    assert result.inventory.recommendations[0].capabilities == ("report-writing",)
    assert result.inventory.delegated_capabilities() == {
        "report-writing": ["analysis-context"]
    }


def test_project_plugin_check_passes_complete_recommendations(tmp_path: Path) -> None:
    """Complete adapter-provided recommendations pass metadata checks."""
    _write_project(
        tmp_path,
        simulators_toml=(
            "[simulators.emses]\n"
            'adapter = "emses"\n'
            'resolver_mode = "package"\n'
            'executable = "mpiemses3D"\n'
        ),
    )

    result = check_codex_plugin_inventory(load_project_codex_plugin_inventory(tmp_path))

    assert result.ok is True
    assert result.ok_with_strict() is True
    assert result.issues == ()
    payload = result.to_dict()
    assert payload["strict_ok"] is True
    assert payload["summary"]["recommendations"] == 2


def test_project_plugin_check_warns_when_adapter_recommendations_cannot_be_collected(
    tmp_path: Path,
) -> None:
    """Missing external adapters are visible without forcing installation."""
    _write_project(
        tmp_path,
        simulators_toml=(
            "[simulators.production]\n"
            'adapter = "missing_external"\n'
            'resolver_mode = "package"\n'
            'executable = "missing-solver"\n'
        ),
    )

    result = check_codex_plugin_inventory(load_project_codex_plugin_inventory(tmp_path))

    assert result.ok is True
    assert result.ok_with_strict() is False
    assert result.to_dict()["strict_ok"] is False
    assert result.inventory.recommendations == ()
    assert [
        (issue.severity, issue.plugin_name, issue.field) for issue in result.issues
    ] == [("warning", "missing_external", "adapter")]
    issue_payload = result.to_dict()["inventory"]["collection_issues"][0]
    assert issue_payload["source"] == "simulator:production"
    assert "could not be collected" in issue_payload["message"]


def test_project_plugin_check_reports_malformed_simulator_config_recommendations(
    tmp_path: Path,
) -> None:
    """Malformed project-side simulator plugin tables are warning-level issues."""
    _write_project(
        tmp_path,
        simulators_toml=(
            '[simulators.production]\nadapter = "generic"\ncodex_plugins = ["broken"]\n'
        ),
    )

    result = check_codex_plugin_inventory(load_project_codex_plugin_inventory(tmp_path))

    assert result.ok is True
    assert result.ok_with_strict() is False
    assert [(issue.plugin_name, issue.field) for issue in result.issues] == [
        ("production", "codex_plugins")
    ]


def test_project_plugin_check_reports_malformed_project_config_recommendations(
    tmp_path: Path,
) -> None:
    """Malformed project-level plugin tables are warning-level issues."""
    _write_project(
        tmp_path,
        project_toml=(
            '[project]\nname = "plugin-demo"\ndescription = ""\n'
            'codex_plugins = ["broken"]\n'
        ),
        simulators_toml="[simulators]\n",
    )

    result = check_codex_plugin_inventory(load_project_codex_plugin_inventory(tmp_path))

    assert result.ok is True
    assert result.ok_with_strict() is False
    assert [(issue.plugin_name, issue.field) for issue in result.issues] == [
        ("plugin-demo", "codex_plugins")
    ]
    assert result.issues[0].source == "project:plugin-demo"


def test_project_plugin_check_reports_malformed_site_recommendations(
    tmp_path: Path,
) -> None:
    """Malformed site plugin tables are warning-level issues."""
    _write_project(
        tmp_path,
        simulators_toml="[simulators]\n",
        site_toml=('[site]\nname = "test-site"\ncodex_plugins = ["broken"]\n'),
    )

    result = check_codex_plugin_inventory(load_project_codex_plugin_inventory(tmp_path))

    assert result.ok is True
    assert result.ok_with_strict() is False
    assert [(issue.plugin_name, issue.field) for issue in result.issues] == [
        ("test-site", "codex_plugins")
    ]
    assert result.issues[0].source == "site:test-site"


def test_project_plugin_check_reports_malformed_simulator_capabilities(
    tmp_path: Path,
) -> None:
    """Malformed simulator capability labels are warning-level metadata issues."""
    _write_project(
        tmp_path,
        simulators_toml=(
            "[simulators.production]\n"
            'adapter = "generic"\n'
            'resolver_mode = "package"\n'
            'executable = "solver"\n'
            "\n[simulators.production.codex_plugins.production-context]\n"
            'display_name = "Production Context"\n'
            'reason = "Project-specific production workflow guidance."\n'
            'install_hint = "codex plugin add production-context@project"\n'
            'capabilities = { role = "broken" }\n'
        ),
    )

    result = check_codex_plugin_inventory(load_project_codex_plugin_inventory(tmp_path))

    assert result.ok is True
    assert result.ok_with_strict() is False
    assert [plugin.name for plugin in result.inventory.recommendations] == [
        "production-context"
    ]
    assert result.inventory.recommendations[0].capabilities == ()
    assert [
        (issue.severity, issue.plugin_name, issue.field, issue.source)
        for issue in result.issues
    ] == [("warning", "production-context", "capabilities", "simulator:production")]
    assert "non-empty strings" in result.issues[0].message


def test_project_plugin_check_reports_malformed_project_capabilities(
    tmp_path: Path,
) -> None:
    """Malformed project-wide capability labels are warning-level metadata issues."""
    _write_project(
        tmp_path,
        project_toml=(
            '[project]\nname = "plugin-demo"\ndescription = ""\n'
            "\n[project.codex_plugins.analysis-context]\n"
            'display_name = "Analysis Context"\n'
            'reason = "Team analysis workflow guidance."\n'
            'install_hint = "codex plugin add analysis-context@project"\n'
            'capabilities = [""]\n'
        ),
        simulators_toml="[simulators]\n",
    )

    result = check_codex_plugin_inventory(load_project_codex_plugin_inventory(tmp_path))

    assert result.ok is True
    assert result.ok_with_strict() is False
    assert result.inventory.recommendations[0].capabilities == ()
    assert [
        (issue.severity, issue.plugin_name, issue.field, issue.source)
        for issue in result.issues
    ] == [("warning", "analysis-context", "capabilities", "project:plugin-demo")]


def test_project_plugin_check_reports_malformed_site_capabilities(
    tmp_path: Path,
) -> None:
    """Malformed site capability labels are warning-level metadata issues."""
    _write_project(
        tmp_path,
        simulators_toml="[simulators]\n",
        site_toml=(
            '[site]\nname = "test-site"\n'
            "[site.codex_plugins.site-context]\n"
            'display_name = "Site Context"\n'
            'reason = "Site-local workflow guidance."\n'
            'install_hint = "codex plugin add site-context@test"\n'
            'capabilities = { role = "broken" }\n'
        ),
    )

    result = check_codex_plugin_inventory(load_project_codex_plugin_inventory(tmp_path))

    assert result.ok is True
    assert result.ok_with_strict() is False
    assert result.inventory.recommendations[0].capabilities == ()
    assert [
        (issue.severity, issue.plugin_name, issue.field, issue.source)
        for issue in result.issues
    ] == [("warning", "site-context", "capabilities", "site:test-site")]


def test_project_plugin_check_reports_malformed_site_plugin_metadata(
    tmp_path: Path,
) -> None:
    """Malformed site plugin metadata is not silently dropped."""
    _write_project(
        tmp_path,
        simulators_toml="[simulators]\n",
        site_toml=(
            '[site]\nname = "test-site"\n'
            "[site.codex_plugins]\n"
            'site-context = "broken"\n'
        ),
    )

    result = check_codex_plugin_inventory(load_project_codex_plugin_inventory(tmp_path))

    assert result.ok is True
    assert result.ok_with_strict() is False
    assert [(issue.plugin_name, issue.field) for issue in result.issues] == [
        ("site-context", "codex_plugins")
    ]
    assert result.issues[0].source == "site:test-site"


def test_project_plugin_check_reports_incomplete_recommendations(
    tmp_path: Path,
) -> None:
    """Incomplete site-provided recommendation metadata is reported."""
    _write_project(
        tmp_path,
        simulators_toml="[simulators]\n",
        site_toml=(
            '[site]\nname = "test-site"\n'
            "[site.codex_plugins.incomplete]\n"
            'display_name = "Incomplete Plugin"\n'
        ),
    )

    result = check_codex_plugin_inventory(load_project_codex_plugin_inventory(tmp_path))

    assert result.ok is False
    assert [issue.field for issue in result.issues] == ["reason", "install_hint"]
    assert {issue.severity for issue in result.issues} == {"error"}


def test_project_plugin_check_warns_on_unknown_visibility(tmp_path: Path) -> None:
    """Unknown visibility is a warning, not an error."""
    _write_project(
        tmp_path,
        simulators_toml="[simulators]\n",
        site_toml=(
            '[site]\nname = "test-site"\n'
            "[site.codex_plugins.site-context]\n"
            'display_name = "Site Context"\n'
            'reason = "Site-local workflow guidance."\n'
            'install_hint = "codex plugin add site-context@test"\n'
            'visibility = "private"\n'
        ),
    )

    result = check_codex_plugin_inventory(load_project_codex_plugin_inventory(tmp_path))

    assert result.ok is True
    assert result.ok_with_strict() is False
    assert [(issue.severity, issue.field) for issue in result.issues] == [
        ("warning", "visibility")
    ]


def test_project_plugin_check_warns_on_conflicting_duplicate_recommendations(
    tmp_path: Path,
) -> None:
    """Duplicate plugin recommendations keep the first entry and warn on drift."""
    _write_project(
        tmp_path,
        simulators_toml=(
            "[simulators.emses]\n"
            'adapter = "emses"\n'
            'resolver_mode = "package"\n'
            'executable = "mpiemses3D"\n'
        ),
        site_toml=(
            '[site]\nname = "test-site"\n'
            "[site.codex_plugins.mpiemses3d-context]\n"
            'display_name = "MPIEMSES3D Context"\n'
            'reason = "Site-local MPIEMSES3D guidance."\n'
            'install_hint = "codex plugin add mpiemses3d-context@site"\n'
            'activation_hint = "Start a new Codex thread."\n'
            'visibility = "private-or-gated"\n'
        ),
    )

    result = check_codex_plugin_inventory(load_project_codex_plugin_inventory(tmp_path))

    assert result.ok is True
    assert result.ok_with_strict() is False
    assert [plugin.name for plugin in result.inventory.recommendations] == [
        "mpiemses3d-context",
        "emout-context",
    ]
    assert [(issue.severity, issue.field) for issue in result.issues] == [
        ("warning", "duplicate")
    ]
    assert result.to_dict()["inventory"]["collection_issues"][0]["field"] == (
        "duplicate"
    )


def test_project_plugin_check_merges_duplicate_sources_and_capabilities(
    tmp_path: Path,
) -> None:
    """Duplicate recommendations can add delegated roles without adapter edits."""
    _write_project(
        tmp_path,
        simulators_toml=(
            "[simulators.emses]\n"
            'adapter = "emses"\n'
            'resolver_mode = "package"\n'
            'executable = "mpiemses3D"\n'
        ),
        site_toml=(
            '[site]\nname = "test-site"\n'
            "[site.codex_plugins.mpiemses3d-context]\n"
            'display_name = "MPIEMSES3D Context"\n'
            'reason = "MPIEMSES3D input review, parameter design, run diagnosis, '
            'output analysis, and simulator learning guides."\n'
            'install_hint = "pip install mpiemses3d-tools\\n'
            'mpiemses-codex-plugin install"\n'
            'activation_hint = "Open Codex /plugins, install '
            '`MPIEMSES3D Context`, then start a new Codex thread."\n'
            'visibility = "private-or-gated"\n'
            'capabilities = ["site-runbook", "run-diagnose"]\n'
        ),
    )

    result = check_codex_plugin_inventory(load_project_codex_plugin_inventory(tmp_path))

    assert result.ok is True
    assert result.ok_with_strict() is True
    assert [plugin.name for plugin in result.inventory.recommendations] == [
        "mpiemses3d-context",
        "emout-context",
    ]
    plugin = result.inventory.recommendations[0]
    assert plugin.source == "simulator:emses, site:test-site"
    assert plugin.source_labels() == ("simulator:emses", "site:test-site")
    assert plugin.capabilities == (
        "input-review",
        "parameter-design",
        "run-diagnose",
        "output-analysis",
        "method-summary",
        "simulator-guide",
        "cookbook",
        "issue-report",
        "site-runbook",
    )
    assert result.inventory.delegated_capabilities()["cookbook"] == [
        "mpiemses3d-context"
    ]
    assert result.inventory.delegated_capabilities()["site-runbook"] == [
        "mpiemses3d-context"
    ]
    plugin_payload = result.to_dict()["inventory"]["recommendations"][0]
    assert plugin_payload["source"] == "simulator:emses, site:test-site"
    assert plugin_payload["sources"] == ["simulator:emses", "site:test-site"]
    assert not result.issues
