"""Tests for runops init and runops doctor CLI commands."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from runops.cli.main import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _mock_bootstrap(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip the bootstrap step (uv/git clone) in all init tests."""
    monkeypatch.setattr(
        "runops.cli.init._bootstrap_environment",
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
        assert (tmp_path / "notes" / "README.md").is_file()
        # Source material scaffolding
        assert (tmp_path / "materials").is_dir()
        assert (tmp_path / "materials" / "papers").is_dir()
        assert (tmp_path / "materials" / "manuals").is_dir()
        assert (tmp_path / "materials" / "figures").is_dir()
        assert (tmp_path / "materials" / "snippets").is_dir()
        assert (tmp_path / "materials" / "README.md").is_file()
        assert (tmp_path / "materials" / "index.toml").is_file()

    def test_init_notes_readme_content(self, tmp_path: Path) -> None:
        """notes/README.md describes the lab-notebook convention."""
        runner.invoke(app, ["init", "-y", "--path", str(tmp_path)])
        readme = (tmp_path / "notes" / "README.md").read_text(encoding="utf-8")
        assert "lab notebook" in readme
        assert "runo notes append" in readme
        assert "notes/YYYY-MM-DD.md" in readme

    def test_init_materials_readme_content(self, tmp_path: Path) -> None:
        """materials/README.md describes visible source material storage."""
        runner.invoke(app, ["init", "-y", "--path", str(tmp_path)])
        readme = (tmp_path / "materials" / "README.md").read_text(encoding="utf-8")
        index = (tmp_path / "materials" / "index.toml").read_text(encoding="utf-8")
        assert "source material" in readme
        assert "human/agent shared workspace" in readme
        assert ".runops/knowledge/" in readme
        assert "materials/**/*.pdf" in readme
        assert "materials = []" in index

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
        # The whole work/ tree is regenerable from input/, so it is excluded
        # wholesale rather than enumerating per-simulator output filenames.
        assert "runs/**/work/" in content
        assert "runs/**/status/" in content
        assert "runs/**/input/plasma.inp" in content
        assert "runs/**/analysis/scratch/" in content
        assert "AGENTS.override.md" in content

    def test_init_vscode_settings_hide_generated_artifacts(
        self,
        tmp_path: Path,
    ) -> None:
        """VS Code hides generated/internal files while keeping sources visible."""
        runner.invoke(app, ["init", "-y", "--path", str(tmp_path)])
        settings = json.loads(
            (tmp_path / ".vscode" / "settings.json").read_text(encoding="utf-8")
        )

        files_exclude = settings["files.exclude"]
        assert files_exclude[".venv"] is True
        assert files_exclude["tools"] is True
        assert files_exclude["refs"] is True
        assert files_exclude[".runops/knowledge"] is True
        assert files_exclude[".runops/environment.toml"] is True
        assert files_exclude["runs/**/work"] is True
        assert files_exclude["runs/**/status"] is True
        assert files_exclude["runs/**/submit"] is True
        assert files_exclude["runs/**/manifest.toml"] is True
        assert "cases" not in files_exclude
        assert "notes" not in files_exclude
        assert "materials" not in files_exclude
        assert "runs/**/survey.toml" not in files_exclude

        search_exclude = settings["search.exclude"]
        assert search_exclude["materials/**/*.pdf"] is True
        assert "materials" not in search_exclude

        watcher_exclude = settings["files.watcherExclude"]
        assert watcher_exclude[".venv/**"] is True
        assert watcher_exclude["runs/**/work/**"] is True
        assert watcher_exclude["runs/**/status/**"] is True

        analysis_exclude = settings["python.analysis.exclude"]
        assert ".venv" in analysis_exclude
        assert "refs" in analysis_exclude
        assert "runs/**/work" in analysis_exclude

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
        """CLAUDE.md includes refs but not inline simulator details."""
        runner.invoke(app, ["init", "emses", "beach", "-y", "--path", str(tmp_path)])
        content = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
        # Simulator details are via imports.md, not inline
        assert "シミュレータ固有知識" not in content
        assert "Agent ガイド" not in content
        assert "runo context" in content
        assert "campaign.toml" in content
        # Ref repos should be listed
        assert "リファレンスリポジトリ" in content
        # Cookbook rule should be generated separately
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
        assert "Simulator Cookbook ルール" in content
        assert "runops へのフィードバック" in content
        assert "globs: refs/**/cookbook/**" not in content

    def test_init_skills(self, tmp_path: Path) -> None:
        """Individual SKILL.md files are created for Claude and Codex."""
        runner.invoke(app, ["init", "-y", "--path", str(tmp_path)])
        skills_dir = tmp_path / ".claude" / "skills"
        codex_skills_dir = tmp_path / ".agents" / "skills"
        assert (skills_dir / "setup-env" / "SKILL.md").exists()
        assert (skills_dir / "survey-design" / "SKILL.md").exists()
        assert (skills_dir / "check-status" / "SKILL.md").exists()
        assert (skills_dir / "analyze" / "SKILL.md").exists()
        assert (skills_dir / "runops-reference" / "SKILL.md").exists()
        assert (codex_skills_dir / "setup-env" / "SKILL.md").exists()
        assert (codex_skills_dir / "runops-reference" / "SKILL.md").exists()
        setup_content = (skills_dir / "setup-env" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        assert "uv venv" in setup_content
        analyze_content = (skills_dir / "analyze" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        assert "--list-recipes" in analyze_content
        assert "analysis/scratch/" in analyze_content

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
        assert "Edit(/tools/runops/**)" in data["permissions"]["allow"]
        assert "Bash(runo runs submit*)" in data["permissions"]["ask"]
        assert "Bash(runops runs submit*)" in data["permissions"]["ask"]
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
        assert 'approval_policy = "on-request"' in config
        assert 'sandbox_mode = "workspace-write"' in config
        assert "project_doc_max_bytes = 65536" in config
        assert "[sandbox_workspace_write]" in config
        assert "network_access = false" in config

        rules = (tmp_path / ".codex" / "rules" / "runops.rules").read_text(
            encoding="utf-8"
        )
        assert 'pattern = ["runo", "runs", "submit", "--dry-run"]' in rules
        assert 'pattern = ["runops", "runs", "submit", "--dry-run"]' in rules
        assert 'decision = "allow"' in rules
        assert 'pattern = ["runo", "runs", "submit", "--all"]' in rules
        assert 'pattern = ["runops", "runs", "submit", "--all"]' in rules
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
        assert "tools/runops" in workflow

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

    def test_init_references_tools_dir(self, tmp_path: Path) -> None:
        """CLAUDE.md references tools/runops/ for docs."""
        runner.invoke(app, ["init", "-y", "--path", str(tmp_path)])
        content = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
        assert "tools/runops/" in content
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

    def test_init_renders_imports_after_bootstrap(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Init discovers tool docs only after bootstrap and wires imports.md."""

        def _fake_bootstrap(
            project_dir: Path,
            _sim_names: list[str],
            _runops_repo: str,
            created: list[str],
            _skipped: list[str],
        ) -> None:
            (project_dir / "tools" / "runops").mkdir(parents=True, exist_ok=True)
            (project_dir / "tools" / "runops" / "entrypoints.toml").write_text(
                'imports = ["docs/agent-user-guide.md"]\n',
                encoding="utf-8",
            )
            docs_dir = project_dir / "tools" / "runops" / "docs"
            docs_dir.mkdir(parents=True, exist_ok=True)
            (docs_dir / "agent-user-guide.md").write_text("# Agent guide\n")
            created.append("tools/runops")

        monkeypatch.setattr("runops.cli.init._bootstrap_environment", _fake_bootstrap)

        result = runner.invoke(app, ["init", "-y", "--path", str(tmp_path)])

        assert result.exit_code == 0
        imports_path = tmp_path / ".runops" / "knowledge" / "enabled" / "imports.md"
        assert imports_path.is_file()
        imports = imports_path.read_text(encoding="utf-8")
        assert "@tools/runops/docs/agent-user-guide.md" in imports
        claude = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
        assert "@.runops/knowledge/enabled/imports.md" in claude

    def test_init_default_is_interactive(self, tmp_path: Path) -> None:
        """Init without -y is interactive (prompts for project name)."""
        user_input = "\n" * 20
        result = runner.invoke(app, ["init", "--path", str(tmp_path)], input=user_input)
        assert result.exit_code == 0
        assert "Project name" in result.output


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
