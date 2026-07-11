"""Tests for the ``runops update`` CLI command."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from runops.cli.main import app
from runops.cli.update import (
    _build_install_cmd,
    _collect_packages,
    _distribution_name_from_package_spec,
    _find_editable_installs,
    _find_venv_python,
    _get_project_simulators,
    _normalize_package_name,
)
from runops.core.exceptions import SimctlError

runner = CliRunner()


def test_find_venv_python_prefers_project_virtualenv(tmp_path: Path) -> None:
    python_path = tmp_path / ".venv" / "bin" / "python"
    python_path.parent.mkdir(parents=True)
    python_path.write_text("", encoding="utf-8")

    with (
        patch("runops.cli.update.Path.cwd", return_value=tmp_path),
        patch("runops.cli.update.find_project_root", return_value=tmp_path),
    ):
        assert _find_venv_python() == python_path


def test_find_venv_python_returns_none_when_project_lookup_fails(
    tmp_path: Path,
) -> None:
    with (
        patch("runops.cli.update.Path.cwd", return_value=tmp_path),
        patch(
            "runops.cli.update.find_project_root", side_effect=SimctlError("no project")
        ),
        patch.dict(os.environ, {}, clear=False),
    ):
        os.environ.pop("VIRTUAL_ENV", None)
        assert _find_venv_python() is None


def test_find_venv_python_falls_back_to_virtual_env(tmp_path: Path) -> None:
    """When project .venv is missing, VIRTUAL_ENV should be honored."""
    real_venv = tmp_path / "shared_venv"
    python_path = real_venv / "bin" / "python"
    python_path.parent.mkdir(parents=True)
    python_path.write_text("", encoding="utf-8")

    project_dir = tmp_path / "project"
    project_dir.mkdir()

    with (
        patch("runops.cli.update.Path.cwd", return_value=project_dir),
        patch("runops.cli.update.find_project_root", return_value=project_dir),
        patch.dict(os.environ, {"VIRTUAL_ENV": str(real_venv)}, clear=False),
    ):
        assert _find_venv_python() == python_path


def test_find_venv_python_resolves_symlinked_venv(tmp_path: Path) -> None:
    """Symlinked project paths should still locate the real .venv."""
    real_project = tmp_path / "real" / "project"
    python_path = real_project / ".venv" / "bin" / "python"
    python_path.parent.mkdir(parents=True)
    python_path.write_text("", encoding="utf-8")

    link_dir = tmp_path / "link"
    try:
        link_dir.symlink_to(real_project, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    with (
        patch("runops.cli.update.Path.cwd", return_value=link_dir),
        patch("runops.cli.update.find_project_root", return_value=link_dir),
    ):
        result = _find_venv_python()
        assert result is not None
        assert result.resolve() == python_path.resolve()


def test_find_venv_python_works_without_pip(tmp_path: Path) -> None:
    """A uv-created venv without pip should still be discoverable."""
    venv = tmp_path / ".venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python").write_text("")
    # Crucially: NO pip binary in .venv/bin

    with (
        patch("runops.cli.update.Path.cwd", return_value=tmp_path),
        patch("runops.cli.update.find_project_root", return_value=tmp_path),
    ):
        assert _find_venv_python() == venv / "bin" / "python"


def test_build_install_cmd_prefers_uv_when_available(tmp_path: Path) -> None:
    venv_py = tmp_path / ".venv" / "bin" / "python"
    with patch("runops.cli.update._find_uv", return_value="/usr/local/bin/uv"):
        cmd, approach = _build_install_cmd(venv_py, ["emout", "numpy"])
    assert approach == "uv pip"
    assert cmd[:5] == [
        "/usr/local/bin/uv",
        "pip",
        "install",
        "--python",
        str(venv_py),
    ]
    assert "--upgrade" in cmd
    assert cmd[-2:] == ["emout", "numpy"]


def test_build_install_cmd_falls_back_to_python_m_pip(tmp_path: Path) -> None:
    venv_py = tmp_path / ".venv" / "bin" / "python"
    with patch("runops.cli.update._find_uv", return_value=None):
        cmd, approach = _build_install_cmd(venv_py, ["emout"])
    assert approach == "python -m pip"
    assert cmd[:4] == [str(venv_py), "-m", "pip", "install"]
    assert cmd[-1] == "emout"


def test_distribution_name_from_package_spec() -> None:
    assert (
        _distribution_name_from_package_spec(
            "MPIEMSES3D @ git+https://github.com/CS12-Laboratory/MPIEMSES3D.git"
        )
        == "MPIEMSES3D"
    )
    assert _distribution_name_from_package_spec("beach-bem>=1.0") == "beach-bem"
    assert _distribution_name_from_package_spec("git+https://x/y.git#egg=foo") == "foo"
    assert _distribution_name_from_package_spec("") is None


def test_normalize_package_name() -> None:
    assert _normalize_package_name("MPIEMSES3D") == "mpiemses3d"
    assert _normalize_package_name("beach_bem.plugin") == "beach-bem-plugin"


def test_find_editable_installs_reads_direct_url_metadata(tmp_path: Path) -> None:
    venv_py = tmp_path / ".venv" / "bin" / "python"
    payload = [
        {
            "name": "MPIEMSES3D",
            "url": "file:///project/refs/MPIEMSES3D",
        }
    ]
    completed = SimpleNamespace(returncode=0, stdout=json.dumps(payload))

    with patch("runops.cli.update.subprocess.run", return_value=completed) as mock_run:
        editables = _find_editable_installs(
            venv_py,
            [
                "MPIEMSES3D @ git+https://github.com/CS12-Laboratory/MPIEMSES3D.git",
                "numpy",
            ],
        )

    assert editables[0].name == "MPIEMSES3D"
    assert editables[0].url == "file:///project/refs/MPIEMSES3D"
    cmd = mock_run.call_args.args[0]
    assert cmd[0] == str(venv_py)
    assert json.loads(cmd[-1]) == ["mpiemses3d", "numpy"]


def test_collect_packages_deduplicates_and_skips_unknown_adapters() -> None:
    fake_registry = SimpleNamespace(
        get=lambda name: {
            "emses": SimpleNamespace(pip_packages=lambda: ["emout", "numpy", "numpy"]),
            "beach": SimpleNamespace(pip_packages=lambda: ["beach-tools", "numpy"]),
        }[name]
    )

    with patch(
        "runops.adapters.registry.get_global_registry",
        return_value=fake_registry,
    ):
        packages = _collect_packages(["emses", "missing", "beach"])

    assert packages == ["emout", "numpy", "beach-tools"]


def test_get_project_simulators_reads_loaded_project(tmp_path: Path) -> None:
    project = SimpleNamespace(simulators={"emses": {}, "beach": {}})

    with (
        patch("runops.cli.update.Path.cwd", return_value=tmp_path),
        patch("runops.cli.update.find_project_root", return_value=tmp_path),
        patch("runops.cli.update.load_project", return_value=project),
    ):
        simulators = _get_project_simulators()

    assert simulators == ["emses", "beach"]


def test_get_project_simulators_returns_empty_on_error(tmp_path: Path) -> None:
    with (
        patch("runops.cli.update.Path.cwd", return_value=tmp_path),
        patch("runops.cli.update.find_project_root", side_effect=SimctlError("boom")),
    ):
        assert _get_project_simulators() == []


def test_update_requires_simulators_when_project_has_none() -> None:
    with patch("runops.cli.update._get_project_simulators", return_value=[]):
        result = runner.invoke(app, ["update"])

    assert result.exit_code == 1
    assert "No simulators found in project" in result.output


def test_update_reports_when_no_packages_are_needed() -> None:
    with (
        patch("runops.cli.update._get_project_simulators", return_value=["emses"]),
        patch("runops.cli.update._collect_packages", return_value=[]),
    ):
        result = runner.invoke(app, ["update"])

    assert result.exit_code == 0
    assert "No packages to upgrade for: emses" in result.output


def test_update_dry_run_lists_packages(tmp_path: Path) -> None:
    with (
        patch("runops.cli.update._get_project_simulators", return_value=["emses"]),
        patch("runops.cli.update._collect_packages", return_value=["emout", "numpy"]),
    ):
        result = runner.invoke(app, ["update", "--dry-run"])

    assert result.exit_code == 0
    assert "Would upgrade for simulators: emses" in result.output
    assert "emout" in result.output
    assert "numpy" in result.output


def test_update_requires_virtualenv_for_real_upgrade() -> None:
    with (
        patch("runops.cli.update._get_project_simulators", return_value=["emses"]),
        patch("runops.cli.update._collect_packages", return_value=["emout"]),
        patch("runops.cli.update._find_venv_python", return_value=None),
    ):
        result = runner.invoke(app, ["update"])

    assert result.exit_code == 1
    assert "No .venv found" in result.output


def test_update_aborts_before_replacing_editable_install(tmp_path: Path) -> None:
    venv_py = tmp_path / ".venv" / "bin" / "python"

    with (
        patch("runops.cli.update._collect_packages", return_value=["MPIEMSES3D"]),
        patch("runops.cli.update._find_venv_python", return_value=venv_py),
        patch(
            "runops.cli.update._find_editable_installs",
            return_value=[
                SimpleNamespace(
                    name="MPIEMSES3D",
                    url="file:///project/refs/MPIEMSES3D",
                )
            ],
        ),
        patch("runops.cli.update.subprocess.run") as mock_run,
    ):
        result = runner.invoke(app, ["update", "emses"], input="n\n")

    assert result.exit_code == 1
    assert "editable-installed" in result.output
    assert "Aborted." in result.output
    mock_run.assert_not_called()


def test_update_yes_replaces_editable_install(tmp_path: Path) -> None:
    completed = SimpleNamespace(returncode=0)
    venv_py = tmp_path / ".venv" / "bin" / "python"

    with (
        patch("runops.cli.update._collect_packages", return_value=["MPIEMSES3D"]),
        patch("runops.cli.update._find_venv_python", return_value=venv_py),
        patch(
            "runops.cli.update._find_editable_installs",
            return_value=[
                SimpleNamespace(
                    name="MPIEMSES3D",
                    url="file:///project/refs/MPIEMSES3D",
                )
            ],
        ),
        patch("runops.cli.update._find_uv", return_value="/usr/local/bin/uv"),
        patch("runops.cli.update.subprocess.run", return_value=completed) as mock_run,
    ):
        result = runner.invoke(app, ["update", "emses", "--yes"])

    assert result.exit_code == 0, result.output
    assert "editable-installed" in result.output
    assert mock_run.call_args.args[0][-1] == "MPIEMSES3D"


def test_update_help_hides_force_compatibility_alias() -> None:
    result = runner.invoke(
        app,
        ["update", "--help"],
        env={"COLUMNS": "160", "TERM": "dumb", "NO_COLOR": "1"},
    )

    assert result.exit_code == 0, result.output
    assert "--yes" in result.output
    assert "--force" not in result.output


def test_update_force_alias_keeps_yes_behavior(tmp_path: Path) -> None:
    completed = SimpleNamespace(returncode=0)
    venv_py = tmp_path / ".venv" / "bin" / "python"

    with (
        patch("runops.cli.update._collect_packages", return_value=["MPIEMSES3D"]),
        patch("runops.cli.update._find_venv_python", return_value=venv_py),
        patch(
            "runops.cli.update._find_editable_installs",
            return_value=[
                SimpleNamespace(
                    name="MPIEMSES3D",
                    url="file:///project/refs/MPIEMSES3D",
                )
            ],
        ),
        patch("runops.cli.update._find_uv", return_value="/usr/local/bin/uv"),
        patch("runops.cli.update.subprocess.run", return_value=completed) as mock_run,
    ):
        result = runner.invoke(app, ["update", "emses", "--force"])

    assert result.exit_code == 0, result.output
    assert mock_run.call_args.args[0][-1] == "MPIEMSES3D"


def test_update_runs_uv_pip_install_for_selected_simulators(tmp_path: Path) -> None:
    completed = SimpleNamespace(returncode=0)
    venv_py = tmp_path / ".venv" / "bin" / "python"

    with (
        patch("runops.cli.update._collect_packages", return_value=["emout", "numpy"]),
        patch("runops.cli.update._find_venv_python", return_value=venv_py),
        patch("runops.cli.update._find_uv", return_value="/usr/local/bin/uv"),
        patch("runops.cli.update.subprocess.run", return_value=completed) as mock_run,
    ):
        result = runner.invoke(app, ["update", "emses", "beach"])

    assert result.exit_code == 0, result.output
    assert "Upgrading packages for: emses, beach" in result.output
    assert "uv pip" in result.output
    assert "Upgraded 2 packages." in result.output
    assert mock_run.call_args.args[0] == [
        "/usr/local/bin/uv",
        "pip",
        "install",
        "--python",
        str(venv_py),
        "--upgrade",
        "emout",
        "numpy",
    ]


def test_update_falls_back_to_python_m_pip_when_uv_missing(tmp_path: Path) -> None:
    """Without uv, fall back to python -m pip."""
    completed = SimpleNamespace(returncode=0)
    venv_py = tmp_path / ".venv" / "bin" / "python"

    with (
        patch("runops.cli.update._collect_packages", return_value=["emout"]),
        patch("runops.cli.update._find_venv_python", return_value=venv_py),
        patch("runops.cli.update._find_uv", return_value=None),
        patch("runops.cli.update.subprocess.run", return_value=completed) as mock_run,
    ):
        result = runner.invoke(app, ["update", "emses"])

    assert result.exit_code == 0, result.output
    assert "python -m pip" in result.output
    assert mock_run.call_args.args[0] == [
        str(venv_py),
        "-m",
        "pip",
        "install",
        "--upgrade",
        "emout",
    ]


def test_update_surfaces_upgrade_failures(tmp_path: Path) -> None:
    failed = SimpleNamespace(returncode=1)
    venv_py = tmp_path / ".venv" / "bin" / "python"

    with (
        patch("runops.cli.update._collect_packages", return_value=["emout"]),
        patch("runops.cli.update._find_venv_python", return_value=venv_py),
        patch("runops.cli.update._find_uv", return_value="/usr/local/bin/uv"),
        patch("runops.cli.update.subprocess.run", return_value=failed),
    ):
        result = runner.invoke(app, ["update", "emses"])

    assert result.exit_code == 1
    assert "Upgrade failed." in result.output
