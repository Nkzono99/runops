"""Tests for runops config CLI commands."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from runops.cli.main import app

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

runner = CliRunner()


def _setup_project(tmp_path: Path) -> None:
    """Create a minimal runops project for config tests."""
    (tmp_path / "runops.toml").write_text('[project]\nname = "test-project"\n')
    (tmp_path / "simulators.toml").write_text("[simulators]\n")
    (tmp_path / "launchers.toml").write_text("[launchers]\n")


class TestConfigShow:
    """Tests for 'runops config show'."""

    def test_show_displays_all_configs(self, tmp_path: Path) -> None:
        """Show command prints all config files."""
        _setup_project(tmp_path)
        result = runner.invoke(app, ["config", "show", "--path", str(tmp_path)])
        assert result.exit_code == 0
        assert "runops.toml" in result.output
        assert "simulators.toml" in result.output
        assert "launchers.toml" in result.output
        assert "test-project" in result.output

    def test_show_fails_without_project(self, tmp_path: Path) -> None:
        """Show fails if runops.toml is missing."""
        result = runner.invoke(app, ["config", "show", "--path", str(tmp_path)])
        assert result.exit_code == 1
        assert "runops.toml not found" in result.output


class TestConfigAddSimulator:
    """Tests for 'runops config add-simulator'."""

    def test_add_simulator_with_name(self, tmp_path: Path) -> None:
        """Add simulator by name with default config (non-interactive)."""
        _setup_project(tmp_path)
        # Provide input for interactive_config prompts
        user_input = "\n".join(
            [
                "local_executable",  # resolver_mode
                "mpiemses3D",  # executable
                "n",  # customize modules?
            ]
        )
        result = runner.invoke(
            app,
            ["config", "add-simulator", "emses", "--path", str(tmp_path)],
            input=user_input,
        )
        assert result.exit_code == 0
        assert "Added simulator 'emses'" in result.output

        # Verify TOML content
        with open(tmp_path / "simulators.toml", "rb") as f:
            data = tomllib.load(f)
        assert "emses" in data["simulators"]
        assert data["simulators"]["emses"]["adapter"] == "emses"

    def test_add_simulator_interactive_selection(self, tmp_path: Path) -> None:
        """Add simulator via interactive selection by number."""
        _setup_project(tmp_path)
        user_input = "\n".join(
            [
                "1",  # select first available (beach)
                "local_executable",  # resolver_mode
                "beach",  # executable
                "n",  # customize modules?
            ]
        )
        result = runner.invoke(
            app,
            ["config", "add-simulator", "--path", str(tmp_path)],
            input=user_input,
        )
        assert result.exit_code == 0
        assert "Added simulator" in result.output

    def test_add_simulator_overwrite_prompt(self, tmp_path: Path) -> None:
        """Adding existing simulator prompts for overwrite confirmation."""
        _setup_project(tmp_path)
        (tmp_path / "simulators.toml").write_text(
            '[simulators.emses]\nadapter = "emses"\n'
        )
        # Decline overwrite
        user_input = "n\n"
        result = runner.invoke(
            app,
            ["config", "add-simulator", "emses", "--path", str(tmp_path)],
            input=user_input,
        )
        assert "Cancelled" in result.output


class TestConfigAddLauncher:
    """Tests for 'runops config add-launcher'."""

    def test_add_launcher_srun(self, tmp_path: Path) -> None:
        """Add srun launcher profile."""
        _setup_project(tmp_path)
        user_input = "\n".join(
            [
                "1",  # srun
                "default",  # profile name
                "--mpi=pmix",  # extra args
            ]
        )
        result = runner.invoke(
            app,
            ["config", "add-launcher", "--path", str(tmp_path)],
            input=user_input,
        )
        assert result.exit_code == 0
        assert "Added launcher 'default'" in result.output

        with open(tmp_path / "launchers.toml", "rb") as f:
            data = tomllib.load(f)
        assert data["launchers"]["default"]["type"] == "srun"
        assert data["launchers"]["default"]["args"] == "--mpi=pmix"


class TestInteractiveInit:
    """Tests for 'runops init' (interactive by default)."""

    @pytest.fixture(autouse=True)
    def _mock_bootstrap(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Skip the bootstrap step (uv install) in interactive init tests."""
        monkeypatch.setattr(
            "runops.cli.init._bootstrap_environment",
            lambda *_args, **_kwargs: None,
        )

    def test_interactive_init_select_simulators(self, tmp_path: Path) -> None:
        """Interactive init prompts for project name and simulators."""
        user_input = "\n".join(
            [
                "my-project",  # project name
                "emses",  # simulator selection
                "n",  # customize settings?
                "",  # launcher (skip)
                "",  # skip knowledge repo selection
                "",  # skip manual knowledge source entry
                "",  # extra line for safety
            ]
        )
        result = runner.invoke(
            app,
            ["init", "--path", str(tmp_path)],
            input=user_input,
        )
        assert result.exit_code == 0
        assert "my-project" in result.output

        content = (tmp_path / "simulators.toml").read_text()
        assert "emses" in content

    def test_interactive_init_skip_all(self, tmp_path: Path) -> None:
        """Interactive init with all defaults skipped."""
        user_input = "\n" * 10
        result = runner.invoke(
            app,
            ["init", "--path", str(tmp_path)],
            input=user_input,
        )
        assert result.exit_code == 0
        content = (tmp_path / "simulators.toml").read_text()
        assert "[simulators]" in content
