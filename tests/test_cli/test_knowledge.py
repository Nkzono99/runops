"""Tests for runops knowledge CLI commands."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from runops.cli.main import app
from runops.core.knowledge import (
    list_insights,
    load_candidate_facts,
    load_facts,
    query_facts,
)
from runops.core.knowledge_source import load_knowledge_config

runner = CliRunner()


def _create_project(tmp_path: Path, extra_toml: str = "") -> Path:
    content = f'[project]\nname = "test-project"\n{extra_toml}'
    (tmp_path / "runops.toml").write_text(content)
    return tmp_path


def test_add_fact_uses_structured_scope_and_evidence_fields(tmp_path: Path) -> None:
    project_root = _create_project(tmp_path)

    with patch("runops.cli.knowledge.Path.cwd", return_value=project_root):
        result = runner.invoke(
            app,
            [
                "knowledge",
                "add-fact",
                "dt must stay below the CFL limit",
                "--scope-text",
                "emses",
                "--evidence-kind",
                "run_observation",
                "--confidence",
                "high",
                "--run",
                "R20260330-0001",
            ],
        )

    assert result.exit_code == 0
    assert "Saved fact [f001]" in result.output

    facts = load_facts(project_root)
    assert len(facts) == 1
    assert facts[0].scope_text == "emses"
    assert facts[0].evidence_kind == "run_observation"
    assert facts[0].source_run == "R20260330-0001"


def test_add_fact_rejects_removed_legacy_alias_options(tmp_path: Path) -> None:
    project_root = _create_project(tmp_path)

    with patch("runops.cli.knowledge.Path.cwd", return_value=project_root):
        result = runner.invoke(
            app,
            [
                "knowledge",
                "add-fact",
                "dt must stay below the CFL limit",
                "--scope",
                "emses",
            ],
        )

    assert result.exit_code != 0
    assert "No such option" in result.output


def test_add_fact_supports_structured_fields_and_supersedes(tmp_path: Path) -> None:
    project_root = _create_project(tmp_path)

    with patch("runops.cli.knowledge.Path.cwd", return_value=project_root):
        first = runner.invoke(
            app,
            ["knowledge", "add-fact", "initial observation"],
        )
        second = runner.invoke(
            app,
            [
                "knowledge",
                "add-fact",
                "refined constraint",
                "--type",
                "constraint",
                "--simulator",
                "emses",
                "--scope-case",
                "baseline",
                "--scope-text",
                "stable grid setup",
                "--param-name",
                "tmgrid.dt",
                "--evidence-kind",
                "run_observation",
                "--evidence-ref",
                "run:R20260330-0002",
                "--supersedes",
                "f001",
            ],
        )

    assert first.exit_code == 0
    assert second.exit_code == 0
    assert "Saved fact [f002]" in second.output

    facts = load_facts(project_root)
    assert len(facts) == 2
    assert facts[1].fact_type == "constraint"
    assert facts[1].simulator == "emses"
    assert facts[1].scope_case == "baseline"
    assert facts[1].scope_text == "stable grid setup"
    assert facts[1].param_name == "tmgrid.dt"
    assert facts[1].evidence_ref == "run:R20260330-0002"
    assert facts[1].supersedes == "f001"

    visible = query_facts(project_root)
    assert [fact.id for fact in visible] == ["f002"]


def test_save_persists_insight_via_action_registry(tmp_path: Path) -> None:
    project_root = _create_project(tmp_path)

    with patch("runops.cli.knowledge.Path.cwd", return_value=project_root):
        result = runner.invoke(
            app,
            [
                "knowledge",
                "save",
                "mag_results",
                "--type",
                "result",
                "--simulator",
                "emses",
                "--tags",
                "survey,scan",
                "--message",
                "Stable trend across the scan.",
            ],
        )

    assert result.exit_code == 0
    assert "mag_results.md" in result.output

    insights = list_insights(project_root, simulator="emses", insight_type="result")
    assert len(insights) == 1
    assert insights[0].name == "mag_results"
    assert insights[0].tags == ["survey", "scan"]
    assert insights[0].content == "Stable trend across the scan."


def test_facts_supports_structured_filters_and_json_output(tmp_path: Path) -> None:
    project_root = _create_project(tmp_path)

    with patch("runops.cli.knowledge.Path.cwd", return_value=project_root):
        runner.invoke(
            app,
            [
                "knowledge",
                "add-fact",
                "dt must stay low",
                "--type",
                "constraint",
                "--simulator",
                "emses",
                "--param-name",
                "tmgrid.dt",
                "--confidence",
                "high",
            ],
        )
        runner.invoke(
            app,
            [
                "knowledge",
                "add-fact",
                "other simulator fact",
                "--type",
                "policy",
                "--simulator",
                "beach",
            ],
        )
        result = runner.invoke(
            app,
            [
                "knowledge",
                "facts",
                "--simulator",
                "emses",
                "--type",
                "constraint",
                "--param-name",
                "tmgrid.dt",
                "--json",
            ],
        )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert len(payload) == 1
    assert payload[0]["simulator"] == "emses"
    assert payload[0]["fact_type"] == "constraint"
    assert payload[0]["param_name"] == "tmgrid.dt"


def test_source_sync_imports_candidate_facts(tmp_path: Path) -> None:
    project_root = _create_project(
        tmp_path,
        """
