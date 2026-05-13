"""Tests for Codex harness generation."""

from __future__ import annotations

from runops.harness import (
    build_codex_config,
    build_codex_readme,
    build_codex_rules,
    build_harness_bundle,
)


def test_build_codex_config_keeps_repo_stable_defaults() -> None:
    """Config echoes the project name and avoids runtime-sensitive policy."""
    content = build_codex_config("demo")
    assert "demo" in content
    assert 'sandbox_mode = "workspace-write"' in content
    assert "project_doc_max_bytes = 65536" in content
    assert "approval_policy =" not in content
    assert "network_access =" not in content
    assert "[sandbox_workspace_write]" not in content


def test_build_codex_config_documents_trust_requirement() -> None:
    """Config comments explain the trust-level requirement for auto-loading."""
    content = build_codex_config("demo")
    assert "trust_level" in content
    assert "~/.codex/config.toml" in content


def test_build_codex_rules_allow_submit_and_gate_destructive_commands() -> None:
    """Rules allow submit but prompt/delete-gate destructive commands."""
    content = build_codex_rules()
    assert 'pattern = ["runo", "runs", "submit", "--dry-run"]' in content
    assert 'pattern = ["runops", "runs", "submit", "--dry-run"]' in content
    assert 'pattern = ["runo", "runs", "submit"]' in content
    assert 'pattern = ["runops", "runs", "submit"]' in content
    assert "does not route around a blocked `--all` command" in content
    assert 'decision = "allow"' in content
    assert 'pattern = ["runo", "runs", "purge-work"]' in content
    assert 'pattern = ["runops", "runs", "purge-work"]' in content
    assert 'pattern = ["runo", "runs", "delete"]' in content
    assert 'pattern = ["runops", "runs", "delete"]' in content
    assert 'decision = "prompt"' in content
    assert 'pattern = ["rm", "-rf"]' in content
    assert 'pattern = ["git", "reset", "--hard"]' in content
    assert 'pattern = ["git", "push", "--force"]' in content
    assert 'decision = "forbidden"' in content


def test_build_codex_readme_explains_auto_loaded_paths() -> None:
    """README lists which paths are auto-loaded and which are not."""
    content = build_codex_readme("demo")
    assert ".codex/config.toml" in content
    assert ".agents/skills/" in content
    assert ".codex/rules/runops.rules" in content
    assert "AGENTS.md" in content
    assert "AGENTS.override.md" in content
    assert "codex execpolicy check" in content
    assert ".codex/hooks.json" in content
    # Clarifies the non-auto-loaded pieces.
    assert "~/.codex/prompts/" in content


def test_build_codex_readme_explains_runtime_policy_split() -> None:
    """README separates repo-local config from runtime/user-local policy."""
    content = build_codex_readme("demo")
    assert "設定の責務分離" in content
    assert "repo-local default" in content
    assert "approval_policy" in content
    assert "network_access" in content
    assert "~/.codex/config.toml" in content
    assert ".codex/rules/*.rules" in content
    assert "runtime policy" in content


def test_build_codex_readme_explains_submit_policy() -> None:
    """README explains that submit is allowed but still requires workflow review."""
    content = build_codex_readme("demo")
    assert "runo runs submit --dry-run --all" in content
    assert "permission layer" in content
    assert "approval_policy" in content
    assert "bulk submit" in content
    assert "個別 submit に分解して迂回しない" in content
    assert "submit 系は `allow`" in content


