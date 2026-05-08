"""Tests for runops update-harness CLI command."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

import runops.cli.update_harness as update_harness_module
import runops.cli.update_harness_tools as update_harness_tools
from runops.cli.main import app
from runops.harness.builder import (
    GITIGNORE_PATH,
    HARNESS_LOCK_PATH,
    build_managed_gitignore_block,
    hash_text,
    load_harness_lock,
    save_harness_lock,
)

runner = CliRunner()


@pytest.fixture(autouse=True)
def _mock_bootstrap(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip the bootstrap step (uv/git clone) in all tests."""
    monkeypatch.setattr(
        "runops.cli.init._bootstrap_environment",
        lambda *_args, **_kwargs: None,
    )


def _init_project(tmp_path: Path) -> None:
    """Create a minimal project via runops init."""
    result = runner.invoke(app, ["init", "-y", "--path", str(tmp_path)])
    assert result.exit_code == 0


def _make_tools_runops_repo(project_dir: Path) -> Path:
    """Create the minimum ``tools/runops/.git`` shape for update tests."""
    runops_dir = project_dir / "tools" / "runops"
    (runops_dir / ".git").mkdir(parents=True)
    return runops_dir


class TestUpdateHarnessBasic:
    """Basic update-harness scenarios."""

    def test_all_files_up_to_date(self, tmp_path: Path) -> None:
        """Freshly-inited project reports all files up to date."""
        _init_project(tmp_path)
        result = runner.invoke(app, ["update-harness", str(tmp_path), "--skip-pull"])
        assert result.exit_code == 0
        assert "up to date" in result.output

    def test_creates_harness_lock(self, tmp_path: Path) -> None:
        """init creates .runops/harness.lock with template hashes."""
        _init_project(tmp_path)
        lock = load_harness_lock(tmp_path)
        assert "CLAUDE.md" in lock
        assert "AGENTS.md" in lock
        assert ".claude/settings.json" in lock
        assert ".vscode/settings.json" in lock
        assert ".claude/rules/runops-workflow.md" in lock
        assert ".claude/rules/upstream-feedback.md" in lock
        assert ".codex/config.toml" in lock
        assert ".codex/rules/runops.rules" in lock
        assert ".agents/skills/new-case/SKILL.md" in lock
        assert ".agents/skills/patch-runops/SKILL.md" in lock
        assert ".agents/skills/python-package-refactor/SKILL.md" in lock
        assert (
            ".agents/skills/python-package-refactor/scripts/inspect_python_package.py"
            in lock
        )
        assert ".agents/skills/research-agenda/SKILL.md" in lock
        assert "cases/AGENTS.md" in lock
        assert "runs/AGENTS.md" in lock
        assert GITIGNORE_PATH in lock

    def test_pull_tools_repo_blocks_dirty_checkout(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """tools/runops updates never pull over uncommitted local patches."""
        _make_tools_runops_repo(tmp_path)
        calls: list[list[str]] = []

        def fake_run(
            cmd: list[str],
            **_kwargs: object,
        ) -> subprocess.CompletedProcess[str]:
            calls.append(cmd)
            if cmd == ["git", "status", "--porcelain"]:
                return subprocess.CompletedProcess(
                    cmd,
                    0,
                    stdout=" M src/runops/foo.py\n",
                    stderr="",
                )
            raise AssertionError(f"unexpected command: {cmd}")

        monkeypatch.setattr(update_harness_tools.subprocess, "run", fake_run)

        status = update_harness_module._pull_tools_repo(tmp_path)

        assert status is not None
        assert status.startswith("blocked:")
        assert "uncommitted" in status
        assert ["git", "pull", "--ff-only"] not in calls

    def test_pull_tools_repo_blocks_local_branch(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """update-runops does not switch away from active patch branches."""
        _make_tools_runops_repo(tmp_path)

        def fake_run(
            cmd: list[str],
            **_kwargs: object,
        ) -> subprocess.CompletedProcess[str]:
            if cmd == ["git", "status", "--porcelain"]:
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            if cmd == ["git", "branch", "--show-current"]:
                return subprocess.CompletedProcess(
                    cmd, 0, stdout="fix/demo\n", stderr=""
                )
            raise AssertionError(f"unexpected command: {cmd}")

        monkeypatch.setattr(update_harness_tools.subprocess, "run", fake_run)

        status = update_harness_module._pull_tools_repo(tmp_path)

        assert status is not None
        assert status.startswith("blocked:")
        assert "fix/demo" in status

    def test_pull_tools_repo_blocks_local_commits(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """local commits are protected until they are pushed or triaged."""
        _make_tools_runops_repo(tmp_path)

        def fake_run(
            cmd: list[str],
            **_kwargs: object,
        ) -> subprocess.CompletedProcess[str]:
            if cmd == ["git", "status", "--porcelain"]:
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            if cmd == ["git", "branch", "--show-current"]:
                return subprocess.CompletedProcess(cmd, 0, stdout="main\n", stderr="")
            if cmd == [
                "git",
                "rev-parse",
                "--abbrev-ref",
                "--symbolic-full-name",
                "@{u}",
            ]:
                return subprocess.CompletedProcess(
                    cmd,
                    0,
                    stdout="origin/main\n",
                    stderr="",
                )
            if cmd == ["git", "rev-list", "--count", "@{u}..HEAD"]:
                return subprocess.CompletedProcess(cmd, 0, stdout="2\n", stderr="")
            raise AssertionError(f"unexpected command: {cmd}")

        monkeypatch.setattr(update_harness_tools.subprocess, "run", fake_run)

        status = update_harness_module._pull_tools_repo(tmp_path)

        assert status is not None
        assert status.startswith("blocked:")
        assert "2 local commit" in status

    def test_pull_tools_repo_allows_clean_main(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """clean main checkouts still pull normally."""
        _make_tools_runops_repo(tmp_path)

        def fake_run(
            cmd: list[str],
            **_kwargs: object,
        ) -> subprocess.CompletedProcess[str]:
            if cmd == ["git", "status", "--porcelain"]:
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            if cmd == ["git", "branch", "--show-current"]:
                return subprocess.CompletedProcess(cmd, 0, stdout="main\n", stderr="")
            if cmd == [
                "git",
                "rev-parse",
                "--abbrev-ref",
                "--symbolic-full-name",
                "@{u}",
            ]:
                return subprocess.CompletedProcess(
                    cmd,
                    0,
                    stdout="origin/main\n",
                    stderr="",
                )
            if cmd == ["git", "rev-list", "--count", "@{u}..HEAD"]:
                return subprocess.CompletedProcess(cmd, 0, stdout="0\n", stderr="")
            if cmd == ["git", "pull", "--ff-only"]:
                return subprocess.CompletedProcess(
                    cmd,
                    0,
                    stdout="Already up to date.\n",
                    stderr="",
                )
            raise AssertionError(f"unexpected command: {cmd}")

        monkeypatch.setattr(update_harness_tools.subprocess, "run", fake_run)

        assert update_harness_module._pull_tools_repo(tmp_path) == "already up to date"

    def test_update_harness_stops_when_tools_repo_pull_is_blocked(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """update-harness preserves local tools/runops work by stopping."""
        _init_project(tmp_path)
        monkeypatch.setattr(
            update_harness_module,
            "_pull_tools_repo",
            lambda _project_dir: "blocked: local uncommitted changes exist",
        )

        result = runner.invoke(app, ["update-harness", str(tmp_path)])

        assert result.exit_code == 1
        assert "tools/runops: blocked:" in result.output
        assert "Local tools/runops changes were preserved" in result.output

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
        (tmp_path / "notes" / "README.md").unlink()
        (tmp_path / "notes" / "history").rmdir()
        (tmp_path / "materials" / "README.md").unlink()
        (tmp_path / "materials" / "papers").rmdir()
        (tmp_path / "research" / "agenda.md").unlink()
        (tmp_path / "research" / "reviews" / ".gitkeep").unlink()

        result = runner.invoke(app, ["update-harness", str(tmp_path), "--skip-pull"])

        assert result.exit_code == 0
        assert "Backfilled" in result.output
        assert (tmp_path / "notes" / "README.md").is_file()
        assert (tmp_path / "notes" / "history").is_dir()
        assert (tmp_path / "materials" / "README.md").is_file()
        assert (tmp_path / "materials" / "papers").is_dir()
        assert (tmp_path / "research" / "agenda.md").is_file()
        assert (tmp_path / "research" / "reviews" / ".gitkeep").is_file()
        lock = load_harness_lock(tmp_path)
        assert "notes/README.md" not in lock
        assert "materials/README.md" not in lock
        assert "research/agenda.md" not in lock

    def test_only_can_limit_workspace_backfill(self, tmp_path: Path) -> None:
        """--only respects visible workspace backfill targets."""
        _init_project(tmp_path)
        (tmp_path / "notes" / "README.md").unlink()
        (tmp_path / "materials" / "README.md").unlink()
        (tmp_path / "research" / "agenda.md").unlink()

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
        assert not (tmp_path / "notes" / "README.md").exists()
        assert (tmp_path / "materials" / "README.md").is_file()
        assert not (tmp_path / "research" / "agenda.md").exists()

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


class TestInitUpstreamFeedback:
    """Tests for --no-upstream-feedback in runops init."""

    def test_default_includes_feedback_rule(self, tmp_path: Path) -> None:
        """By default, upstream-feedback.md rule is created."""
        _init_project(tmp_path)
        rule = tmp_path / ".claude" / "rules" / "upstream-feedback.md"
        assert rule.exists()
        content = rule.read_text(encoding="utf-8")
        assert "Nkzono99/runops" in content
        assert "gh issue create" in content

    def test_no_upstream_feedback_flag(self, tmp_path: Path) -> None:
        """--no-upstream-feedback omits the rule file."""
        result = runner.invoke(
            app, ["init", "-y", "--no-upstream-feedback", "--path", str(tmp_path)]
        )
        assert result.exit_code == 0
        rule = tmp_path / ".claude" / "rules" / "upstream-feedback.md"
        assert not rule.exists()
        agents = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
        assert "runops へのフィードバック" not in agents

    def test_simproject_records_upstream_feedback(self, tmp_path: Path) -> None:
        """runops.toml includes [harness] upstream_feedback = true."""
        _init_project(tmp_path)
        content = (tmp_path / "runops.toml").read_text(encoding="utf-8")
        assert "[harness]" in content
        assert "upstream_feedback = true" in content

    def test_simproject_records_no_upstream_feedback(self, tmp_path: Path) -> None:
        """--no-upstream-feedback sets upstream_feedback = false."""
        runner.invoke(
            app, ["init", "-y", "--no-upstream-feedback", "--path", str(tmp_path)]
        )
        content = (tmp_path / "runops.toml").read_text(encoding="utf-8")
        assert "upstream_feedback = false" in content

    def test_update_harness_respects_setting(self, tmp_path: Path) -> None:
        """update-harness reads upstream_feedback from runops.toml."""
        # Init without feedback
        runner.invoke(
            app, ["init", "-y", "--no-upstream-feedback", "--path", str(tmp_path)]
        )
        rule = tmp_path / ".claude" / "rules" / "upstream-feedback.md"
        assert not rule.exists()

        # update-harness should NOT create it
        result = runner.invoke(app, ["update-harness", str(tmp_path), "--skip-pull"])
        assert result.exit_code == 0
        assert not rule.exists()


class TestHarnessLock:
    """Tests for .runops/harness.lock persistence."""

    def test_lock_is_valid_json(self, tmp_path: Path) -> None:
        """harness.lock is valid JSON with version and hashes."""
        _init_project(tmp_path)
        lock_path = tmp_path / HARNESS_LOCK_PATH
        assert lock_path.exists()
        data = json.loads(lock_path.read_text(encoding="utf-8"))
        assert data["version"] == 1
        assert isinstance(data["hashes"], dict)
        assert len(data["hashes"]) > 0

    def test_lock_hashes_are_sha256(self, tmp_path: Path) -> None:
        """All hashes in the lock are 64-char hex sha256 strings."""
        _init_project(tmp_path)
        lock = load_harness_lock(tmp_path)
        for _path, h in lock.items():
            assert len(h) == 64
            int(h, 16)  # raises if not hex

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


class TestUpdateHarnessReexec:
    """Tests for re-execing after tools/runops is updated."""

    def test_restart_with_skip_pull_reexecs_current_command(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Re-exec runs the same CLI command once with --skip-pull appended."""
        captured: dict[str, object] = {}

        def fake_exec(executable: str, argv: list[str], env: dict[str, str]) -> None:
            captured["executable"] = executable
            captured["argv"] = argv
            captured["env"] = env
            raise RuntimeError("exec called")

        monkeypatch.setattr(
            sys, "argv", ["runops", "update-harness", "/tmp/p", "--force"]
        )
        monkeypatch.setattr(sys, "executable", "/usr/bin/python3")
        monkeypatch.setattr(os, "execvpe", fake_exec)

        with pytest.raises(RuntimeError, match="exec called"):
            update_harness_module._restart_with_skip_pull()

        assert captured["executable"] == "/usr/bin/python3"
        assert captured["argv"] == [
            "/usr/bin/python3",
            "-I",
            "-m",
            "runops.cli.main",
            "update-harness",
            "/tmp/p",
            "--force",
            "--skip-pull",
        ]
        env = captured["env"]
        assert isinstance(env, dict)
        assert env[update_harness_module._REEXEC_ENV_VAR] == "1"

    def test_restarts_after_pull_update(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A successful pull triggers a restart before rendering harness files."""
        _init_project(tmp_path)
        restarted: list[bool] = []

        monkeypatch.setattr(
            "runops.cli.update_harness._pull_tools_repo",
            lambda *_args, **_kwargs: "updated",
        )

        def fake_restart() -> None:
            restarted.append(True)
            raise typer.Exit(code=0)

        monkeypatch.setattr(
            "runops.cli.update_harness._restart_with_skip_pull",
            fake_restart,
        )
        monkeypatch.delenv(update_harness_module._REEXEC_ENV_VAR, raising=False)

        result = runner.invoke(app, ["update-harness", str(tmp_path)])

        assert result.exit_code == 0
        assert restarted == [True]
        assert "tools/runops: updated" in result.output

    def test_reinstall_editable_refreshes_install(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """After a successful pull, editable install is refreshed before re-exec."""
        _init_project(tmp_path)

        tools_runops = tmp_path / "tools" / "runops"
        tools_runops.mkdir(parents=True)
        (tools_runops / "pyproject.toml").write_text("[project]\nname='runops'\n")

        venv_bin = tmp_path / ".venv" / "bin"
        venv_bin.mkdir(parents=True)
        (venv_bin / "python").write_text("")

        captured_calls: list[list[str]] = []

        def fake_run(argv, *_, **__):  # type: ignore[no-untyped-def]
            captured_calls.append(list(argv))

            class _Result:
                returncode = 0
                stdout = ""
                stderr = ""

            return _Result()

        monkeypatch.setattr(
            "runops.cli.update_harness._pull_tools_repo",
            lambda *_args, **_kwargs: "updated",
        )
        monkeypatch.setattr(
            "runops.cli.update_harness_tools.subprocess.run",
            fake_run,
        )
        monkeypatch.setattr(
            "runops.cli.update_harness._restart_with_skip_pull",
            lambda: (_ for _ in ()).throw(typer.Exit(code=0)),
        )
        monkeypatch.delenv(update_harness_module._REEXEC_ENV_VAR, raising=False)

        result = runner.invoke(app, ["update-harness", str(tmp_path)])

        assert result.exit_code == 0
        # subprocess.run was called with uv pip install -e tools/runops
        assert any(
            "pip" in call and "install" in call and "-e" in call
            for call in captured_calls
        )
        assert "editable install refreshed" in result.output

    def test_reinstall_editable_when_metadata_is_stale(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Refresh editable install even when ``git pull`` says no update."""
        _init_project(tmp_path)

        tools_runops = tmp_path / "tools" / "runops"
        tools_runops.mkdir(parents=True)
        (tools_runops / "pyproject.toml").write_text(
            "[project]\nname='runops'\nversion='0.5.1'\n",
            encoding="utf-8",
        )

        venv_bin = tmp_path / ".venv" / "bin"
        venv_bin.mkdir(parents=True)
        (venv_bin / "python").write_text("", encoding="utf-8")

        captured_calls: list[list[str]] = []

        def fake_run(argv, *_, **__):  # type: ignore[no-untyped-def]
            captured_calls.append(list(argv))

            class _Result:
                def __init__(self, stdout: str = "") -> None:
                    self.returncode = 0
                    self.stdout = stdout
                    self.stderr = ""

            if len(argv) >= 3 and argv[1] == "-c":
                return _Result(
                    json.dumps(
                        {
                            "installed": True,
                            "editable": True,
                            "version": "0.4.0",
                            "url": tools_runops.resolve().as_uri(),
                        }
                    )
                )
            return _Result()

        monkeypatch.setattr(
            "runops.cli.update_harness._pull_tools_repo",
            lambda *_args, **_kwargs: "already up to date",
        )
        monkeypatch.setattr("runops.cli.update_harness_tools.subprocess.run", fake_run)
        monkeypatch.setattr(
            "runops.cli.update_harness._restart_with_skip_pull",
            lambda: (_ for _ in ()).throw(typer.Exit(code=0)),
        )
        monkeypatch.delenv(update_harness_module._REEXEC_ENV_VAR, raising=False)

        result = runner.invoke(app, ["update-harness", str(tmp_path)])

        assert result.exit_code == 0
        assert "tools/runops: already up to date" in result.output
        assert "editable install refreshed" in result.output
        assert any(len(call) >= 3 and call[1] == "-c" for call in captured_calls)
        assert any(
            "pip" in call and "install" in call and "-e" in call
            for call in captured_calls
        )

    def test_skips_reinstall_when_editable_metadata_matches(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Do not reinstall when the editable metadata already matches."""
        _init_project(tmp_path)

        tools_runops = tmp_path / "tools" / "runops"
        tools_runops.mkdir(parents=True)
        (tools_runops / "pyproject.toml").write_text(
            "[project]\nname='runops'\nversion='0.5.1'\n",
            encoding="utf-8",
        )

        venv_bin = tmp_path / ".venv" / "bin"
        venv_bin.mkdir(parents=True)
        (venv_bin / "python").write_text("", encoding="utf-8")

        captured_calls: list[list[str]] = []
        restarted: list[bool] = []

        def fake_run(argv, *_, **__):  # type: ignore[no-untyped-def]
            captured_calls.append(list(argv))

            class _Result:
                returncode = 0
                stdout = json.dumps(
                    {
                        "installed": True,
                        "editable": True,
                        "version": "0.5.1",
                        "url": tools_runops.resolve().as_uri(),
                    }
                )
                stderr = ""

            return _Result()

        monkeypatch.setattr(
            "runops.cli.update_harness._pull_tools_repo",
            lambda *_args, **_kwargs: "already up to date",
        )
        monkeypatch.setattr("runops.cli.update_harness_tools.subprocess.run", fake_run)
        monkeypatch.setattr(
            "runops.cli.update_harness._restart_with_skip_pull",
            lambda: restarted.append(True),
        )

        result = runner.invoke(app, ["update-harness", str(tmp_path)])

        assert result.exit_code == 0
        assert "editable install refreshed" not in result.output
        assert restarted == []
        assert not any(
            "pip" in call and "install" in call and "-e" in call
            for call in captured_calls
        )

    def test_reinstall_editable_skipped_without_venv(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When there's no .venv, editable install is skipped gracefully."""
        _init_project(tmp_path)

        tools_runops = tmp_path / "tools" / "runops"
        tools_runops.mkdir(parents=True)
        (tools_runops / "pyproject.toml").write_text("[project]\nname='runops'\n")

        monkeypatch.setattr(
            "runops.cli.update_harness._pull_tools_repo",
            lambda *_args, **_kwargs: "updated",
        )
        monkeypatch.setattr(
            "runops.cli.update_harness._restart_with_skip_pull",
            lambda: (_ for _ in ()).throw(typer.Exit(code=0)),
        )
        monkeypatch.delenv(update_harness_module._REEXEC_ENV_VAR, raising=False)

        result = runner.invoke(app, ["update-harness", str(tmp_path)])

        assert result.exit_code == 0
        assert "skipped (no .venv)" in result.output
