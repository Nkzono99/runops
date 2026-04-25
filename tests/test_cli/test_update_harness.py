"""Tests for runops update-harness CLI command."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

import runops.cli.update_harness as update_harness_module
from runops.cli.main import app
from runops.harness.builder import (
    HARNESS_LOCK_PATH,
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
        assert "cases/AGENTS.md" in lock
        assert "runs/AGENTS.md" in lock

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
        assert (tmp_path / ".vscode" / "settings.json.new").exists()

    def test_backfills_visible_workspace_when_missing(self, tmp_path: Path) -> None:
        """update-harness recreates missing notes/materials scaffold."""
        _init_project(tmp_path)
        (tmp_path / "notes" / "README.md").unlink()
        (tmp_path / "materials" / "README.md").unlink()
        (tmp_path / "materials" / "papers").rmdir()

        result = runner.invoke(app, ["update-harness", str(tmp_path), "--skip-pull"])

        assert result.exit_code == 0
        assert "Backfilled" in result.output
        assert (tmp_path / "notes" / "README.md").is_file()
        assert (tmp_path / "materials" / "README.md").is_file()
        assert (tmp_path / "materials" / "papers").is_dir()
        lock = load_harness_lock(tmp_path)
        assert "notes/README.md" not in lock
        assert "materials/README.md" not in lock

    def test_only_can_limit_workspace_backfill(self, tmp_path: Path) -> None:
        """--only respects notes/materials workspace backfill targets."""
        _init_project(tmp_path)
        (tmp_path / "notes" / "README.md").unlink()
        (tmp_path / "materials" / "README.md").unlink()

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
        monkeypatch.setattr(update_harness_module.sys, "executable", "/usr/bin/python3")
        monkeypatch.setattr(update_harness_module.os, "execvpe", fake_exec)

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
            "runops.cli.update_harness.subprocess.run",
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
