"""Tests for runops init and runops doctor CLI commands."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
import typer
from typer.testing import CliRunner

from runops.cli.main import app
from runops.core.codex_plugin import CodexPluginRecommendation
from runops.core.environment import EnvironmentInfo
from runops.harness.builder import GITIGNORE_MANAGED_END, GITIGNORE_MANAGED_START
from runops.harness.harnessops import HarnessOpsResult

runner = CliRunner()


@pytest.fixture(autouse=True)
def _mock_bootstrap(
    monkeypatch: pytest.MonkeyPatch,
    mock_init_external_processes: None,
) -> None:
    """Skip the bootstrap step (uv install) in all init tests."""
    del mock_init_external_processes
    monkeypatch.setattr(
        "runops.cli.init._bootstrap_environment",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "runops.harness.harnessops.initialize_project_harnessops",
        lambda *_args, **_kwargs: HarnessOpsResult(
            "skipped",
            "HarnessOps skipped (test)",
        ),
    )
    monkeypatch.setattr(
        "runops.core.environment.detect_environment",
        lambda: EnvironmentInfo(cluster_name="test-cluster"),
    )
    monkeypatch.setattr(
        "runops.cli.init.command.ensure_github_auth_for_simulators",
        lambda *_args, **_kwargs: None,
    )


class TestInit:
    """Tests for the 'runops init' command."""

    def test_init_creates_all_files(self, tmp_path: Path) -> None:
        """Init in an empty directory creates all expected files and dirs."""
        result = runner.invoke(app, ["init", "-y", "--path", str(tmp_path)])
        assert result.exit_code == 0
        assert (tmp_path / "runops.toml").exists()
        assert (tmp_path / "simulators.toml").exists()
        assert (tmp_path / "launchers.toml").exists()
        assert (tmp_path / "campaign.toml").exists()
        assert (tmp_path / "cases").is_dir()
        assert (tmp_path / "runs").is_dir()
        assert (tmp_path / ".gitignore").exists()

    def test_init_invokes_harnessops(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Init delegates project overlay creation to hops when enabled."""
        calls: list[Path] = []

        def _fake_harnessops(project_dir: Path) -> HarnessOpsResult:
            calls.append(project_dir)
            return HarnessOpsResult("created", "HarnessOps initialized")

        monkeypatch.setattr(
            "runops.harness.harnessops.initialize_project_harnessops",
            _fake_harnessops,
        )
        result = runner.invoke(app, ["init", "-y", "--path", str(tmp_path)])

        assert result.exit_code == 0
        assert calls == [tmp_path.resolve()]
        assert "HarnessOps initialized" in result.output

    def test_init_can_skip_harnessops(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--no-harnessops disables the hops lifecycle hook."""

        def _fail_harnessops(_project_dir: Path) -> HarnessOpsResult:
            raise AssertionError("should not be called")

        monkeypatch.setattr(
            "runops.harness.harnessops.initialize_project_harnessops",
            _fail_harnessops,
        )
        result = runner.invoke(
            app,
            ["init", "-y", "--no-harnessops", "--path", str(tmp_path)],
        )

        assert result.exit_code == 0
        assert "HarnessOps (disabled)" in result.output
        assert (tmp_path / ".git").is_dir()
        assert (tmp_path / "CLAUDE.md").exists()
        assert (tmp_path / "AGENTS.md").exists()
        assert (tmp_path / ".runops" / "knowledge" / "candidates" / "facts").is_dir()
        assert (tmp_path / ".claude" / "skills").is_dir()
        assert (tmp_path / ".agents" / "skills").is_dir()
        assert (tmp_path / ".codex" / "config.toml").exists()
        assert (tmp_path / ".codex" / "rules" / "runops.rules").exists()
        assert (tmp_path / ".vscode" / "settings.json").exists()
        # Lab notebook scaffolding
        assert (tmp_path / "notes").is_dir()
        assert (tmp_path / "notes" / "reports").is_dir()
        assert (tmp_path / "notes" / "reports" / "README.md").is_file()
        assert (tmp_path / "notes" / "reports" / "archive").is_dir()
        assert (tmp_path / "notes" / "reports" / "figures").is_dir()
        assert (tmp_path / "notes" / "history").is_dir()
        assert (tmp_path / "notes" / "README.md").is_file()
        # Source material scaffolding
        assert (tmp_path / "materials").is_dir()
        assert (tmp_path / "materials" / "papers").is_dir()
        assert (tmp_path / "materials" / "manuals").is_dir()
        assert (tmp_path / "materials" / "figures").is_dir()
        assert (tmp_path / "materials" / "snippets").is_dir()
        assert (tmp_path / "materials" / "README.md").is_file()
        assert (tmp_path / "materials" / "index.toml").is_file()
        # Research decision-layer scaffolding
        assert (tmp_path / "research").is_dir()
        assert (tmp_path / "research" / "README.md").is_file()
        assert (tmp_path / "research" / "agenda.md").is_file()
        assert (tmp_path / "research" / "proposals").is_dir()
        assert (tmp_path / "research" / "reviews").is_dir()

    def test_init_notes_readme_content(self, tmp_path: Path) -> None:
        """notes/README.md describes the lab-notebook convention."""
        runner.invoke(app, ["init", "-y", "--path", str(tmp_path)])
        readme = (tmp_path / "notes" / "README.md").read_text(encoding="utf-8")
        assert "lab notebook" in readme
        assert "runo notes append" in readme
        assert "runo notes archive" in readme
        assert "notes/YYYY-MM-DD.md" in readme
        assert "notes/history/YYYY/YYYY-MM-DD.md" in readme
        assert "notes/reports/README.md" in readme
        assert "Markdown だけで図を確認できる" in readme
        assert "再開できるログ" in readme
        assert "Context:" in readme
        assert "Evidence:" in readme
        assert "Observation:" in readme
        assert "Interpretation:" in readme

    def test_init_reports_readme_content(self, tmp_path: Path) -> None:
        """notes/reports/README.md describes report-index conventions."""
        runner.invoke(app, ["init", "-y", "--path", str(tmp_path)])
        readme = (tmp_path / "notes" / "reports" / "README.md").read_text(
            encoding="utf-8"
        )

        assert "Recommended Reading Order" in readme
        assert "Machine-Readable Entry Points" in readme
        assert "Heavy / Recovery-Only Material" in readme
        assert "Markdown image" in readme
        assert "analysis/cross_run/<comparison_id>/" in readme

    def test_init_materials_readme_content(self, tmp_path: Path) -> None:
        """materials/README.md describes visible source material storage."""
        runner.invoke(app, ["init", "-y", "--path", str(tmp_path)])
        readme = (tmp_path / "materials" / "README.md").read_text(encoding="utf-8")
        index = (tmp_path / "materials" / "index.toml").read_text(encoding="utf-8")
        assert "source material" in readme
        assert "human/agent shared workspace" in readme
        assert ".runops/knowledge/" in readme
        assert "materials/**/*.pdf" in readme
        assert "local by default" in readme
        assert "materials = []" in index

    def test_init_research_scaffold_content(self, tmp_path: Path) -> None:
        """research/ documents the mutable decision-ledger convention."""
        runner.invoke(app, ["init", "-y", "--path", str(tmp_path)])
        readme = (tmp_path / "research" / "README.md").read_text(encoding="utf-8")
        agenda = (tmp_path / "research" / "agenda.md").read_text(encoding="utf-8")

        assert "研究判断の台帳" in readme
        assert "TODO リストではなく" in readme
        assert "agenda.md is not an artifact ledger" in readme
        assert "Do not put chronological notes or artifact inventories" in readme
        assert "本文は日本語" in readme
        assert "mutable な現在の研究判断の台帳" in agenda
        assert "agenda.md is not an artifact ledger" in agenda
        assert "What Would Change Our Mind" in agenda
        assert "Human gate: yes/no" in agenda

    def test_init_creates_note_skill(self, tmp_path: Path) -> None:
        """The note skill is scaffolded next to the other skills."""
        runner.invoke(app, ["init", "-y", "--path", str(tmp_path)])
        skill_md = tmp_path / ".claude" / "skills" / "note" / "SKILL.md"
        codex_skill_md = tmp_path / ".agents" / "skills" / "note" / "SKILL.md"
        assert skill_md.is_file()
        assert codex_skill_md.is_file()
        content = skill_md.read_text(encoding="utf-8")
        codex_content = codex_skill_md.read_text(encoding="utf-8")
        assert "name: note" in content
        assert "runo notes append" in content
        assert "name: note" in codex_content
        assert "runo notes append" in codex_content
        assert "`/note`" in content
        assert "`$note`" in codex_content
        assert "`/note`" not in codex_content
        assert "Model name must not stand alone" in codex_content
        assert "Figures are first-class note content" in codex_content
        assert "Do not replace image embeds with plain Markdown links" in codex_content
        assert "notes/reports/README.md" in codex_content
        assert "Quality gate before append" in codex_content

    def test_init_creates_research_agenda_skill(self, tmp_path: Path) -> None:
        """The research-agenda skill is rendered for Claude and Codex."""
        runner.invoke(app, ["init", "-y", "--path", str(tmp_path)])
        skill_md = tmp_path / ".claude" / "skills" / "research-agenda" / "SKILL.md"
        codex_skill_md = (
            tmp_path / ".agents" / "skills" / "research-agenda" / "SKILL.md"
        )

        assert skill_md.is_file()
        assert codex_skill_md.is_file()
        content = skill_md.read_text(encoding="utf-8")
        codex_content = codex_skill_md.read_text(encoding="utf-8")
        assert "name: research-agenda" in content
        assert "research/agenda.md" in content
        assert "本文は日本語" in content
        assert "判断の台帳" in codex_content
        assert "agenda.md is not an artifact ledger" in codex_content
        assert (
            "Do not put chronological notes or artifact inventories back into agenda.md"
            in codex_content
        )
        assert "notes/reports/README.md" in codex_content
        assert "analysis/cross_run/<comparison_id>/" in codex_content
        assert (tmp_path / "research" / "paper_requests.toml").is_file()

    def test_init_creates_migrate_runops_skill(self, tmp_path: Path) -> None:
        """The migrate-runops skill is rendered for Claude and Codex."""
        runner.invoke(app, ["init", "-y", "--path", str(tmp_path)])
        skill_md = tmp_path / ".claude" / "skills" / "migrate-runops" / "SKILL.md"
        codex_skill_md = tmp_path / ".agents" / "skills" / "migrate-runops" / "SKILL.md"

        assert skill_md.is_file()
        assert codex_skill_md.is_file()
        content = skill_md.read_text(encoding="utf-8")
        codex_content = codex_skill_md.read_text(encoding="utf-8")
        assert "name: migrate-runops" in content
        assert "docs/migrations/" in content
        assert "Human gate" in content
        assert "`/update-runops`" in content
        assert "`$update-runops`" in codex_content
        assert "{{ skill_prefix }}" not in codex_content

    def test_init_creates_python_package_refactor_skill_resources(
        self,
        tmp_path: Path,
    ) -> None:
        """Skill resources are scaffolded beside python-package-refactor."""
        runner.invoke(app, ["init", "-y", "--path", str(tmp_path)])
        codex_skill_dir = tmp_path / ".agents" / "skills" / "python-package-refactor"
        claude_skill_dir = tmp_path / ".claude" / "skills" / "python-package-refactor"

        assert (codex_skill_dir / "SKILL.md").is_file()
        assert (codex_skill_dir / "scripts" / "inspect_python_package.py").is_file()
        assert (codex_skill_dir / "references" / "refactor-playbook.md").is_file()
        assert not (codex_skill_dir / "README.md").exists()
        assert not (codex_skill_dir / "manifest.txt").exists()
        assert (claude_skill_dir / "scripts" / "inspect_python_package.py").is_file()

        codex_content = (codex_skill_dir / "SKILL.md").read_text(encoding="utf-8")
        claude_content = (claude_skill_dir / "SKILL.md").read_text(encoding="utf-8")
        assert "name: python-package-refactor" in codex_content
        assert ".agents/skills/python-package-refactor/scripts/" in codex_content
        assert ".claude/skills/python-package-refactor/scripts/" in claude_content
        assert "{{ skills_dir }}" not in codex_content

    def test_init_simproject_content(self, tmp_path: Path) -> None:
        """runops.toml has correct project name derived from dir name."""
        result = runner.invoke(app, ["init", "-y", "--path", str(tmp_path)])
        assert result.exit_code == 0
        content = (tmp_path / "runops.toml").read_text(encoding="utf-8")
        assert "[project]" in content
        assert f'name = "{tmp_path.name}"' in content

    def test_init_custom_name(self, tmp_path: Path) -> None:
        """--name option overrides directory name in runops.toml."""
        result = runner.invoke(
            app, ["init", "-y", "--path", str(tmp_path), "--name", "my-project"]
        )
        assert result.exit_code == 0
        content = (tmp_path / "runops.toml").read_text(encoding="utf-8")
        assert 'name = "my-project"' in content
        assert "my-project" in result.output

    def test_init_simulators_content(self, tmp_path: Path) -> None:
        """simulators.toml has empty [simulators] section."""
        runner.invoke(app, ["init", "-y", "--path", str(tmp_path)])
        content = (tmp_path / "simulators.toml").read_text(encoding="utf-8")
        assert "[simulators]" in content

    def test_init_launchers_content(self, tmp_path: Path) -> None:
        """launchers.toml has default srun launcher."""
        runner.invoke(app, ["init", "-y", "--path", str(tmp_path)])
        content = (tmp_path / "launchers.toml").read_text(encoding="utf-8")
        assert "[launchers.srun]" in content
        assert 'type = "srun"' in content
        assert "use_slurm_ntasks = true" in content

    def test_init_campaign_content(self, tmp_path: Path) -> None:
        """campaign.toml is created with schema and simulator hint."""
        runner.invoke(app, ["init", "emses", "-y", "--path", str(tmp_path)])
        content = (tmp_path / "campaign.toml").read_text(encoding="utf-8")
        assert "#:schema" in content
        assert "[campaign]" in content
        assert f'name = "{tmp_path.name}"' in content
        assert 'simulator = "emses"' in content
        assert "[variables]" in content
        assert "[observables]" in content

    def test_init_gitignore_content(self, tmp_path: Path) -> None:
        """.gitignore contains run output exclusion patterns."""
        runner.invoke(app, ["init", "-y", "--path", str(tmp_path)])
        content = (tmp_path / ".gitignore").read_text(encoding="utf-8")
        assert GITIGNORE_MANAGED_START in content
        assert GITIGNORE_MANAGED_END in content
        # The whole work/ tree is regenerable from input/, so it is excluded
        # wholesale rather than enumerating per-simulator output filenames.
        assert "runs/**/work/" in content
        assert "runs/**/status/" in content
        assert "**/.runops-submit.lock" in content
        assert "runs/**/input/plasma.inp" in content
        assert "runs/**/analysis/scratch/" in content
        assert "materials/**/*.pdf" in content
        assert "materials/**/*.pptx" in content
        assert "materials/**/*.docx" in content
        assert "materials/**/*.zip" in content
        assert "!materials/README.md" in content
        assert "!materials/index.toml" in content
        assert "AGENTS.override.md" in content

    def test_init_vscode_settings_keep_run_artifacts_visible(
        self,
        tmp_path: Path,
    ) -> None:
        """VS Code keeps useful run artifacts visible while hiding internals."""
        runner.invoke(app, ["init", "-y", "--path", str(tmp_path)])
        settings = json.loads(
            (tmp_path / ".vscode" / "settings.json").read_text(encoding="utf-8")
        )

        files_exclude = settings["files.exclude"]
        assert files_exclude[".venv"] is True
        assert files_exclude[".ruff_cache"] is True
        assert files_exclude[".pytest_cache"] is True
        assert files_exclude["tools"] is True
        assert files_exclude["refs"] is True
        assert files_exclude[".runops/knowledge"] is True
        assert files_exclude[".runops/environment.toml"] is True
        assert "runs/**/work" not in files_exclude
        assert files_exclude["runs/**/status"] is True
        assert "runs/**/submit" not in files_exclude
        assert files_exclude["runs/**/manifest.toml"] is True
        assert "cases" not in files_exclude
        assert "notes" not in files_exclude
        assert "materials" not in files_exclude
        assert "runs/**/survey.toml" not in files_exclude

        search_exclude = settings["search.exclude"]
        assert search_exclude[".ruff_cache"] is True
        assert search_exclude[".pytest_cache"] is True
        assert search_exclude["runs/**/work"] is True
        assert "runs/**/submit" not in search_exclude
        assert search_exclude["materials/**/*.pdf"] is True
        assert "materials" not in search_exclude

        watcher_exclude = settings["files.watcherExclude"]
        assert watcher_exclude[".venv/**"] is True
        assert watcher_exclude[".ruff_cache/**"] is True
        assert watcher_exclude[".pytest_cache/**"] is True
        assert watcher_exclude["runs/**/work/**"] is True
        assert watcher_exclude["runs/**/status/**"] is True
        assert "runs/**/submit/**" not in watcher_exclude

        analysis_exclude = settings["python.analysis.exclude"]
        assert "**/node_modules" in analysis_exclude
        assert "**/__pycache__" in analysis_exclude
        assert "**/.*" in analysis_exclude
        assert ".venv" in analysis_exclude
        assert ".ruff_cache" in analysis_exclude
        assert ".pytest_cache" in analysis_exclude
        assert "refs" in analysis_exclude
        assert "runs/**/work" in analysis_exclude
        assert "runs/**/submit" not in analysis_exclude

    def test_init_skips_existing_files(self, tmp_path: Path) -> None:
        """Init does not overwrite existing files."""
        (tmp_path / "runops.toml").write_text('[project]\nname = "original"\n')
        result = runner.invoke(app, ["init", "-y", "--path", str(tmp_path)])
        assert result.exit_code == 0
        content = (tmp_path / "runops.toml").read_text(encoding="utf-8")
        assert 'name = "original"' in content
        assert "Skipped" in result.output

    def test_init_reports_created_items(self, tmp_path: Path) -> None:
        """Init output lists created items."""
        result = runner.invoke(app, ["init", "-y", "--path", str(tmp_path)])
        assert result.exit_code == 0
        assert "Created:" in result.output
        assert "runops.toml" in result.output

    def test_init_creates_target_directory(self, tmp_path: Path) -> None:
        """Init creates the target directory if it does not exist."""
        target = tmp_path / "new-project"
        result = runner.invoke(app, ["init", "-y", "--path", str(target)])
        assert result.exit_code == 0
        assert target.is_dir()
        assert (target / "runops.toml").exists()

    def test_init_defaults_to_cwd(self, tmp_path: Path) -> None:
        """Init without path argument uses current working directory."""
        import os

        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = runner.invoke(app, ["init", "-y"])
            assert result.exit_code == 0
            assert (tmp_path / "runops.toml").exists()
        finally:
            os.chdir(original_cwd)

    def test_init_skips_git_init_if_exists(self, tmp_path: Path) -> None:
        """Init skips git init when .git already exists."""
        (tmp_path / ".git").mkdir()
        result = runner.invoke(app, ["init", "-y", "--path", str(tmp_path)])
        assert result.exit_code == 0
        assert "git init" in result.output
        assert "Skipped" in result.output

    def test_init_claude_md_with_simulators(self, tmp_path: Path) -> None:
        """CLAUDE.md defaults to plugin/knowledge guidance without refs."""
        result = runner.invoke(
            app,
            ["init", "emses", "beach", "-y", "--path", str(tmp_path)],
        )
        assert result.exit_code == 0
        assert "Recommended Codex plugins" in result.output
        assert "MPIEMSES3D Context" in result.output
        assert "emout Context" in result.output
        assert "Capabilities: input-review, parameter-design" in result.output
        content = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
        # Simulator details are via imports.md, not inline
        assert "シミュレータ固有知識" not in content
        assert "Agent ガイド" not in content
        assert "runo context" in content
        assert "campaign.toml" in content
        assert "推奨 Codex plugins" in content
        assert "MPIEMSES3D Context" in content
        assert "emout Context" in content
        assert "任意のリファレンスミラー" not in content
        cookbook_rule = tmp_path / ".claude" / "rules" / "cookbook.md"
        assert not cookbook_rule.exists()

    def test_init_with_refs_includes_reference_guidance(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """--with-refs opts into local refs mirrors and cookbook guidance."""
        auth_calls: list[bool] = []

        def _record_auth(
            _sim_names: list[str],
            *,
            interactive: bool,
            login: bool,
            skip: bool,
            include_refs: bool,
        ) -> None:
            del interactive, login, skip
            auth_calls.append(include_refs)

        monkeypatch.setattr(
            "runops.cli.init.command.ensure_github_auth_for_simulators",
            _record_auth,
        )
        monkeypatch.setattr(
            "runops.cli.init.command._clone_doc_repos",
            lambda *_args, **_kwargs: (["refs/MPIEMSES3D/"], []),
        )

        result = runner.invoke(
            app,
            ["init", "emses", "-y", "--with-refs", "--path", str(tmp_path)],
        )

        assert result.exit_code == 0
        assert auth_calls == [True]
        content = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
        assert "任意のリファレンスミラー" in content
        assert "refs/MPIEMSES3D" in content
        cookbook_rule = tmp_path / ".claude" / "rules" / "cookbook.md"
        assert cookbook_rule.exists()
        assert "cookbook" in cookbook_rule.read_text(encoding="utf-8").lower()

    def test_init_claude_md_without_simulators(self, tmp_path: Path) -> None:
        """CLAUDE.md is generated without simulator sections when none given."""
        runner.invoke(app, ["init", "-y", "--path", str(tmp_path)])
        content = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
        assert "runops" in content
        assert "シミュレータ固有知識" not in content
        # No cookbook rule when no simulators
        cookbook_rule = tmp_path / ".claude" / "rules" / "cookbook.md"
        assert not cookbook_rule.exists()

    def test_init_agents_md(self, tmp_path: Path) -> None:
        """AGENTS.md is generated as a standalone instruction file."""
        runner.invoke(app, ["init", "emses", "-y", "--path", str(tmp_path)])
        agents_path = tmp_path / "AGENTS.md"
        assert agents_path.exists()
        assert not agents_path.is_symlink()
        content = agents_path.read_text(encoding="utf-8")
        assert "runops" in content
        assert "runo context" in content
        assert "役割分担" in content
        assert "$new-case" in content
        assert "/new-case" not in content
        assert "Codex 補助ルール" in content
        assert "runops へのフィードバック" in content
        assert "Simulator Cookbook ルール" not in content
        assert "globs: refs/**/cookbook/**" not in content

    def test_init_skills(self, tmp_path: Path) -> None:
        """Individual SKILL.md files are created for Claude and Codex."""
        runner.invoke(app, ["init", "-y", "--path", str(tmp_path)])
        skills_dir = tmp_path / ".claude" / "skills"
        codex_skills_dir = tmp_path / ".agents" / "skills"
        assert (skills_dir / "setup-env" / "SKILL.md").exists()
        assert (skills_dir / "setup-runops" / "SKILL.md").exists()
        assert (skills_dir / "setup-plugins" / "SKILL.md").exists()
        assert (skills_dir / "survey-design" / "SKILL.md").exists()
        assert (skills_dir / "check-status" / "SKILL.md").exists()
        assert (skills_dir / "analyze" / "SKILL.md").exists()
        assert (skills_dir / "summarize-script" / "SKILL.md").exists()
        assert (skills_dir / "runops-reference" / "SKILL.md").exists()
        assert (codex_skills_dir / "setup-env" / "SKILL.md").exists()
        assert (codex_skills_dir / "setup-runops" / "SKILL.md").exists()
        assert (codex_skills_dir / "setup-plugins" / "SKILL.md").exists()
        assert (codex_skills_dir / "summarize-script" / "SKILL.md").exists()
        assert (codex_skills_dir / "runops-reference" / "SKILL.md").exists()
        setup_content = (skills_dir / "setup-env" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        assert "uv venv" in setup_content
        setup_runops_content = (
            codex_skills_dir / "setup-runops" / "SKILL.md"
        ).read_text(encoding="utf-8")
        assert "$setup-env" in setup_runops_content
        assert "$setup-plugins" in setup_runops_content
        assert "$setup-campaign" in setup_runops_content
        assert "project は生成済み" in setup_runops_content
        assert "状態確認だけで応答を終えない" in setup_runops_content
        assert "project の状態はこちらで確認します" in setup_runops_content
        assert "doctor で未解決の項目はありますか" not in setup_runops_content
        assert 'git commit -m "chore: scaffold runops project"' in setup_runops_content
        assert "次に頼みやすい形で 2-4 個" in setup_runops_content
        assert "{{ skill_prefix }}" not in setup_runops_content
        setup_plugins_content = (
            codex_skills_dir / "setup-plugins" / "SKILL.md"
        ).read_text(encoding="utf-8")
        assert "runo plugins --check" in setup_plugins_content
        assert "runo plugins --json" in setup_plugins_content
        assert "Codex hooks は experimental" in setup_plugins_content
        assert "plugin-provided hook" in setup_plugins_content
        assert "runops project 側で hook を自作しない" in setup_plugins_content
        assert "$setup-runops" in setup_plugins_content
        assert "{{ skill_prefix }}" not in setup_plugins_content
        analyze_content = (skills_dir / "analyze" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        assert "--list-recipes" in analyze_content
        assert "analysis/scratch/" in analyze_content
        assert "analysis/cross_run/" in analyze_content
        summarize_content = (skills_dir / "summarize-script" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        assert "cases/<simulator>/<case>/summarize.py" in summarize_content
        assert "figures[].path" in summarize_content

    def test_init_skills_with_packages(self, tmp_path: Path) -> None:
        """Setup-env skill includes pip packages when simulators specified."""
        runner.invoke(app, ["init", "emses", "-y", "--path", str(tmp_path)])
        content = (
            tmp_path / ".claude" / "skills" / "setup-env" / "SKILL.md"
        ).read_text(encoding="utf-8")
        assert "emout" in content
        assert "h5py" in content

    def test_init_claude_settings(self, tmp_path: Path) -> None:
        """Team-shared .claude/settings.json encodes the harness policy."""
        runner.invoke(app, ["init", "-y", "--path", str(tmp_path)])
        settings_path = tmp_path / ".claude" / "settings.json"
        assert settings_path.exists()

        data = json.loads(settings_path.read_text(encoding="utf-8"))
        assert "permissions" in data
        assert "allow" in data["permissions"]
        assert "ask" in data["permissions"]
        assert "deny" in data["permissions"]
        assert any("runo" in r for r in data["permissions"]["allow"])
        assert any("runops" in r for r in data["permissions"]["allow"])
        assert "Edit(/campaign.toml)" in data["permissions"]["allow"]
        assert "Edit(/tools/runops/**)" not in data["permissions"]["allow"]
        assert "Bash(runo runs submit*)" in data["permissions"]["allow"]
        assert "Bash(runops runs submit*)" in data["permissions"]["allow"]
        assert "Bash(runo runs submit*)" not in data["permissions"]["ask"]
        assert "Bash(runops runs submit*)" not in data["permissions"]["ask"]
        assert "Write(/runops.toml)" in data["permissions"]["ask"]
        assert "Write(/SITE.md)" in data["permissions"]["deny"]
        assert "Edit(/runs/**/manifest.toml)" in data["permissions"]["deny"]
        assert "Read(/.env)" in data["permissions"]["deny"]
        assert data["permissions"]["disableBypassPermissionsMode"] == "disable"
        # PreToolUse hooks are intentionally NOT scaffolded; their intent
        # is captured in .claude/rules/runops-workflow.md instead.
        assert "hooks" not in data

    def test_init_codex_config_and_rules(self, tmp_path: Path) -> None:
        """Codex project config and execpolicy rules are scaffolded."""
        runner.invoke(app, ["init", "-y", "--path", str(tmp_path)])
        config = (tmp_path / ".codex" / "config.toml").read_text(encoding="utf-8")
        assert 'sandbox_mode = "workspace-write"' in config
        assert "project_doc_max_bytes = 32768" in config
        assert "approval_policy =" not in config
        assert "network_access =" not in config
        assert "[sandbox_workspace_write]" not in config

        rules = (tmp_path / ".codex" / "rules" / "runops.rules").read_text(
            encoding="utf-8"
        )
        assert 'pattern = ["runo", "runs", "submit", "--dry-run"]' in rules
        assert 'pattern = ["runops", "runs", "submit", "--dry-run"]' in rules
        assert 'pattern = ["runo", "runs", "submit"]' in rules
        assert 'pattern = ["runops", "runs", "submit"]' in rules
        assert 'decision = "allow"' in rules
        assert 'decision = "prompt"' in rules
        assert 'pattern = ["rm", "-rf"]' in rules
        assert 'decision = "forbidden"' in rules

    def test_init_does_not_create_claude_hooks_dir(self, tmp_path: Path) -> None:
        """init must not scaffold .claude/hooks/ shell scripts."""
        runner.invoke(app, ["init", "-y", "--path", str(tmp_path)])
        hooks_dir = tmp_path / ".claude" / "hooks"
        # Either the directory doesn't exist, or it exists but is empty.
        if hooks_dir.exists():
            assert not any(hooks_dir.iterdir())

    def test_init_claude_rules(self, tmp_path: Path) -> None:
        """Project rules are created in .claude/rules/."""
        runner.invoke(app, ["init", "-y", "--path", str(tmp_path)])
        rules_dir = tmp_path / ".claude" / "rules"
        assert (rules_dir / "runops-workflow.md").exists()
        assert (rules_dir / "plan-before-act.md").exists()
        workflow = (rules_dir / "runops-workflow.md").read_text(encoding="utf-8")
        assert "manifest.toml" in workflow
        assert "SITE.md" in workflow
        assert "analysis/scratch/" in workflow
        assert "promote-fact" in workflow
        # Behavioural rules that used to live in PreToolUse hooks must now be
        # documented in this rule file.
        assert "runo runs submit" in workflow
        assert "通常の project には `tools/runops/` がない" in workflow

    def test_init_subdirectory_claude_md(self, tmp_path: Path) -> None:
        """Context-specific CLAUDE.md files are created in cases/ and runs/."""
        runner.invoke(app, ["init", "-y", "--path", str(tmp_path)])
        assert (tmp_path / "cases" / "CLAUDE.md").exists()
        assert (tmp_path / "runs" / "CLAUDE.md").exists()
        assert (tmp_path / "cases" / "AGENTS.md").exists()
        assert (tmp_path / "runs" / "AGENTS.md").exists()
        cases_content = (tmp_path / "cases" / "CLAUDE.md").read_text(encoding="utf-8")
        assert "case.toml" in cases_content
        runs_content = (tmp_path / "runs" / "CLAUDE.md").read_text(encoding="utf-8")
        assert "manifest.toml" in runs_content
        assert "analysis/scratch/" in runs_content
        assert (tmp_path / "cases" / "AGENTS.md").read_text(
            encoding="utf-8"
        ) == cases_content
        assert (tmp_path / "runs" / "AGENTS.md").read_text(
            encoding="utf-8"
        ) == runs_content

    def test_init_gitignore_personal_overrides(self, tmp_path: Path) -> None:
        """.gitignore excludes personal agent override files."""
        runner.invoke(app, ["init", "-y", "--path", str(tmp_path)])
        content = (tmp_path / ".gitignore").read_text(encoding="utf-8")
        assert "CLAUDE.local.md" in content
        assert "AGENTS.override.md" in content
        assert "settings.local.json" in content

    def test_init_with_simulators(self, tmp_path: Path) -> None:
        """Init with simulator names generates default simulators.toml."""
        result = runner.invoke(
            app, ["init", "emses", "beach", "-y", "--path", str(tmp_path)]
        )
        assert result.exit_code == 0
        content = (tmp_path / "simulators.toml").read_text(encoding="utf-8")
        assert "[simulators.emses]" in content
        assert 'adapter = "emses"' in content
        assert 'executable = "mpiemses3D"' in content
        assert "[simulators.beach]" in content
        assert 'adapter = "beach"' in content

    def test_init_with_unknown_simulator(self, tmp_path: Path) -> None:
        """Init with unknown simulator name fails with helpful error."""
        result = runner.invoke(
            app, ["init", "nonexistent", "-y", "--path", str(tmp_path)]
        )
        assert result.exit_code != 0
        assert "Unknown simulator" in result.output

    def test_init_with_single_simulator(self, tmp_path: Path) -> None:
        """Init with a single simulator name works."""
        result = runner.invoke(app, ["init", "emses", "-y", "--path", str(tmp_path)])
        assert result.exit_code == 0
        content = (tmp_path / "simulators.toml").read_text(encoding="utf-8")
        assert "[simulators.emses]" in content
        assert "beach" not in content

    def test_init_schema_comments(self, tmp_path: Path) -> None:
        """Generated TOMLs include #:schema comments."""
        runner.invoke(app, ["init", "-y", "--path", str(tmp_path)])
        for filename in ("runops.toml", "simulators.toml", "launchers.toml"):
            content = (tmp_path / filename).read_text(encoding="utf-8")
            assert "#:schema" in content
        runops_content = (tmp_path / "runops.toml").read_text(encoding="utf-8")
        assert "/schemas/runops.json" in runops_content
        assert "simproject.json" not in runops_content

    def test_init_references_generated_runops_knowledge(self, tmp_path: Path) -> None:
        """CLAUDE.md references generated runops knowledge for docs."""
        runner.invoke(app, ["init", "-y", "--path", str(tmp_path)])
        content = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
        assert ".runops/knowledge/enabled/imports.md" in content
        assert (
            tmp_path / ".runops" / "knowledge" / "runops" / "agent-user-guide.md"
        ).is_file()
        assert not (tmp_path / "tools" / "runops").exists()
        # docs/ directory should NOT be generated
        assert not (tmp_path / "docs").exists()

    def test_init_creates_site_md_for_selected_site_profile(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Interactive init copies SITE.md when a bundled site profile is chosen."""
        from runops.cli.init import _BundledSiteProfile

        repo_root = Path(__file__).resolve().parents[2]
        site_dir = repo_root / "src" / "runops" / "sites"
        profile = _BundledSiteProfile(
            name="camphor",
            launcher={"type": "srun", "use_slurm_ntasks": True},
            source_path=site_dir / "camphor.toml",
            docs_path=site_dir / "camphor.md",
            codex_plugins=[
                CodexPluginRecommendation(
                    name="kudpc-hpc-codex-plugin",
                    display_name="KUDPC HPC",
                    reason="KUDPC site workflow guidance.",
                    install_hint="codex plugin add kudpc-hpc-codex-plugin@test",
                    activation_hint="Start a new Codex thread.",
                    visibility="private-or-gated",
                )
            ],
        )

        monkeypatch.setattr("runops.cli.init._prompt_simulators", lambda: ([], {}))
        monkeypatch.setattr(
            "runops.cli.init._prompt_launchers",
            lambda: ({"srun": {"type": "srun", "use_slurm_ntasks": True}}, profile),
        )
        monkeypatch.setattr(
            "runops.cli.init._prompt_knowledge_sources",
            lambda _project_dir: [],
        )

        result = runner.invoke(
            app,
            ["init", "--path", str(tmp_path), "--name", "site-project"],
        )
        assert result.exit_code == 0
        site_md = tmp_path / "SITE.md"
        assert site_md.exists()
        assert "Camphor3" in site_md.read_text(encoding="utf-8")
        site_toml = (tmp_path / "site.toml").read_text(encoding="utf-8")
        assert "#:schema" in site_toml
        assert "/schemas/site.json" in site_toml
        assert "[site.codex_plugins.kudpc-hpc-codex-plugin]" in site_toml
        assert "KUDPC HPC" in result.output
        assert "KUDPC HPC" in (tmp_path / "AGENTS.md").read_text(encoding="utf-8")

    def test_init_renders_imports_after_bootstrap(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Init renders package-provided agent docs and wires imports.md."""

        def _fake_bootstrap(
            project_dir: Path,
            _sim_names: list[str],
            _runops_package: str,
            created: list[str],
            _skipped: list[str],
            **_kwargs: object,
        ) -> None:
            (project_dir / ".venv").mkdir(parents=True, exist_ok=True)
            created.append(".venv")

        monkeypatch.setattr("runops.cli.init._bootstrap_environment", _fake_bootstrap)

        result = runner.invoke(app, ["init", "-y", "--path", str(tmp_path)])

        assert result.exit_code == 0
        imports_path = tmp_path / ".runops" / "knowledge" / "enabled" / "imports.md"
        assert imports_path.is_file()
        imports = imports_path.read_text(encoding="utf-8")
        assert "@.runops/knowledge/runops/agent-user-guide.md" in imports
        claude = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
        assert "@.runops/knowledge/enabled/imports.md" in claude

    def test_init_default_is_interactive(self, tmp_path: Path) -> None:
        """Init without -y is interactive (prompts for project name)."""
        user_input = "\n" * 20
        result = runner.invoke(app, ["init", "--path", str(tmp_path)], input=user_input)
        assert result.exit_code == 0
        assert "Project name" in result.output

    def test_init_github_auth_failure_happens_before_writes(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """GitHub auth preflight fails before scaffold files are written."""

        def _fail_auth(
            _sim_names: list[str],
            *,
            interactive: bool,
            login: bool,
            skip: bool,
            include_refs: bool,
        ) -> None:
            assert interactive is False
            assert login is False
            assert skip is False
            assert include_refs is False
            raise typer.Exit(code=1)

        monkeypatch.setattr(
            "runops.cli.init.command.ensure_github_auth_for_simulators",
            _fail_auth,
        )

        result = runner.invoke(app, ["init", "emses", "-y", "--path", str(tmp_path)])

        assert result.exit_code == 1
        assert not (tmp_path / "runops.toml").exists()
        assert not (tmp_path / "simulators.toml").exists()

    def test_init_can_skip_github_auth_preflight(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """--skip-github-auth-check is forwarded to the auth preflight."""
        calls: list[tuple[bool, bool]] = []

        def _record_auth(
            _sim_names: list[str],
            *,
            interactive: bool,
            login: bool,
            skip: bool,
            include_refs: bool,
        ) -> None:
            del interactive, login
            calls.append((skip, include_refs))

        monkeypatch.setattr(
            "runops.cli.init.command.ensure_github_auth_for_simulators",
            _record_auth,
        )

        result = runner.invoke(
            app,
            [
                "init",
                "emses",
                "-y",
                "--skip-github-auth-check",
                "--path",
                str(tmp_path),
            ],
        )

        assert result.exit_code == 0
        assert calls == [(True, False)]
        assert (tmp_path / "runops.toml").exists()


class TestDoctor:
    """Tests for the 'runops doctor' command."""

    def test_doctor_all_pass(self, tmp_path: Path) -> None:
        """Doctor passes on a properly initialized project with sbatch."""
        # Set up a valid project
        (tmp_path / "runops.toml").write_text('[project]\nname = "test-project"\n')
        (tmp_path / "simulators.toml").write_text("[simulators]\n")
        (tmp_path / "launchers.toml").write_text("[launchers]\n")
        (tmp_path / "runs").mkdir()

        with patch("runops.cli.init.shutil.which", return_value="/usr/bin/sbatch"):
            result = runner.invoke(app, ["doctor", str(tmp_path)])

        assert result.exit_code == 0
        assert "All checks passed" in result.output

    def test_doctor_missing_simproject(self, tmp_path: Path) -> None:
        """Doctor fails if runops.toml is missing."""
        result = runner.invoke(app, ["doctor", str(tmp_path)])
        assert result.exit_code == 1
        assert "[FAIL] runops.toml not found" in result.output

    def test_doctor_invalid_simproject(self, tmp_path: Path) -> None:
        """Doctor fails if runops.toml is invalid."""
        (tmp_path / "runops.toml").write_text("invalid content\n")
        (tmp_path / "simulators.toml").write_text("[simulators]\n")
        (tmp_path / "launchers.toml").write_text("[launchers]\n")

        with patch("runops.cli.init.shutil.which", return_value="/usr/bin/sbatch"):
            result = runner.invoke(app, ["doctor", str(tmp_path)])

        assert result.exit_code == 1
        assert "[FAIL] runops.toml" in result.output

    def test_doctor_missing_simulators(self, tmp_path: Path) -> None:
        """Doctor fails if simulators.toml is missing."""
        (tmp_path / "runops.toml").write_text('[project]\nname = "test-project"\n')
        (tmp_path / "launchers.toml").write_text("[launchers]\n")

        with patch("runops.cli.init.shutil.which", return_value="/usr/bin/sbatch"):
            result = runner.invoke(app, ["doctor", str(tmp_path)])

        assert result.exit_code == 1
        assert "[FAIL] simulators.toml not found" in result.output

    def test_doctor_missing_launchers(self, tmp_path: Path) -> None:
        """Doctor fails if launchers.toml is missing."""
        (tmp_path / "runops.toml").write_text('[project]\nname = "test-project"\n')
        (tmp_path / "simulators.toml").write_text("[simulators]\n")

        with patch("runops.cli.init.shutil.which", return_value="/usr/bin/sbatch"):
            result = runner.invoke(app, ["doctor", str(tmp_path)])

        assert result.exit_code == 1
        assert "[FAIL] launchers.toml not found" in result.output

    def test_doctor_missing_sbatch(self, tmp_path: Path) -> None:
        """Doctor fails if sbatch is not in PATH."""
        (tmp_path / "runops.toml").write_text('[project]\nname = "test-project"\n')
        (tmp_path / "simulators.toml").write_text("[simulators]\n")
        (tmp_path / "launchers.toml").write_text("[launchers]\n")

        with patch("runops.cli.init.shutil.which", return_value=None):
            result = runner.invoke(app, ["doctor", str(tmp_path)])

        assert result.exit_code == 1
        assert "[FAIL] sbatch not found in PATH" in result.output

    def test_doctor_duplicate_run_ids(self, tmp_path: Path) -> None:
        """Doctor fails if duplicate run_ids exist."""
        (tmp_path / "runops.toml").write_text('[project]\nname = "test-project"\n')
        (tmp_path / "simulators.toml").write_text("[simulators]\n")
        (tmp_path / "launchers.toml").write_text("[launchers]\n")
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()

        # Create two runs with the same run_id
        for sub in ("run_a", "run_b"):
            run_dir = runs_dir / sub
            run_dir.mkdir()
            (run_dir / "manifest.toml").write_text(
                '[run]\nid = "R20260327-0001"\nstatus = "created"\n'
            )

        with patch("runops.cli.init.shutil.which", return_value="/usr/bin/sbatch"):
            result = runner.invoke(app, ["doctor", str(tmp_path)])

        assert result.exit_code == 1
        assert "[FAIL] Duplicate run_id" in result.output

    def test_doctor_no_runs_dir(self, tmp_path: Path) -> None:
        """Doctor passes run_id check when runs/ does not exist."""
        (tmp_path / "runops.toml").write_text('[project]\nname = "test-project"\n')
        (tmp_path / "simulators.toml").write_text("[simulators]\n")
        (tmp_path / "launchers.toml").write_text("[launchers]\n")

        with patch("runops.cli.init.shutil.which", return_value="/usr/bin/sbatch"):
            result = runner.invoke(app, ["doctor", str(tmp_path)])

        assert result.exit_code == 0
        assert "[PASS] No runs/ directory" in result.output

    def test_doctor_reports_failure_count(self, tmp_path: Path) -> None:
        """Doctor output includes the number of failed checks."""
        # Empty dir: simproject, simulators, launchers all missing + no sbatch
        with patch("runops.cli.init.shutil.which", return_value=None):
            result = runner.invoke(app, ["doctor", str(tmp_path)])

        assert result.exit_code == 1
        assert "check(s) failed" in result.output

    def test_doctor_fails_on_incomplete_codex_plugin_metadata(
        self,
        tmp_path: Path,
    ) -> None:
        """Doctor treats incomplete project-side plugin metadata as a failure."""
        (tmp_path / "runops.toml").write_text('[project]\nname = "test-project"\n')
        (tmp_path / "simulators.toml").write_text("[simulators]\n")
        (tmp_path / "launchers.toml").write_text("[launchers]\n")
        (tmp_path / "site.toml").write_text(
            '[site]\nname = "test-site"\n'
            "[site.codex_plugins.incomplete]\n"
            'display_name = "Incomplete Plugin"\n',
            encoding="utf-8",
        )

        with patch("runops.cli.init.shutil.which", return_value="/usr/bin/sbatch"):
            result = runner.invoke(app, ["doctor", str(tmp_path)])

        assert result.exit_code == 1
        assert "[FAIL] Codex plugin recommendation metadata" in result.output
        assert "incomplete.reason" in result.output
        assert "incomplete.install_hint" in result.output

    def test_doctor_warns_on_codex_plugin_metadata_warnings(
        self,
        tmp_path: Path,
    ) -> None:
        """Doctor surfaces warning-only plugin metadata without failing."""
        (tmp_path / "runops.toml").write_text('[project]\nname = "test-project"\n')
        (tmp_path / "simulators.toml").write_text("[simulators]\n")
        (tmp_path / "launchers.toml").write_text("[launchers]\n")
        (tmp_path / "site.toml").write_text(
            '[site]\nname = "test-site"\n'
            "[site.codex_plugins.site-context]\n"
            'display_name = "Site Context"\n'
            'reason = "Site-local workflow guidance."\n'
            'install_hint = "codex plugin add site-context@test"\n'
            'visibility = "private"\n',
            encoding="utf-8",
        )

        with patch("runops.cli.init.shutil.which", return_value="/usr/bin/sbatch"):
            result = runner.invoke(app, ["doctor", str(tmp_path)])

        assert result.exit_code == 0
        assert "[WARN] Codex plugin recommendation metadata" in result.output
        assert "site-context.visibility" in result.output