[knowledge]
enabled = true

[[knowledge.sources]]
name = "shared"
type = "path"
kind = "project"
path = "../shared-project"
""",
    )
    source_root = tmp_path.parent / "shared-project"
    facts_dir = source_root / ".runops"
    facts_dir.mkdir(parents=True, exist_ok=True)
    (facts_dir / "facts.toml").write_text(
        "[[facts]]\n"
        'id = "f004"\n'
        'claim = "keep dt below 1.0"\n'
        'fact_type = "constraint"\n'
        'simulator = "emses"\n'
        'confidence = "high"\n',
        encoding="utf-8",
    )

    with patch("runops.cli.knowledge.Path.cwd", return_value=project_root):
        result = runner.invoke(app, ["knowledge", "source", "sync"])

    assert result.exit_code == 0
    assert "Candidate facts synced: 1 across 1 source(s)" in result.output
    candidate_facts = load_candidate_facts(project_root)
    assert [fact.id for fact in candidate_facts] == ["shared:f004"]


def test_promote_fact_copies_candidate_to_local_facts(tmp_path: Path) -> None:
    project_root = _create_project(
        tmp_path,
        """
[knowledge]
enabled = true

[[knowledge.sources]]
name = "shared"
type = "path"
kind = "project"
path = "../shared-project"
""",
    )
    source_root = tmp_path.parent / "shared-project"
    facts_dir = source_root / ".runops"
    facts_dir.mkdir(parents=True, exist_ok=True)
    (facts_dir / "facts.toml").write_text(
        "[[facts]]\n"
        'id = "f004"\n'
        'claim = "keep dt below 1.0"\n'
        'fact_type = "constraint"\n'
        'simulator = "emses"\n'
        'confidence = "high"\n',
        encoding="utf-8",
    )

    with patch("runops.cli.knowledge.Path.cwd", return_value=project_root):
        sync_result = runner.invoke(app, ["knowledge", "source", "sync"])
        promote_result = runner.invoke(
            app,
            ["knowledge", "promote-fact", "shared:f004"],
        )

    assert sync_result.exit_code == 0
    assert promote_result.exit_code == 0
    assert "Promoted shared:f004 -> f001" in promote_result.output

    local_facts = load_facts(project_root)
    assert len(local_facts) == 1
    assert local_facts[0].id == "f001"
    assert local_facts[0].fact_type == "constraint"
    assert local_facts[0].evidence_ref == "fact:shared:f004"


def test_knowledge_help_shows_source_group() -> None:
    result = runner.invoke(app, ["knowledge", "--help"])
    assert result.exit_code == 0
    assert "source" in result.output
    assert "profile" in result.output


def test_knowledge_source_help_shows_grouped_commands() -> None:
    result = runner.invoke(app, ["knowledge", "source", "--help"])
    assert result.exit_code == 0
    for cmd in ["list", "attach", "detach", "sync", "render", "status"]:
        assert cmd in result.output


def test_knowledge_profile_help_shows_grouped_commands() -> None:
    result = runner.invoke(app, ["knowledge", "profile", "--help"])
    assert result.exit_code == 0
    for cmd in ["enable", "disable"]:
        assert cmd in result.output


# ---------- Knowledge source CLI tests ----------


def test_attach_path_source(tmp_path: Path) -> None:
    project_root = _create_project(tmp_path)
    kb_dir = tmp_path / "my-kb"
    kb_dir.mkdir()
    (kb_dir / "README.md").write_text("# KB\n")
    (kb_dir / "profiles").mkdir()
    (kb_dir / "profiles" / "common.md").write_text("# Common\n")

    with patch("runops.cli.knowledge.Path.cwd", return_value=project_root):
        result = runner.invoke(
            app,
            [
                "knowledge",
                "source",
                "attach",
                "path",
                "my-kb",
                str(kb_dir),
                "--no-sync",
            ],
        )

    assert result.exit_code == 0
    assert "Attached [profiles/path] my-kb" in result.output

    config = load_knowledge_config(project_root)
    assert config is not None
    assert len(config.sources) == 1
    assert config.sources[0].name == "my-kb"
    assert config.sources[0].source_type == "path"
    assert config.sources[0].kind == "profiles"


def test_attach_path_project_source(tmp_path: Path) -> None:
    project_root = _create_project(tmp_path)
    upstream = tmp_path / "other-project"
    (upstream / ".runops" / "insights").mkdir(parents=True)

    with patch("runops.cli.knowledge.Path.cwd", return_value=project_root):
        result = runner.invoke(
            app,
            [
                "knowledge",
                "source",
                "attach",
                "path",
                "other-project",
                str(upstream),
                "--kind",
                "project",
                "--no-sync",
            ],
        )

    assert result.exit_code == 0
    assert "Attached [project/path] other-project" in result.output

    config = load_knowledge_config(project_root)
    assert config is not None
    assert config.sources[0].kind == "project"
    assert config.sources[0].mount == ""


def test_attach_git_source_with_profiles(tmp_path: Path) -> None:
    project_root = _create_project(tmp_path)

    with patch("runops.cli.knowledge.Path.cwd", return_value=project_root):
        result = runner.invoke(
            app,
            [
                "knowledge",
                "source",
                "attach",
                "git",
                "lab-kb",
                "https://github.com/lab/kb.git",
                "--profiles",
                "common,emses",
                "--no-sync",
            ],
        )

    assert result.exit_code == 0
    config = load_knowledge_config(project_root)
    assert config is not None
    assert config.sources[0].kind == "profiles"
    assert config.sources[0].profiles == ["common", "emses"]


def test_attach_invalid_type(tmp_path: Path) -> None:
    project_root = _create_project(tmp_path)

    with patch("runops.cli.knowledge.Path.cwd", return_value=project_root):
        result = runner.invoke(
            app,
            [
                "knowledge",
                "source",
                "attach",
                "invalid",
                "kb",
                "some-url",
                "--no-sync",
            ],
        )

    assert result.exit_code == 1
    assert "Invalid source type" in result.output


def test_attach_rejects_profiles_for_project_source(tmp_path: Path) -> None:
    project_root = _create_project(tmp_path)

    with patch("runops.cli.knowledge.Path.cwd", return_value=project_root):
        result = runner.invoke(
            app,
            [
                "knowledge",
                "source",
                "attach",
                "path",
                "upstream",
                "../upstream",
                "--kind",
                "project",
                "--profiles",
                "common",
            ],
        )

    assert result.exit_code == 1
    assert "--profiles is only valid" in result.output


def test_detach_source(tmp_path: Path) -> None:
    toml = """
