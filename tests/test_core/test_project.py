"""Tests for core project module."""

from __future__ import annotations

from pathlib import Path

import pytest
import tomli_w

from runops.core.exceptions import ProjectConfigError, ProjectNotFoundError
from runops.core.project import find_project_root, load_project

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


class TestLoadProject:
    """Tests for load_project()."""

    def test_load_minimal_project(self, tmp_path: Path) -> None:
        (tmp_path / "runops.toml").write_text('[project]\nname = "my-project"\n')
        config = load_project(tmp_path)
        assert config.name == "my-project"
        assert config.description == ""
        assert config.root_dir == tmp_path.resolve()
        assert config.simulators == {}
        assert config.launchers == {}
        assert config.experiment_policy.require_experiment is False
        assert config.experiment_policy.max_active_experiments == 5
        assert config.experiment_policy.default_max_materialized_runs == 3
        assert config.experiment_policy.max_unreviewed_completed_runs == 12

    def test_load_experiment_policy(self, tmp_path: Path) -> None:
        (tmp_path / "runops.toml").write_text(
            '[project]\nname = "proj"\n\n'
            "[experiments.policy]\n"
            "require_experiment = true\n"
            "max_active_experiments = 2\n"
            "default_max_materialized_runs = 4\n"
            "max_unreviewed_completed_runs = 8\n"
        )

        policy = load_project(tmp_path).experiment_policy

        assert policy.require_experiment is True
        assert policy.max_active_experiments == 2
        assert policy.default_max_materialized_runs == 4
        assert policy.max_unreviewed_completed_runs == 8

    @pytest.mark.parametrize(
        "policy",
        [
            "require_experiment = 1\n",
            "max_active_experiments = 0\n",
            "default_max_materialized_runs = true\n",
            "max_unreviewed_completed_runs = -1\n",
        ],
    )
    def test_invalid_experiment_policy(self, tmp_path: Path, policy: str) -> None:
        (tmp_path / "runops.toml").write_text(
            '[project]\nname = "proj"\n\n[experiments.policy]\n' + policy
        )

        with pytest.raises(ProjectConfigError, match=r"experiments\.policy"):
            load_project(tmp_path)

    def test_load_with_description(self, tmp_path: Path) -> None:
        (tmp_path / "runops.toml").write_text(
            '[project]\nname = "proj"\ndescription = "A test"\n'
        )
        config = load_project(tmp_path)
        assert config.description == "A test"

    def test_load_with_simulators_and_launchers(self, tmp_path: Path) -> None:
        (tmp_path / "runops.toml").write_text('[project]\nname = "proj"\n')
        (tmp_path / "simulators.toml").write_bytes(
            tomli_w.dumps({"simulators": {"sim1": {"adapter": "a1"}}}).encode()
        )
        (tmp_path / "launchers.toml").write_bytes(
            tomli_w.dumps(
                {"launchers": {"srun": {"kind": "srun", "command": "srun"}}}
            ).encode()
        )
        config = load_project(tmp_path)
        assert "sim1" in config.simulators
        assert "srun" in config.launchers

    def test_load_from_fixture(self) -> None:
        """Load a project using fixture TOML files."""
        # Create a temp-like structure from fixtures
        import shutil
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            src = FIXTURES_DIR
            shutil.copy(src / "sample_runops.toml", tmp / "runops.toml")
            shutil.copy(src / "sample_simulators.toml", tmp / "simulators.toml")
            shutil.copy(src / "sample_launchers.toml", tmp / "launchers.toml")
            config = load_project(tmp)
            assert config.name == "test-project"
            assert "lunar_pic" in config.simulators
            assert "slurm_srun" in config.launchers

    def test_missing_simproject_toml(self, tmp_path: Path) -> None:
        with pytest.raises(ProjectConfigError, match="not found"):
            load_project(tmp_path)

    def test_missing_project_section(self, tmp_path: Path) -> None:
        (tmp_path / "runops.toml").write_text("key = 1\n")
        with pytest.raises(ProjectConfigError, match="\\[project\\] section"):
            load_project(tmp_path)

    def test_missing_project_name(self, tmp_path: Path) -> None:
        (tmp_path / "runops.toml").write_text("[project]\n")
        with pytest.raises(ProjectConfigError, match=r"project\.name"):
            load_project(tmp_path)

    def test_invalid_toml(self, tmp_path: Path) -> None:
        (tmp_path / "runops.toml").write_text("not valid toml [[[")
        with pytest.raises(ProjectConfigError, match="Invalid TOML"):
            load_project(tmp_path)

    def test_frozen_dataclass(self, tmp_path: Path) -> None:
        (tmp_path / "runops.toml").write_text('[project]\nname = "proj"\n')
        config = load_project(tmp_path)
        with pytest.raises(AttributeError):
            config.name = "other"  # type: ignore[misc]


class TestFindProjectRoot:
    """Tests for find_project_root()."""

    def test_find_in_current_dir(self, tmp_path: Path) -> None:
        (tmp_path / "runops.toml").touch()
        assert find_project_root(tmp_path) == tmp_path.resolve()

    def test_find_in_parent_dir(self, tmp_path: Path) -> None:
        (tmp_path / "runops.toml").touch()
        child = tmp_path / "runs" / "survey1"
        child.mkdir(parents=True)
        assert find_project_root(child) == tmp_path.resolve()

    def test_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(ProjectNotFoundError):
            find_project_root(tmp_path)

    def test_start_from_file(self, tmp_path: Path) -> None:
        (tmp_path / "runops.toml").touch()
        some_file = tmp_path / "notes.txt"
        some_file.touch()
        assert find_project_root(some_file) == tmp_path.resolve()
