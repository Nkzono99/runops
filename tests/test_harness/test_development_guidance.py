"""Drift checks for active runops development guidance."""

from __future__ import annotations

from pathlib import Path

import pytest

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
ACTIVE_GUIDANCE = IMPLEMENT_CORE + IMPLEMENT_CLI + REVIEW_AND_TEST
ARCHITECTURE_DOCS = (
    ".codex/rules/architecture.md",
    ".claude/rules/architecture.md",
    "docs/architecture.md",
    "docs/layers/interface.md",
    "docs/layers/knowledge.md",
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


@pytest.mark.parametrize("relative_path", ACTIVE_GUIDANCE)
def test_active_guidance_has_no_obsolete_examples(relative_path: str) -> None:
    text = _read(relative_path)

    assert "01HQ3" not in text
    assert "[state]" not in text
    assert "[parameters]" not in text
    assert "runops submit RUN" not in text


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


def test_codex_and_claude_architecture_rules_are_identical() -> None:
    assert _read(".codex/rules/architecture.md") == _read(
        ".claude/rules/architecture.md"
    )


def test_codex_and_claude_command_rules_are_identical() -> None:
    assert _read(".codex/rules/commands.md") == _read(".claude/rules/commands.md")


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