[knowledge]
enabled = true

[[knowledge.sources]]
name = "test-kb"
type = "path"
kind = "profiles"
path = "/some/path"
mount = "refs/knowledge/test-kb"
"""
    project_root = _create_project(tmp_path, toml)

    with patch("runops.cli.knowledge.Path.cwd", return_value=project_root):
        result = runner.invoke(
            app,
            ["knowledge", "source", "detach", "test-kb", "--keep-files"],
        )

    assert result.exit_code == 0
    assert "Detached: test-kb" in result.output
    config = load_knowledge_config(project_root)
    assert config is not None
    assert len(config.sources) == 0


def test_detach_not_found(tmp_path: Path) -> None:
    project_root = _create_project(tmp_path, "\n[knowledge]\nsources = []\n")

    with patch("runops.cli.knowledge.Path.cwd", return_value=project_root):
        result = runner.invoke(
            app,
            ["knowledge", "source", "detach", "nonexistent"],
        )

    assert result.exit_code == 1
    assert "Source not found" in result.output


def test_detach_refuses_to_remove_path_outside_project(tmp_path: Path) -> None:
    outside_dir = tmp_path.parent / f"{tmp_path.name}-outside-kb"
    outside_dir.mkdir()
    (outside_dir / "data.txt").write_text("keep", encoding="utf-8")
    toml = f"""
