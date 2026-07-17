"""Tests for runops update-harness CLI command."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from runops.cli.main import app
from runops.harness.builder import (
    GITIGNORE_PATH,
    HARNESS_LOCK_PATH,
    applied_harness_runops_version,
    build_managed_gitignore_block,
    hash_text,
    load_harness_lock,
    load_harness_upgrade_chain,
    save_harness_lock,
)

runner = CliRunner()


@pytest.fixture(autouse=True)
def _mock_bootstrap(
    monkeypatch: pytest.MonkeyPatch,
    mock_init_external_processes: None,
) -> None:
    """Skip the bootstrap step (uv install) in all tests."""
    del mock_init_external_processes
    monkeypatch.setattr(
        "runops.cli.init._bootstrap_environment",
        lambda *_args, **_kwargs: None,
    )


def _init_project(tmp_path: Path) -> None:
    """Create a minimal project via runops init."""
    result = runner.invoke(app, ["init", "-y", "--path", str(tmp_path)])
    assert result.exit_code == 0


class TestUpdateHarnessBasic:
    """Basic update-harness scenarios."""

    def test_all_files_up_to_date(self, tmp_path: Path) -> None:
        """Freshly-inited project reports all files up to date."""
        _init_project(tmp_path)
        result = runner.invoke(app, ["update-harness", str(tmp_path), "--skip-pull"])
        assert result.exit_code == 0
        assert "up to date" in result.output

    def test_update_harness_includes_project_config_plugin_recommendations(
        self,
        tmp_path: Path,
    ) -> None:
        """Generated agent docs include project-wide Codex plugin recommendations."""
        _init_project(tmp_path)
        (tmp_path / "runops.toml").write_text(
            '[project]\nname = "plugin-project"\n'
            "\n[project.codex_plugins.analysis-context]\n"
            'display_name = "Analysis Context"\n'
            'reason = "Team analysis workflow guidance."\n'
            'install_hint = "codex plugin add analysis-context@project"\n'
            'capabilities = ["analysis-workflow", "handoff"]\n',
            encoding="utf-8",
        )

        result = runner.invoke(
            app,
            [
                "update-harness",
                str(tmp_path),
                "--skip-pull",
                "--force",
                "--only",
                "AGENTS.md",
            ],
        )

        assert result.exit_code == 0
        agents = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
        assert "Analysis Context" in agents
        assert "`analysis-context`" in agents
        assert "委譲役割: analysis-workflow, handoff" in agents
        assert "目的駆動の実行契約" in agents

    def test_creates_harness_lock(self, tmp_path: Path) -> None:
        """init creates .runops/harness.lock with template hashes."""
        _init_project(tmp_path)
        lock = load_harness_lock(tmp_path)
        assert "CLAUDE.md" in lock
        assert "AGENTS.md" in lock
        assert ".claude/settings.json" in lock
        assert ".vscode/settings.json" in lock
        assert ".claude/rules/runops-workflow.md" in lock
        assert ".claude/rules/upstream-feedback.md" not in lock
        assert ".codex/config.toml" in lock
        assert ".codex/rules/runops.rules" in lock
        assert ".agents/skills/new-case/SKILL.md" in lock
        assert ".agents/skills/setup-plugins/SKILL.md" in lock
        assert ".agents/skills/patch-runops/SKILL.md" in lock
        assert ".agents/skills/python-package-refactor/SKILL.md" not in lock
        assert not any("python-package-refactor" in path for path in lock)
        assert ".agents/skills/research-workspace/SKILL.md" in lock
        assert "cases/AGENTS.md" in lock
        assert "runs/AGENTS.md" in lock
        assert GITIGNORE_PATH in lock

    def test_retires_unedited_obsolete_managed_files(self, tmp_path: Path) -> None:
        """Removed HarnessOps-era templates disappear without touching edits."""
        _init_project(tmp_path)
        obsolete = tmp_path / ".claude/rules/upstream-feedback.md"
        obsolete.write_text("obsolete managed content\n", encoding="utf-8")
        lock = load_harness_lock(tmp_path)
        lock[".claude/rules/upstream-feedback.md"] = hash_text(
            "obsolete managed content\n"
        )
        save_harness_lock(tmp_path, lock)

        result = runner.invoke(app, ["update-harness", str(tmp_path), "--skip-pull"])

        assert result.exit_code == 0
        assert "Retired 1 obsolete managed file" in result.output
        assert not obsolete.exists()
        assert ".claude/rules/upstream-feedback.md" not in load_harness_lock(tmp_path)

    def test_retires_development_only_python_refactor_skill(
        self,
        tmp_path: Path,
    ) -> None:
        """An old generated package-dev skill is removed from research projects."""
        _init_project(tmp_path)
        skill = tmp_path / ".agents/skills/python-package-refactor/SKILL.md"
        script = (
            tmp_path
            / ".agents/skills/python-package-refactor/scripts/inspect_python_package.py"
        )
        skill.parent.mkdir(parents=True, exist_ok=True)
        script.parent.mkdir(parents=True, exist_ok=True)
        skill.write_text("old skill\n", encoding="utf-8")
        script.write_text("old script\n", encoding="utf-8")
        lock = load_harness_lock(tmp_path)
        lock[".agents/skills/python-package-refactor/SKILL.md"] = hash_text(
            "old skill\n"
        )
        lock[
            ".agents/skills/python-package-refactor/scripts/inspect_python_package.py"
        ] = hash_text("old script\n")
        save_harness_lock(tmp_path, lock)

        result = runner.invoke(app, ["update-harness", str(tmp_path), "--skip-pull"])

        assert result.exit_code == 0
        assert "Retired 2 obsolete managed file(s)" in result.output
        assert not skill.exists()
        assert not script.exists()
        assert not skill.parent.exists()
        assert not any(
            "python-package-refactor" in path for path in load_harness_lock(tmp_path)
        )

    def test_overwrites_unedited_files(self, tmp_path: Path) -> None:
        """Files matching their lock hash are silently overwritten."""
        _init_project(tmp_path)
        claude_md = tmp_path / "CLAUDE.md"
        original = claude_md.read_text(encoding="utf-8")

        # Simulate template change by tampering with lock hash
        lock = load_harness_lock(tmp_path)
        lock["CLAUDE.md"] = hash_text(original)  # match current disk
        save_harness_lock(tmp_path, lock)

        result = runner.invoke(app, ["update-harness", str(tmp_path), "--skip-pull"])
        assert result.exit_code == 0
        # File content is identical to template, so it's "up to date"
        assert "up to date" in result.output

    def test_writes_new_for_user_edited(self, tmp_path: Path) -> None:
        """User-edited files are preserved; .new variant is written."""
        _init_project(tmp_path)
        claude_md = tmp_path / "CLAUDE.md"

        # User edits the file
        claude_md.write_text("# My custom CLAUDE.md\n", encoding="utf-8")

        result = runner.invoke(app, ["update-harness", str(tmp_path), "--skip-pull"])
        assert result.exit_code == 0
        assert ".new" in result.output
        # Original is preserved
        assert claude_md.read_text(encoding="utf-8") == "# My custom CLAUDE.md\n"
        # .new file exists
        new_file = tmp_path / "CLAUDE.md.new"
        assert new_file.exists()

    def test_new_file_does_not_advance_applied_runops_version(
        self,
        tmp_path: Path,
    ) -> None:
        """Writing .new leaves harness version stale until the user merges."""
        _init_project(tmp_path)
        lock = load_harness_lock(tmp_path)
        save_harness_lock(tmp_path, lock, runops_version="0.1.0")
        claude_md = tmp_path / "CLAUDE.md"
        previous_hash = lock["CLAUDE.md"]

        claude_md.write_text("# My custom CLAUDE.md\n", encoding="utf-8")

        result = runner.invoke(
            app,
            [
                "update-harness",
                str(tmp_path),
                "--skip-pull",
                "--upgrade-step",
                "--from-version",
                "0.1.0",
            ],
        )

        assert result.exit_code == 0
        assert (tmp_path / "CLAUDE.md.new").exists()
        assert applied_harness_runops_version(tmp_path) == "0.1.0"
        assert load_harness_lock(tmp_path)["CLAUDE.md"] == previous_hash

    def test_plain_update_harness_requires_chain_for_stale_lock(
        self,
        tmp_path: Path,
    ) -> None:
        """Plain update-harness refuses to skip a stale version chain."""
        _init_project(tmp_path)
        lock = load_harness_lock(tmp_path)
        save_harness_lock(tmp_path, lock, runops_version="0.1.0")

        result = runner.invoke(app, ["update-harness", str(tmp_path), "--skip-pull"])

        assert result.exit_code == 1
        assert "planned upgrade chain" in result.output
        assert "--apply-chain" in result.output

    def test_plan_shows_versioned_upgrade_chain(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """--plan prints checkpoint steps without running them."""
        _init_project(tmp_path)
        lock = load_harness_lock(tmp_path)
        save_harness_lock(tmp_path, lock, runops_version="0.8.0")
        monkeypatch.setattr(
            "runops.application.operator.harness_upgrade._fetch_pypi_runops_versions",
            lambda: ("0.8.2", "0.9.0"),
        )

        result = runner.invoke(
            app,
            [
                "update-harness",
                str(tmp_path),
                "--plan",
                "--target",
                "0.9.0",
            ],
        )

        assert result.exit_code == 0
        assert "project harness applied: 0.8.0" in result.output
        assert "1. 0.8.0 -> 0.8.2" in result.output
        assert "2. 0.8.2 -> 0.9.0" in result.output

    def test_apply_chain_runs_uvx_exact_versions(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """--apply-chain delegates each step to uvx with exact versions."""
        _init_project(tmp_path)
        lock = load_harness_lock(tmp_path)
        save_harness_lock(tmp_path, lock, runops_version="0.8.0")
        monkeypatch.setattr(
            "runops.application.operator.harness_upgrade._fetch_pypi_runops_versions",
            lambda: ("0.8.2", "0.9.0"),
        )
        monkeypatch.setattr(
            "runops.application.operator.harness_upgrade.shutil.which",
            lambda _name: "uvx",
        )
        commands: list[list[str]] = []

        def _fake_run(
            command: tuple[str, ...],
            *,
            project_dir: Path,
        ) -> subprocess.CompletedProcess[str]:
            assert project_dir == tmp_path
            commands.append(list(command))
            return subprocess.CompletedProcess(list(command), 0)

        monkeypatch.setattr(
            "runops.application.operator.harness_upgrade._run_upgrade_step_command",
            _fake_run,
        )

        result = runner.invoke(
            app,
            [
                "update-harness",
                str(tmp_path),
                "--apply-chain",
                "--target",
                "0.9.0",
            ],
        )

        assert result.exit_code == 0
        assert commands == [
            [
                "uvx",
                "--from",
                "runops==0.8.2",
                "runo",
                "update-harness",
                str(tmp_path.resolve()),
                "--upgrade-step",
                "--from-version",
                "0.8.0",
            ],
            [
                "uvx",
                "--from",
                "runops==0.9.0",
                "runo",
                "update-harness",
                str(tmp_path.resolve()),
                "--upgrade-step",
                "--from-version",
                "0.8.2",
            ],
        ]

    def test_force_overwrites_edited(self, tmp_path: Path) -> None:
        """--force overwrites even user-edited files."""
        _init_project(tmp_path)
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("# Edited\n", encoding="utf-8")

        result = runner.invoke(
            app, ["update-harness", str(tmp_path), "--skip-pull", "--force"]
        )
        assert result.exit_code == 0
        assert "Updated" in result.output
        # File should no longer be the user edit
        assert claude_md.read_text(encoding="utf-8") != "# Edited\n"

    def test_vscode_settings_are_harness_managed(self, tmp_path: Path) -> None:
        """User edits to .vscode/settings.json are preserved via .new."""
        _init_project(tmp_path)
        settings_path = tmp_path / ".vscode" / "settings.json"
        settings_path.write_text('{"files.exclude":{}}\n', encoding="utf-8")

        result = runner.invoke(app, ["update-harness", str(tmp_path), "--skip-pull"])

        assert result.exit_code == 0
        assert ".vscode/settings.json.new" in result.output
        assert settings_path.read_text(encoding="utf-8") == '{"files.exclude":{}}\n'
        new_settings_path = tmp_path / ".vscode" / "settings.json.new"
        assert new_settings_path.exists()
        new_settings = json.loads(new_settings_path.read_text(encoding="utf-8"))
        analysis_exclude = new_settings["python.analysis.exclude"]
        assert "**/node_modules" in analysis_exclude
        assert "**/__pycache__" in analysis_exclude
        assert "**/.*" in analysis_exclude

    def test_backfills_visible_workspace_when_missing(self, tmp_path: Path) -> None:
        """update-harness recreates missing visible workspace scaffold."""
        _init_project(tmp_path)
        (tmp_path / "materials" / "README.md").unlink()
        (tmp_path / "materials" / "papers").rmdir()
        (tmp_path / "research" / "CURRENT.md").unlink()
        (tmp_path / "research" / "journal" / "active.md").unlink()

        result = runner.invoke(app, ["update-harness", str(tmp_path), "--skip-pull"])

        assert result.exit_code == 0
        assert "Backfilled" in result.output
        assert (tmp_path / "materials" / "README.md").is_file()
        assert (tmp_path / "materials" / "papers").is_dir()
        assert (tmp_path / "research" / "CURRENT.md").is_file()
        assert (tmp_path / "research" / "journal" / "active.md").is_file()
        lock = load_harness_lock(tmp_path)
        assert "materials/README.md" not in lock
        assert "research/CURRENT.md" not in lock

    def test_only_can_limit_workspace_backfill(self, tmp_path: Path) -> None:
        """--only respects visible workspace backfill targets."""
        _init_project(tmp_path)
        (tmp_path / "materials" / "README.md").unlink()
        (tmp_path / "research" / "CURRENT.md").unlink()

        result = runner.invoke(
            app,
            [
                "update-harness",
                str(tmp_path),
                "--skip-pull",
                "--only",
                "materials",
            ],
        )

        assert result.exit_code == 0
        assert (tmp_path / "materials" / "README.md").is_file()
        assert not (tmp_path / "research" / "CURRENT.md").exists()

    def test_dry_run_no_writes(self, tmp_path: Path) -> None:
        """--dry-run reports but does not actually write files."""
        _init_project(tmp_path)
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("# Edited\n", encoding="utf-8")

        old_lock = load_harness_lock(tmp_path)

        result = runner.invoke(
            app, ["update-harness", str(tmp_path), "--skip-pull", "--dry-run"]
        )
        assert result.exit_code == 0
        assert "[dry-run]" in result.output
        # File untouched
        assert claude_md.read_text(encoding="utf-8") == "# Edited\n"
        # No .new file
        assert not (tmp_path / "CLAUDE.md.new").exists()
        # Lock unchanged
        assert load_harness_lock(tmp_path) == old_lock

    def test_adopt_locks_current_state(self, tmp_path: Path) -> None:
        """--adopt records current file hashes without overwriting."""
        _init_project(tmp_path)
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("# Custom\n", encoding="utf-8")

        result = runner.invoke(
            app, ["update-harness", str(tmp_path), "--skip-pull", "--adopt"]
        )
        assert result.exit_code == 0
        assert "Adopted" in result.output

        # Lock now matches the on-disk custom content
        lock = load_harness_lock(tmp_path)
        assert lock["CLAUDE.md"] == hash_text("# Custom\n")

    def test_gitignore_updates_managed_block_in_place(self, tmp_path: Path) -> None:
        """update-harness refreshes only the managed gitignore block."""
        _init_project(tmp_path)
        gitignore_path = tmp_path / GITIGNORE_PATH
        old_block = build_managed_gitignore_block().replace("runs/**/status/\n", "")
        gitignore_path.write_text(
            f"# custom-before/\n\n{old_block}\ncustom-after/\n",
            encoding="utf-8",
        )

        lock = load_harness_lock(tmp_path)
        lock[GITIGNORE_PATH] = hash_text(old_block)
        save_harness_lock(tmp_path, lock)

        result = runner.invoke(app, ["update-harness", str(tmp_path), "--skip-pull"])

        assert result.exit_code == 0
        assert ".gitignore" in result.output
        updated = gitignore_path.read_text(encoding="utf-8")
        assert "# custom-before/" in updated
        assert "custom-after/" in updated
        assert build_managed_gitignore_block() in updated
        assert old_block not in updated
        assert not (tmp_path / ".gitignore.new").exists()

    def test_gitignore_without_managed_block_writes_new(self, tmp_path: Path) -> None:
        """Existing gitignore without the managed block is preserved via .new."""
        _init_project(tmp_path)
        gitignore_path = tmp_path / GITIGNORE_PATH
        gitignore_path.write_text("# custom-only\ncache/\n", encoding="utf-8")

        result = runner.invoke(app, ["update-harness", str(tmp_path), "--skip-pull"])

        assert result.exit_code == 0
        assert ".gitignore.new" in result.output
        assert gitignore_path.read_text(encoding="utf-8") == "# custom-only\ncache/\n"
        new_content = (tmp_path / ".gitignore.new").read_text(encoding="utf-8")
        assert new_content.startswith("# custom-only\ncache/\n")
        assert build_managed_gitignore_block() in new_content

    def test_only_filters_paths(self, tmp_path: Path) -> None:
        """--only limits which files are processed."""
        _init_project(tmp_path)
        # Edit both CLAUDE.md and AGENTS.md
        (tmp_path / "CLAUDE.md").write_text("# A\n", encoding="utf-8")
        (tmp_path / "AGENTS.md").write_text("# B\n", encoding="utf-8")

        result = runner.invoke(
            app,
            [
                "update-harness",
                str(tmp_path),
                "--skip-pull",
                "--force",
                "--only",
                "CLAUDE.md",
            ],
        )
        assert result.exit_code == 0
        # CLAUDE.md was updated
        assert (tmp_path / "CLAUDE.md").read_text(encoding="utf-8") != "# A\n"
        # AGENTS.md was NOT touched
        assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") == "# B\n"

    def test_force_refreshes_setup_runops_guidance(
        self,
        tmp_path: Path,
    ) -> None:
        """update-harness refreshes setup-runops onboarding guidance."""
        _init_project(tmp_path)
        skill_path = tmp_path / ".agents" / "skills" / "setup-runops" / "SKILL.md"
        skill_path.write_text("stale setup-runops\n", encoding="utf-8")

        result = runner.invoke(
            app,
            [
                "update-harness",
                str(tmp_path),
                "--skip-pull",
                "--force",
                "--only",
                ".agents/skills/setup-runops/SKILL.md",
            ],
        )

        assert result.exit_code == 0
        content = skill_path.read_text(encoding="utf-8")
        assert "## 実行契約" in content
        assert "Default milestone" in content
        assert "context / doctor は各1回" in content
        assert "local state から決まらない設計情報だけ" in content
        assert 'git commit -m "chore: scaffold runops project"' in content

    def test_force_refreshes_bounded_campaign_skill(
        self,
        tmp_path: Path,
    ) -> None:
        """update-harness installs the bounded campaign execution contract."""
        _init_project(tmp_path)
        skill_path = tmp_path / ".agents" / "skills" / "setup-campaign" / "SKILL.md"
        skill_path.write_text("stale campaign skill\n", encoding="utf-8")

        result = runner.invoke(
            app,
            [
                "update-harness",
                str(tmp_path),
                "--skip-pull",
                "--force",
                "--only",
                ".agents/skills/setup-campaign/SKILL.md",
            ],
        )

        assert result.exit_code == 0
        content = skill_path.read_text(encoding="utf-8")
        assert "## 実行契約" in content
        assert all(
            field in content for field in ("Goal", "Done", "Budget", "Invariant")
        )
        assert "runo plugins --check" not in content


class TestHarnessLock:
    """Tests for .runops/harness.lock persistence."""

    def test_lock_is_valid_json(self, tmp_path: Path) -> None:
        """harness.lock is valid JSON with version and hashes."""
        _init_project(tmp_path)
        lock_path = tmp_path / HARNESS_LOCK_PATH
        assert lock_path.exists()
        data = json.loads(lock_path.read_text(encoding="utf-8"))
        assert data["version"] == 1
        assert isinstance(data["runops_version"], str)
        assert applied_harness_runops_version(tmp_path) == data["runops_version"]
        assert isinstance(data["hashes"], dict)
        assert len(data["hashes"]) > 0

    def test_lock_hashes_are_sha256(self, tmp_path: Path) -> None:
        """All hashes in the lock are 64-char hex sha256 strings."""
        _init_project(tmp_path)
        lock = load_harness_lock(tmp_path)
        for _path, h in lock.items():
            assert len(h) == 64
            int(h, 16)  # raises if not hex

    def test_upgrade_step_records_upgrade_chain_event(self, tmp_path: Path) -> None:
        """Exact-version upgrade steps append a provenance event."""
        _init_project(tmp_path)

        result = runner.invoke(
            app,
            [
                "update-harness",
                str(tmp_path),
                "--skip-pull",
                "--upgrade-step",
                "--from-version",
                "0.8.0",
            ],
        )

        assert result.exit_code == 0
        events = load_harness_upgrade_chain(tmp_path)
        assert events[-1]["from"] == "0.8.0"
        assert events[-1]["to"]
        assert events[-1]["command"] == "update-harness --upgrade-step"

    def test_no_lock_treated_as_all_edited(self, tmp_path: Path) -> None:
        """When harness.lock is missing, all files are treated as user-edited."""
        _init_project(tmp_path)
        # Remove lock
        (tmp_path / HARNESS_LOCK_PATH).unlink()

        # Edit one file to differ from template
        (tmp_path / "CLAUDE.md").write_text("# Custom\n", encoding="utf-8")

        result = runner.invoke(app, ["update-harness", str(tmp_path), "--skip-pull"])
        assert result.exit_code == 0
        # CLAUDE.md should get a .new since it's edited and lock is missing
        assert (tmp_path / "CLAUDE.md.new").exists()
