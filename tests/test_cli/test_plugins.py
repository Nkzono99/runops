"""Tests for the ``runo plugins`` command."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from runops.cli.main import app

runner = CliRunner()


def _write_project(project_dir: Path) -> None:
    project_dir.joinpath("runops.toml").write_text(
        '[project]\nname = "plugin-demo"\ndescription = ""\n',
        encoding="utf-8",
    )
    project_dir.joinpath("simulators.toml").write_text(
        "[simulators.emses]\n"
        'adapter = "emses"\n'
        'resolver_mode = "package"\n'
        'executable = "mpiemses3D"\n',
        encoding="utf-8",
    )


def _write_project_with_site_plugin(
    project_dir: Path,
    *,
    site_plugin: str,
) -> None:
    project_dir.joinpath("runops.toml").write_text(
        '[project]\nname = "plugin-demo"\ndescription = ""\n',
        encoding="utf-8",
    )
    project_dir.joinpath("simulators.toml").write_text(
        "[simulators]\n",
        encoding="utf-8",
    )
    project_dir.joinpath("site.toml").write_text(
        '[site]\nname = "test-site"\n' + site_plugin,
        encoding="utf-8",
    )


def _write_project_with_missing_adapter(project_dir: Path) -> None:
    project_dir.joinpath("runops.toml").write_text(
        '[project]\nname = "plugin-demo"\ndescription = ""\n',
        encoding="utf-8",
    )
    project_dir.joinpath("simulators.toml").write_text(
        "[simulators.production]\n"
        'adapter = "missing_external"\n'
        'resolver_mode = "package"\n'
        'executable = "missing-solver"\n',
        encoding="utf-8",
    )


def _write_project_with_simulator_plugin(project_dir: Path) -> None:
    project_dir.joinpath("runops.toml").write_text(
        '[project]\nname = "plugin-demo"\ndescription = ""\n',
        encoding="utf-8",
    )
    project_dir.joinpath("simulators.toml").write_text(
        "[simulators.production]\n"
        'adapter = "generic"\n'
        'resolver_mode = "package"\n'
        'executable = "solver"\n'
        "\n[simulators.production.codex_plugins.production-context]\n"
        'display_name = "Production Context"\n'
        'reason = "Project-specific production workflow guidance."\n'
        'install_hint = "codex plugin add production-context@project"\n',
        encoding="utf-8",
    )


def _write_beach_project(project_dir: Path) -> None:
    project_dir.joinpath("runops.toml").write_text(
        '[project]\nname = "beach-demo"\ndescription = ""\n',
        encoding="utf-8",
    )
    project_dir.joinpath("simulators.toml").write_text(
        "[simulators.beach]\n"
        'adapter = "beach"\n'
        'resolver_mode = "package"\n'
        'executable = "beach"\n',
        encoding="utf-8",
    )


def _write_project_with_project_plugin(project_dir: Path) -> None:
    project_dir.joinpath("runops.toml").write_text(
        '[project]\nname = "plugin-demo"\ndescription = ""\n'
        "\n[project.codex_plugins.analysis-context]\n"
        'display_name = "Analysis Context"\n'
        'reason = "Team analysis workflow guidance."\n'
        'install_hint = "codex plugin add analysis-context@project"\n',
        encoding="utf-8",
    )
    project_dir.joinpath("simulators.toml").write_text(
        "[simulators]\n",
        encoding="utf-8",
    )


def test_plugins_outputs_recommendations(tmp_path: Path) -> None:
    """The command lists project Codex plugin recommendations."""
    _write_project(tmp_path)

    result = runner.invoke(app, ["plugins", str(tmp_path)])

    assert result.exit_code == 0
    assert "Codex plugin recommendations for plugin-demo" in result.output
    assert "runops does not install or enable these plugins" in result.output
    assert "MPIEMSES3D Context" in result.output
    assert "emout Context" in result.output
    assert "Delegated capabilities:" in result.output
    assert "parameter-design: mpiemses3d-context" in result.output
    assert "Capabilities: input-review, parameter-design" in result.output


def test_plugins_outputs_json(tmp_path: Path) -> None:
    """The command emits machine-readable inventory JSON."""
    _write_project(tmp_path)

    result = runner.invoke(app, ["plugins", str(tmp_path), "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["$schema"] == "schemas/codex-plugin-inventory.json"
    assert data["schema_version"] == 1
    assert data["project"]["name"] == "plugin-demo"
    assert data["simulators"] == ["emses"]
    assert data["management"]["runops_installs_plugins"] is False
    assert data["management"]["runops_enables_plugins"] is False
    assert data["management"]["runops_inspects_user_install_state"] is False
    assert [plugin["name"] for plugin in data["recommendations"]] == [
        "mpiemses3d-context",
        "emout-context",
    ]
    assert data["recommendations"][0]["sources"] == ["simulator:emses"]
    assert "parameter-design" in data["recommendations"][0]["capabilities"]
    assert "visualization-script" in data["recommendations"][1]["capabilities"]
    assert data["delegated_capabilities"]["parameter-design"] == ["mpiemses3d-context"]
    assert data["delegated_capabilities"]["visualization-script"] == ["emout-context"]


def test_plugins_outputs_simulator_config_recommendations_json(
    tmp_path: Path,
) -> None:
    """Project simulator config recommendations are visible to external tools."""
    _write_project_with_simulator_plugin(tmp_path)

    result = runner.invoke(app, ["plugins", str(tmp_path), "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["$schema"] == "schemas/codex-plugin-inventory.json"
    assert [plugin["name"] for plugin in data["recommendations"]] == [
        "production-context"
    ]
    assert data["recommendations"][0]["source"] == "simulator:production"
    assert data["recommendations"][0]["sources"] == ["simulator:production"]


def test_plugins_outputs_project_config_recommendations_json(
    tmp_path: Path,
) -> None:
    """Project-wide recommendations are visible to external tools."""
    _write_project_with_project_plugin(tmp_path)

    result = runner.invoke(app, ["plugins", str(tmp_path), "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["$schema"] == "schemas/codex-plugin-inventory.json"
    assert [plugin["name"] for plugin in data["recommendations"]] == [
        "analysis-context"
    ]
    assert data["recommendations"][0]["source"] == "project:plugin-demo"
    assert data["recommendations"][0]["sources"] == ["project:plugin-demo"]


def test_plugins_outputs_beach_adapter_recommendation_json(tmp_path: Path) -> None:
    """BEACH adapter recommendations are visible to external tools."""
    _write_beach_project(tmp_path)

    result = runner.invoke(app, ["plugins", str(tmp_path), "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["$schema"] == "schemas/codex-plugin-inventory.json"
    assert [plugin["name"] for plugin in data["recommendations"]] == ["beach-context"]
    assert data["recommendations"][0]["display_name"] == "BEACH Context"
    assert data["recommendations"][0]["source"] == "simulator:beach"
    assert data["recommendations"][0]["sources"] == ["simulator:beach"]
    assert "config-review" in data["recommendations"][0]["capabilities"]
    assert "cookbook" in data["recommendations"][0]["capabilities"]
    assert data["delegated_capabilities"]["cookbook"] == ["beach-context"]
    assert data["delegated_capabilities"]["config-review"] == ["beach-context"]


def test_plugins_check_passes_for_complete_recommendations(tmp_path: Path) -> None:
    """--check validates advisory metadata without checking install state."""
    _write_project(tmp_path)

    result = runner.invoke(app, ["plugins", str(tmp_path), "--check"])

    assert result.exit_code == 0
    assert "Plugin recommendation metadata: OK" in result.output


def test_plugins_check_reports_incomplete_recommendations(tmp_path: Path) -> None:
    """--check fails on incomplete recommendation metadata."""
    _write_project_with_site_plugin(
        tmp_path,
        site_plugin=(
            '[site.codex_plugins.incomplete]\ndisplay_name = "Incomplete Plugin"\n'
        ),
    )

    result = runner.invoke(app, ["plugins", str(tmp_path), "--check"])

    assert result.exit_code == 1
    assert "2 error(s), 0 warning(s)" in result.output
    assert "[error] incomplete.reason" in result.output
    assert "[error] incomplete.install_hint" in result.output


def test_plugins_check_strict_fails_on_warnings(tmp_path: Path) -> None:
    """--strict makes warning-only metadata checks fail."""
    _write_project_with_site_plugin(
        tmp_path,
        site_plugin=(
            "[site.codex_plugins.site-context]\n"
            'display_name = "Site Context"\n'
            'reason = "Site-local workflow guidance."\n'
            'install_hint = "codex plugin add site-context@test"\n'
            'visibility = "private"\n'
        ),
    )

    relaxed = runner.invoke(app, ["plugins", str(tmp_path), "--check"])
    strict = runner.invoke(app, ["plugins", str(tmp_path), "--check", "--strict"])

    assert relaxed.exit_code == 0
    assert "0 error(s), 1 warning(s)" in relaxed.output
    assert strict.exit_code == 1
    assert "0 error(s), 1 warning(s)" in strict.output


def test_plugins_check_reports_malformed_site_recommendations(tmp_path: Path) -> None:
    """Malformed site plugin metadata is surfaced as a warning."""
    _write_project_with_site_plugin(
        tmp_path,
        site_plugin='codex_plugins = ["broken"]\n',
    )

    relaxed = runner.invoke(app, ["plugins", str(tmp_path), "--check"])
    strict = runner.invoke(app, ["plugins", str(tmp_path), "--check", "--strict"])

    assert relaxed.exit_code == 0
    assert "0 error(s), 1 warning(s)" in relaxed.output
    assert "[warning] test-site.codex_plugins" in relaxed.output
    assert "Site-level Codex plugin recommendations" in relaxed.output
    assert strict.exit_code == 1


def test_plugins_check_reports_malformed_capabilities(tmp_path: Path) -> None:
    """Malformed capability metadata is visible in relaxed and strict checks."""
    _write_project_with_site_plugin(
        tmp_path,
        site_plugin=(
            "[site.codex_plugins.site-context]\n"
            'display_name = "Site Context"\n'
            'reason = "Site-local workflow guidance."\n'
            'install_hint = "codex plugin add site-context@test"\n'
            'capabilities = { role = "broken" }\n'
        ),
    )

    relaxed = runner.invoke(app, ["plugins", str(tmp_path), "--check"])
    strict = runner.invoke(app, ["plugins", str(tmp_path), "--check", "--strict"])

    assert relaxed.exit_code == 0
    assert "0 error(s), 1 warning(s)" in relaxed.output
    assert "[warning] site-context.capabilities" in relaxed.output
    assert "non-empty strings" in relaxed.output
    assert strict.exit_code == 1


def test_plugins_check_warns_when_adapter_is_not_registered(tmp_path: Path) -> None:
    """Missing external adapters are reported without checking install state."""
    _write_project_with_missing_adapter(tmp_path)

    relaxed = runner.invoke(app, ["plugins", str(tmp_path), "--check"])
    strict = runner.invoke(app, ["plugins", str(tmp_path), "--check", "--strict"])

    assert relaxed.exit_code == 0
    assert "0 error(s), 1 warning(s)" in relaxed.output
    assert "[warning] missing_external.adapter" in relaxed.output
    assert "could not be collected" in relaxed.output
    assert strict.exit_code == 1
    assert "0 error(s), 1 warning(s)" in strict.output


def test_plugins_check_outputs_json(tmp_path: Path) -> None:
    """--check --json emits inventory plus check issues."""
    _write_project(tmp_path)

    result = runner.invoke(app, ["plugins", str(tmp_path), "--check", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["$schema"] == "schemas/codex-plugin-check-result.json"
    assert data["schema_version"] == 1
    assert data["ok"] is True
    assert data["strict_ok"] is True
    assert data["summary"]["recommendations"] == 2
    assert data["issues"] == []
    assert data["inventory"]["$schema"] == "schemas/codex-plugin-inventory.json"
    assert data["inventory"]["management"]["runops_installs_plugins"] is False


def test_plugins_check_json_includes_strict_status_for_warnings(
    tmp_path: Path,
) -> None:
    """--check --json exposes strict warning status from the core payload."""
    _write_project_with_site_plugin(
        tmp_path,
        site_plugin=(
            "[site.codex_plugins.site-context]\n"
            'display_name = "Site Context"\n'
            'reason = "Site-local workflow guidance."\n'
            'install_hint = "codex plugin add site-context@test"\n'
            'visibility = "private"\n'
        ),
    )

    result = runner.invoke(app, ["plugins", str(tmp_path), "--check", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["$schema"] == "schemas/codex-plugin-check-result.json"
    assert data["ok"] is True
    assert data["strict_ok"] is False
    assert data["summary"] == {
        "recommendations": 1,
        "errors": 0,
        "warnings": 1,
    }


def test_plugins_fails_outside_project(tmp_path: Path) -> None:
    """Missing runops.toml produces a user-facing error."""
    result = runner.invoke(app, ["plugins", str(tmp_path)])

    assert result.exit_code == 1
    assert "Error: No runops.toml found" in result.output