[knowledge]
enabled = true

[[knowledge.sources]]
name = "test-kb"
type = "path"
kind = "profiles"
path = "/some/path"
mount = "{outside_dir.as_posix()}"
"""
    project_root = _create_project(tmp_path, toml)

    with patch("runops.cli.knowledge.Path.cwd", return_value=project_root):
        result = runner.invoke(app, ["knowledge", "source", "detach", "test-kb"])

    assert result.exit_code == 0
    assert "Detached: test-kb" in result.output
    assert "refusing to remove mount outside project root" in result.output
    assert outside_dir.exists()


def test_render_generates_imports(tmp_path: Path) -> None:
    toml = """
[knowledge]
enabled = true

[[knowledge.sources]]
name = "kb"
type = "path"
kind = "profiles"
path = "."
mount = "refs/knowledge/kb"
profiles = ["common"]
"""
    project_root = _create_project(tmp_path, toml)

    # Create the mounted source with profiles
    mount = project_root / "refs" / "knowledge" / "kb" / "profiles"
    mount.mkdir(parents=True)
    (mount / "common.md").write_text("# Common\n")

    with patch("runops.cli.knowledge.Path.cwd", return_value=project_root):
        result = runner.invoke(app, ["knowledge", "source", "render"])

    assert result.exit_code == 0
    assert "Rendered:" in result.output

    imports = project_root / ".runops" / "knowledge" / "enabled" / "imports.md"
    assert imports.is_file()
    assert "@refs/knowledge/kb/profiles/common.md" in imports.read_text()


def test_render_uses_entrypoints_manifest(tmp_path: Path) -> None:
    toml = """
[knowledge]
enabled = true

