"""Drift checks for active runops development guidance."""

from __future__ import annotations

from pathlib import Path

import pytest
import tomli

ROOT = Path(__file__).resolve().parents[2]

IMPLEMENT_CORE = (
    ".agents/skills/implement-core/SKILL.md",
    ".claude/agents/implement-core.md",
    ".codex/agents/implement-core.toml",
)
IMPLEMENT_CLI = (
    ".agents/skills/implement-cli/SKILL.md",
    ".claude/agents/implement-cli.md",
    ".codex/agents/implement-cli.toml",
)
REVIEW_AND_TEST = (
    ".agents/skills/spec-reviewer/SKILL.md",
    ".claude/agents/spec-reviewer.md",
    ".codex/agents/spec-reviewer.toml",
    ".agents/skills/test-writer/SKILL.md",
    ".claude/agents/test-writer.md",
    ".codex/agents/test-writer.toml",
)
SIMULATOR_GUIDANCE = (
    ".agents/skills/beach/SKILL.md",
    ".agents/skills/emses/SKILL.md",
    ".claude/agents/beach.md",
    ".claude/agents/emses.md",
    ".codex/agents/beach.toml",
    ".codex/agents/emses.toml",
    "src/runops/templates/adapters/beach/agent_guide.md",
    "src/runops/templates/adapters/emses/agent_guide.md",
)
SIMULATOR_DEV_SKILLS = (
    ".agents/skills/beach/SKILL.md",
    ".agents/skills/emses/SKILL.md",
)
ACTIVE_GUIDANCE = IMPLEMENT_CORE + IMPLEMENT_CLI + REVIEW_AND_TEST + SIMULATOR_GUIDANCE
ARCHITECTURE_DOCS = (
    ".codex/rules/architecture.md",
    ".claude/rules/architecture.md",
    "docs/architecture.md",
    "docs/layers/interface.md",
    "docs/layers/knowledge.md",
    "SPEC.md",
)
CONTEXT_MODEL_DOCS = (
    ".codex/rules/architecture.md",
    ".claude/rules/architecture.md",
    "docs/architecture.md",
    "SPEC.md",
)
PROJECT_GUIDANCE = ("AGENTS.md", "CLAUDE.md")


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


@pytest.mark.parametrize("relative_path", IMPLEMENT_CORE)
def test_implement_core_guidance_uses_canonical_manifest_contract(
    relative_path: str,
) -> None:
    text = _read(relative_path)

    assert "RYYYYMMDD-NNNN" in text
    assert "params_snapshot" in text
    assert "SPEC.md" in text
    assert ".codex/rules/commands.md" in text


@pytest.mark.parametrize("relative_path", IMPLEMENT_CLI)
def test_implement_cli_guidance_uses_grouped_command_surface(
    relative_path: str,
) -> None:
    text = _read(relative_path)

    assert "runo runs submit" in text
    assert "SPEC.md" in text
    assert ".codex/rules/commands.md" in text


@pytest.mark.parametrize("relative_path", REVIEW_AND_TEST)
def test_review_and_test_guidance_links_canonical_sources(relative_path: str) -> None:
    text = _read(relative_path)

    assert "SPEC.md" in text
    assert ".codex/rules/commands.md" in text


@pytest.mark.parametrize("relative_path", SIMULATOR_GUIDANCE)
def test_simulator_guidance_uses_grouped_commands(relative_path: str) -> None:
    text = _read(relative_path)

    assert "runo runs create" in text
    assert "runo runs submit" in text
    assert "runo runs status" in text
    assert "runo analyze summarize" in text
    assert "runo analyze collect" in text


@pytest.mark.parametrize("relative_path", ACTIVE_GUIDANCE)
def test_active_guidance_has_no_obsolete_examples(relative_path: str) -> None:
    text = _read(relative_path)

    assert "01HQ3" not in text
    assert "[state]" not in text
    assert "[parameters]" not in text
    assert "runops submit RUN" not in text
    assert "`runo create`" not in text
    assert "`runo submit`" not in text
    assert "`runo status`" not in text
    assert "`runo summarize`" not in text
    assert "`runo collect`" not in text
    assert "tests/test_core/test_plugins.py" not in text
    assert "tests/test_core/test_context.py" not in text


@pytest.mark.parametrize("relative_path", SIMULATOR_DEV_SKILLS)
def test_simulator_guidance_names_current_application_tests(
    relative_path: str,
) -> None:
    text = _read(relative_path)

    assert "tests/test_application/test_plugins.py" in text
    assert "tests/test_application/test_context.py" in text


@pytest.mark.parametrize("relative_path", ARCHITECTURE_DOCS)
def test_architecture_docs_name_current_contexts_and_dependency_direction(
    relative_path: str,
) -> None:
    text = _read(relative_path)

    assert "Execution Kernel" in text
    assert "Research Workspace" in text
    assert "Agent Gateway" in text
    assert "Operator/Developer" in text
    assert "core -> application -> interfaces/infrastructure" in text


@pytest.mark.parametrize("relative_path", CONTEXT_MODEL_DOCS)
def test_operator_context_owns_harness_update_and_demo_replay(
    relative_path: str,
) -> None:
    text = _read(relative_path)

    assert "update-harness" in text
    assert "demo replay" in text


def test_codex_and_claude_architecture_rules_are_identical() -> None:
    assert _read(".codex/rules/architecture.md") == _read(
        ".claude/rules/architecture.md"
    )


def test_codex_and_claude_command_rules_are_identical() -> None:
    assert _read(".codex/rules/commands.md") == _read(".claude/rules/commands.md")


def test_command_rules_keep_recovered_command_paths_and_arguments() -> None:
    text = _read(".codex/rules/commands.md")
    required_paths = (
        "runo migrate show MIGRATION [NUMBER]",
        "runo migrate apply MIGRATION [NUMBER]",
        "runo knowledge save NAME",
        "runo knowledge show NAME",
        "runo knowledge add-fact CLAIM",
        "runo knowledge promote-fact FACT_ID",
        "runo knowledge source attach SOURCE_TYPE NAME URL_OR_PATH",
        "runo knowledge source detach NAME",
        "runo knowledge source list",
        "runo knowledge profile enable SOURCE_NAME PROFILE_NAMES...",
        "runo knowledge profile disable SOURCE_NAME PROFILE_NAMES...",
        "runo demo import-codex-session SESSION_LOG --out PATH",
        "runo demo render-replay EVENTS --out PATH",
        "runo demo build-codex-replay [SESSION_LOG] --out PATH",
    )

    for command in required_paths:
        assert command in text


def test_all_codex_agent_toml_files_parse() -> None:
    for path in sorted((ROOT / ".codex/agents").glob("*.toml")):
        tomli.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("relative_path", PROJECT_GUIDANCE)
def test_project_guidance_names_application_boundary(relative_path: str) -> None:
    text = _read(relative_path)

    assert "application/" in text
    assert "core/" in text


def test_v0_migration_note_records_surface_and_internal_moves() -> None:
    text = _read("docs/migrations/v0.md")

    assert "runo runs submit" in text
    assert "--yes" in text
    assert "--force" in text
    assert "hidden" in text
    assert "core/" in text
    assert "application/" in text