def test_bundle_emits_codex_config_and_agents_skills() -> None:
    """build_harness_bundle emits .codex/config.toml and .agents/skills/."""
    bundle = build_harness_bundle(
        "demo",
        ["emses"],
        knowledge_imports_path=".runops/knowledge/enabled/imports.md",
    )
    assert ".codex/config.toml" in bundle.files
    assert ".codex/README.md" in bundle.files
    assert ".codex/rules/runops.rules" in bundle.files
    assert ".agents/skills/new-case/SKILL.md" in bundle.files
    assert ".agents/skills/setup-runops/SKILL.md" in bundle.files
    assert ".agents/skills/research-agenda/SKILL.md" in bundle.files
    assert ".agents/skills/summarize-script/SKILL.md" in bundle.files
    assert ".agents/skills/patch-runops/SKILL.md" in bundle.files
    assert ".agents/skills/update-runops/SKILL.md" in bundle.files
    assert ".agents/skills/migrate-runops/SKILL.md" in bundle.files
    assert ".agents/skills/python-package-refactor/SKILL.md" in bundle.files
    assert (
        ".agents/skills/python-package-refactor/scripts/inspect_python_package.py"
        in bundle.files
    )
    assert (
        ".agents/skills/python-package-refactor/references/refactor-playbook.md"
        in bundle.files
    )
    assert ".agents/skills/python-package-refactor/README.md" not in bundle.files
    assert ".agents/skills/python-package-refactor/manifest.txt" not in bundle.files
    assert "cases/AGENTS.md" in bundle.files
    assert "runs/AGENTS.md" in bundle.files
    agents = bundle.files["AGENTS.md"]
    assert "性質ごとに書き先を分ける" in agents
    assert "$research-agenda" in agents
    assert "$summarize-script" in agents
    assert "$patch-runops" in agents
    assert "$update-runops" in agents
    assert "$migrate-runops" in agents
    assert "$python-package-refactor" in agents
    assert "$setup-runops" in agents
    assert "active question、current decision、paused/killed" in agents
    # Skills share the same frontmatter, but use each agent's native
    # invocation syntax in the body.
    claude_note = bundle.files[".claude/skills/note/SKILL.md"]
    codex_note = bundle.files[".agents/skills/note/SKILL.md"]
    assert "name: note" in claude_note
    assert "name: note" in codex_note
    assert "`/note`" in claude_note
    assert "`/learn`" in claude_note
    assert "`$note`" in codex_note
    assert "`$learn`" in codex_note
    assert "`/note`" not in codex_note
    assert "{{ skill_prefix }}" not in codex_note
    assert "Model name must not stand alone" in codex_note
    assert "Figures are first-class note content" in codex_note
    assert "Quality gate before append" in codex_note
    codex_run_all = bundle.files[".agents/skills/run-all/SKILL.md"]
    assert "runo runs submit --dry-run --all" in codex_run_all
    assert "runo runs submit --all --dry-run" not in codex_run_all
    codex_refactor = bundle.files[".agents/skills/python-package-refactor/SKILL.md"]
    claude_refactor = bundle.files[".claude/skills/python-package-refactor/SKILL.md"]
    assert ".agents/skills/python-package-refactor/scripts/" in codex_refactor
    assert ".claude/skills/python-package-refactor/scripts/" in claude_refactor
    assert "{{ skills_dir }}" not in codex_refactor
    codex_summarize = bundle.files[".agents/skills/summarize-script/SKILL.md"]
    assert "`$note`" in codex_summarize
    assert "cases/<simulator>/<case>/summarize.py" in codex_summarize
    assert "{{ skill_prefix }}" not in codex_summarize
    codex_migrate = bundle.files[".agents/skills/migrate-runops/SKILL.md"]
    assert "`$update-runops`" in codex_migrate
    assert "`$feedback-runops`" in codex_migrate
    assert "runo migrate list" in codex_migrate
    assert "{{ skill_prefix }}" not in codex_migrate
    codex_feedback = bundle.files[".agents/skills/feedback-runops/SKILL.md"]
    assert "hops add-failure" in codex_feedback
    assert "hops feedback export --target runops --sanitize" in codex_feedback
    codex_setup = bundle.files[".agents/skills/setup-runops/SKILL.md"]
    claude_setup = bundle.files[".claude/skills/setup-runops/SKILL.md"]
    assert "`$setup-env`" in codex_setup
    assert "`$setup-campaign`" in codex_setup
    assert "project は生成済み" in codex_setup
    assert "状態確認だけで応答を終えない" in codex_setup
    assert "必ず「セットアップ後に行うこと」" in codex_setup
    assert "project の状態はこちらで確認します" in codex_setup
    assert "doctor で未解決の項目はありますか" not in codex_setup
    assert 'git commit -m "chore: scaffold runops project"' in codex_setup
    assert "`/setup-env`" in claude_setup
    assert "状態確認だけで応答を終えない" in claude_setup
    assert 'git commit -m "chore: scaffold runops project"' in claude_setup
    assert "{{ skill_prefix }}" not in codex_setup