[[knowledge.sources]]
name = "kb"
type = "path"
kind = "profiles"
path = "."
mount = "refs/knowledge/kb"
profiles = ["common"]
"""
    project_root = _create_project(tmp_path, toml)

    mount = project_root / "refs" / "knowledge" / "kb"
    (mount / "profiles").mkdir(parents=True)
    (mount / "profiles" / "common.md").write_text("# Common\n", encoding="utf-8")
    (mount / "docs").mkdir()
    (mount / "docs" / "agent-guide.md").write_text("# Agent\n", encoding="utf-8")
    (mount / "entrypoints.toml").write_text(
        '[profiles.common]\nimports = ["profiles/common.md", "docs/agent-guide.md"]\n',
        encoding="utf-8",
    )

    with patch("runops.cli.knowledge.Path.cwd", return_value=project_root):
        result = runner.invoke(app, ["knowledge", "source", "render"])

    assert result.exit_code == 0
    imports = project_root / ".runops" / "knowledge" / "enabled" / "imports.md"
    content = imports.read_text(encoding="utf-8")
    assert "@refs/knowledge/kb/profiles/common.md" in content
    assert "@refs/knowledge/kb/docs/agent-guide.md" in content


def test_render_no_knowledge_section(tmp_path: Path) -> None:
    project_root = _create_project(tmp_path)

    with patch("runops.cli.knowledge.Path.cwd", return_value=project_root):
        result = runner.invoke(app, ["knowledge", "source", "render"])

    assert result.exit_code == 1
    assert "No [knowledge] section" in result.output


def test_status_no_config(tmp_path: Path) -> None:
    project_root = _create_project(tmp_path)

    with patch("runops.cli.knowledge.Path.cwd", return_value=project_root):
        result = runner.invoke(app, ["knowledge", "source", "status"])

    assert result.exit_code == 0
    assert "not configured" in result.output


def test_status_with_sources(tmp_path: Path) -> None:
    toml = """
[knowledge]
enabled = true

[[knowledge.sources]]
name = "kb"
type = "path"
kind = "profiles"
path = "."
mount = "refs/knowledge/kb"
profiles = ["common"]
"""
    project_root = _create_project(tmp_path, toml)

    with patch("runops.cli.knowledge.Path.cwd", return_value=project_root):
        result = runner.invoke(app, ["knowledge", "source", "status"])

    assert result.exit_code == 0
    assert "enabled" in result.output
    assert "kb" in result.output


def test_source_list_shows_configured_sources(tmp_path: Path) -> None:
    toml = """
[knowledge]
enabled = true

[[knowledge.sources]]
name = "kb"
type = "git"
kind = "profiles"
url = "https://github.com/lab/kb.git"
mount = "refs/knowledge/kb"
"""
    project_root = _create_project(tmp_path, toml)

    with patch("runops.cli.knowledge.Path.cwd", return_value=project_root):
        result = runner.invoke(app, ["knowledge", "source", "list"])

    assert result.exit_code == 0
    assert "kb" in result.output
    assert "git" in result.output


def test_source_list_includes_project_sources(tmp_path: Path) -> None:
    toml = """
[knowledge]
enabled = true

[[knowledge.sources]]
name = "kb"
type = "git"
kind = "profiles"
url = "https://github.com/lab/kb.git"
mount = "refs/knowledge/kb"

[[knowledge.sources]]
name = "legacy-project"
type = "path"
kind = "project"
path = "../legacy-project"
"""
    project_root = _create_project(tmp_path, toml)
    linked_project = tmp_path.parent / "legacy-project"
    linked_project.mkdir(parents=True, exist_ok=True)

    with patch("runops.cli.knowledge.Path.cwd", return_value=project_root):
        result = runner.invoke(app, ["knowledge", "source", "list"])

    assert result.exit_code == 0
    assert "kb" in result.output
    assert "legacy-project" in result.output
    assert "project/path" in result.output


def test_source_list_no_config(tmp_path: Path) -> None:
    project_root = _create_project(tmp_path)

    with patch("runops.cli.knowledge.Path.cwd", return_value=project_root):
        result = runner.invoke(app, ["knowledge", "source", "list"])

    assert result.exit_code == 0
    assert "No knowledge sources" in result.output


def test_source_group_list(tmp_path: Path) -> None:
    toml = """
[knowledge]
enabled = true

[[knowledge.sources]]
name = "kb"
type = "git"
kind = "profiles"
url = "https://github.com/lab/kb.git"
mount = "refs/knowledge/kb"
"""
    project_root = _create_project(tmp_path, toml)

    with patch("runops.cli.knowledge.Path.cwd", return_value=project_root):
        result = runner.invoke(app, ["knowledge", "source", "list"])

    assert result.exit_code == 0
    assert "Configured knowledge sources" in result.output
    assert "kb" in result.output


def test_sync_supports_named_project_source(tmp_path: Path) -> None:
    linked_a = tmp_path.parent / "linked-a"
    linked_b = tmp_path.parent / "linked-b"
    for linked_root, insight_name in (
        (linked_a, "alpha-note"),
        (linked_b, "beta-note"),
    ):
        insights_dir = linked_root / ".runops" / "insights"
        insights_dir.mkdir(parents=True, exist_ok=True)
        (insights_dir / f"{insight_name}.md").write_text(
            "---\n"
            "type: result\n"
            "simulator: emses\n"
            "created: 2026-04-02\n"
            "---\n\n"
            f"{insight_name}\n",
            encoding="utf-8",
        )

    project_root = _create_project(
        tmp_path,
        """
[knowledge]
enabled = true

[[knowledge.sources]]
name = "alpha"
type = "path"
kind = "project"
path = "../linked-a"

[[knowledge.sources]]
name = "beta"
type = "path"
kind = "project"
path = "../linked-b"
""",
    )

    with patch("runops.cli.knowledge.Path.cwd", return_value=project_root):
        result = runner.invoke(app, ["knowledge", "source", "sync", "alpha"])

    assert result.exit_code == 0
    assert "Importing transported knowledge from external sources" in result.output
    assert "alpha" in result.output
    assert "beta" not in result.output
    assert (project_root / ".runops" / "insights" / "alpha__alpha-note.md").is_file()
    assert not (project_root / ".runops" / "insights" / "beta__beta-note.md").exists()


def test_profile_enable_and_disable_updates_rendered_imports(tmp_path: Path) -> None:
    project_root = _create_project(
        tmp_path,
        """
[knowledge]
enabled = true

[[knowledge.sources]]
name = "kb"
type = "path"
kind = "profiles"
path = "."
mount = "refs/knowledge/kb"
profiles = ["common"]
""",
    )
    mount = project_root / "refs" / "knowledge" / "kb" / "profiles"
    mount.mkdir(parents=True)
    (mount / "common.md").write_text("# Common\n", encoding="utf-8")
    (mount / "emses.md").write_text("# EMSES\n", encoding="utf-8")

    with patch("runops.cli.knowledge.Path.cwd", return_value=project_root):
        enable = runner.invoke(
            app,
            ["knowledge", "profile", "enable", "kb", "emses"],
        )
        disable = runner.invoke(
            app,
            ["knowledge", "profile", "disable", "kb", "common"],
        )

    assert enable.exit_code == 0
    assert disable.exit_code == 0

    config = load_knowledge_config(project_root)
    assert config is not None
    assert config.sources[0].profiles == ["emses"]
    imports = (
        project_root / ".runops" / "knowledge" / "enabled" / "imports.md"
    ).read_text(encoding="utf-8")
    assert "@refs/knowledge/kb/profiles/emses.md" in imports
    assert "@refs/knowledge/kb/profiles/common.md" not in imports


def test_removed_flat_source_commands_are_unavailable() -> None:
    for argv in (
        ["knowledge", "attach", "--help"],
        ["knowledge", "status"],
        ["knowledge", "render"],
    ):
        result = runner.invoke(app, argv)
        assert result.exit_code != 0
        assert "No such command" in result.output


def test_removed_link_commands_are_unavailable() -> None:
    for argv in (
        ["knowledge", "link", "--help"],
        ["knowledge", "unlink", "--help"],
        ["knowledge", "links"],
    ):
        result = runner.invoke(app, argv)
        assert result.exit_code != 0
        assert "No such command" in result.output