def test_bundle_does_not_emit_project_local_codex_prompts() -> None:
    """Project-local slash prompts are unsupported by Codex."""
    bundle = build_harness_bundle(
        "demo",
        ["emses"],
        knowledge_imports_path=".runops/knowledge/enabled/imports.md",
    )
    assert not any(path.startswith(".codex/prompts/") for path in bundle.files)


def test_agents_md_does_not_use_import_syntax() -> None:
    """AGENTS.md must not rely on Claude's @file import syntax."""
    bundle = build_harness_bundle(
        "demo",
        ["emses"],
        knowledge_imports_path=".runops/knowledge/enabled/imports.md",
    )
    agents = bundle.files["AGENTS.md"]
    assert "@SITE.md" not in agents
    assert "@.runops/knowledge" not in agents
    # Plain path references are used instead.
    assert ".runops/knowledge/enabled/imports.md" in agents
    assert "SITE.md" in agents
    # Skills are referenced by the Codex path.
    assert ".agents/skills/" in agents
    # Codex skills are invoked by mention, not Claude slash commands.
    assert "$new-case" in agents
    assert "/new-case" not in agents


def test_agents_md_inlines_shared_codex_rules() -> None:
    """Codex gets shared cookbook/upstream guidance through AGENTS.md."""
    bundle = build_harness_bundle(
        "demo",
        ["emses"],
        upstream_feedback=True,
    )
    agents = bundle.files["AGENTS.md"]
    assert "## Codex 補助ルール" in agents
    assert "### Simulator Cookbook ルール" in agents
    assert "### runops へのフィードバック" in agents
    # The Claude rule frontmatter must not be embedded into AGENTS.md.
    assert "globs: refs/**/cookbook/**" not in agents


def test_agents_md_omits_empty_codex_rules_section() -> None:
    """No empty Codex rules section is emitted when no shared rules apply."""
    bundle = build_harness_bundle(
        "demo",
        [],
        upstream_feedback=False,
    )
    agents = bundle.files["AGENTS.md"]
    assert "## Codex 補助ルール" not in agents
    assert "Simulator Cookbook ルール" not in agents
    assert "runops へのフィードバック" not in agents


def test_claude_md_keeps_import_syntax() -> None:
    """CLAUDE.md continues to use @file imports (Claude Code supports it)."""
    bundle = build_harness_bundle(
        "demo",
        ["emses"],
        knowledge_imports_path=".runops/knowledge/enabled/imports.md",
    )
    claude = bundle.files["CLAUDE.md"]
    assert "@SITE.md" in claude
    assert "@.runops/knowledge/enabled/imports.md" in claude
    assert ".claude/skills/" in claude
    assert "/new-case" in claude
    assert "Codex 補助ルール" not in claude


def test_harness_prefixes_include_agents_and_codex() -> None:
    """is_harness_path covers the new .codex and .agents paths."""
    from runops.harness.builder import is_harness_path

    assert is_harness_path(".codex/config.toml")
    assert is_harness_path(".codex/README.md")
    assert is_harness_path(".codex/rules/runops.rules")
    assert is_harness_path(".vscode/settings.json")
    assert is_harness_path(".gitignore")
    assert is_harness_path(".agents/skills/new-case/SKILL.md")
    assert is_harness_path("cases/AGENTS.md")
    assert is_harness_path("runs/AGENTS.md")
