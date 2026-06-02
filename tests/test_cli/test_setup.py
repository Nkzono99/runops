"""Tests for runops setup CLI command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from runops.cli.main import app
from runops.harness.harnessops import HarnessOpsResult

runner = CliRunner()


@pytest.fixture(autouse=True)
def _mock_harnessops(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep setup tests independent from the local hops installation."""
    monkeypatch.setattr(
        "runops.harness.harnessops.initialize_project_harnessops",
        lambda *_args, **_kwargs: HarnessOpsResult(
            "skipped",
            "HarnessOps skipped (test)",
        ),
    )


def _make_existing_project(project_dir: Path, simulator: str | None = None) -> None:
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "runops.toml").write_text(
        '[project]\nname = "setup-project"\n',
        encoding="utf-8",
    )
    simulators = "[simulators]\n"
    if simulator is not None:
        simulators = (
            f"[simulators.{simulator}]\n"
            f'adapter = "{simulator}"\n'
            'resolver_mode = "package"\n'
        )
    (project_dir / "simulators.toml").write_text(simulators, encoding="utf-8")
    (project_dir / "launchers.toml").write_text("[launchers]\n", encoding="utf-8")


def test_setup_renders_imports_for_builtin_agent_guide(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_dir = tmp_path / "setup-project"
    _make_existing_project(project_dir)

    def _fake_bootstrap(
        root: Path,
        _sim_names: list[str],
        _runops_package: str,
        created: list[str],
        _skipped: list[str],
        **_kwargs: object,
    ) -> None:
        (root / ".venv").mkdir(parents=True, exist_ok=True)
        created.append(".venv")

    monkeypatch.setattr("runops.cli.init._bootstrap_environment", _fake_bootstrap)

    result = runner.invoke(app, ["setup", "--path", str(project_dir)])

    assert result.exit_code == 0
    imports_path = project_dir / ".runops" / "knowledge" / "enabled" / "imports.md"
    assert imports_path.is_file()
    imports = imports_path.read_text(encoding="utf-8")
    assert "@.runops/knowledge/runops/agent-user-guide.md" in imports


def test_setup_invokes_harnessops(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Setup delegates HarnessOps project overlay initialization to hops."""
    project_dir = tmp_path / "setup-project"
    _make_existing_project(project_dir)
    calls: list[Path] = []

    def _fake_bootstrap(
        _root: Path,
        _sim_names: list[str],
        _runops_package: str,
        _created: list[str],
        _skipped: list[str],
        **_kwargs: object,
    ) -> None:
        return None

    def _fake_harnessops(root: Path) -> HarnessOpsResult:
        calls.append(root)
        return HarnessOpsResult("created", "HarnessOps initialized")

    monkeypatch.setattr("runops.cli.init._bootstrap_environment", _fake_bootstrap)
    monkeypatch.setattr(
        "runops.harness.harnessops.initialize_project_harnessops",
        _fake_harnessops,
    )

    result = runner.invoke(app, ["setup", "--path", str(project_dir)])

    assert result.exit_code == 0
    assert calls == [project_dir.resolve()]
    assert "HarnessOps initialized" in result.output


def test_setup_runs_auth_for_simulator_packages_without_refs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Setup preflights private package installs but leaves refs opt-in."""
    project_dir = tmp_path / "setup-project"
    _make_existing_project(project_dir, simulator="emses")

    auth_calls: list[tuple[list[str], bool]] = []

    def _record_auth(
        sim_names: list[str],
        *,
        interactive: bool,
        login: bool,
        skip: bool,
        include_refs: bool,
    ) -> None:
        assert interactive is False
        assert login is False
        assert skip is False
        auth_calls.append((sim_names, include_refs))

    monkeypatch.setattr(
        "runops.cli.setup.ensure_github_auth_for_simulators", _record_auth
    )
    monkeypatch.setattr(
        "runops.cli.init._bootstrap_environment",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "runops.cli.init._clone_doc_repos",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("refs should not be cloned by default")
        ),
    )

    result = runner.invoke(app, ["setup", "--path", str(project_dir)])

    assert result.exit_code == 0
    assert auth_calls == [(["emses"], False)]
    assert "Recommended Codex plugins" in result.output
    assert "MPIEMSES3D Context" in result.output
    assert "emout Context" in result.output


def test_setup_with_refs_clones_reference_mirrors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--with-refs opts setup into adapter-declared refs mirrors."""
    project_dir = tmp_path / "setup-project"
    _make_existing_project(project_dir, simulator="emses")

    auth_calls: list[bool] = []
    clone_calls: list[list[str]] = []

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

    def _record_clone(
        _project_dir: Path,
        sim_names: list[str],
    ) -> tuple[list[str], list[str]]:
        clone_calls.append(sim_names)
        return ["refs/MPIEMSES3D"], []

    monkeypatch.setattr(
        "runops.cli.setup.ensure_github_auth_for_simulators", _record_auth
    )
    monkeypatch.setattr(
        "runops.cli.init._bootstrap_environment",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr("runops.cli.init._clone_doc_repos", _record_clone)

    result = runner.invoke(
        app,
        ["setup", "--with-refs", "--path", str(project_dir)],
    )

    assert result.exit_code == 0
    assert auth_calls == [True]
    assert clone_calls == [["emses"]]
    assert "refs/MPIEMSES3D" in result.output


def test_setup_smoke_with_knowledge_attach_render_and_doctor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_dir = tmp_path / "smoke-project"

    def _fake_bootstrap(
        root: Path,
        _sim_names: list[str],
        _runops_package: str,
        created: list[str],
        _skipped: list[str],
        **_kwargs: object,
    ) -> None:
        (root / ".venv").mkdir(parents=True, exist_ok=True)
        created.append(".venv")

    monkeypatch.setattr("runops.cli.init._bootstrap_environment", _fake_bootstrap)

    init_result = runner.invoke(app, ["init", "-y", "--path", str(project_dir)])
    assert init_result.exit_code == 0

    kb_dir = tmp_path / "shared-kb"
    (kb_dir / "profiles").mkdir(parents=True)
    (kb_dir / "README.md").write_text("# Shared KB\n", encoding="utf-8")
    (kb_dir / "profiles" / "common.md").write_text("# Common\n", encoding="utf-8")
    (kb_dir / "entrypoints.toml").write_text(
        '[profiles.common]\nimports = ["profiles/common.md"]\n',
        encoding="utf-8",
    )

    with patch("runops.cli.knowledge.Path.cwd", return_value=project_dir):
        attach_result = runner.invoke(
            app,
            [
                "knowledge",
                "source",
                "attach",
                "path",
                "shared-kb",
                str(kb_dir),
                "--profiles",
                "common",
            ],
        )
        render_result = runner.invoke(app, ["knowledge", "source", "render"])

    assert attach_result.exit_code == 0
    assert render_result.exit_code == 0

    setup_result = runner.invoke(app, ["setup", "--path", str(project_dir)])
    assert setup_result.exit_code == 0

    with patch("runops.cli.init.shutil.which", return_value="/usr/bin/sbatch"):
        doctor_result = runner.invoke(app, ["doctor", str(project_dir)])

    assert doctor_result.exit_code == 0
    imports = (
        project_dir / ".runops" / "knowledge" / "enabled" / "imports.md"
    ).read_text(encoding="utf-8")
    assert "@.runops/knowledge/runops/agent-user-guide.md" in imports
    assert "@refs/knowledge/shared-kb/profiles/common.md" in imports


def test_setup_warns_on_invalid_project_config_and_continues(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_dir = tmp_path / "broken-project"
    project_dir.mkdir()
    (project_dir / "runops.toml").write_text("[project]\nname = [\n", encoding="utf-8")

    captured_sim_names: list[list[str]] = []

    def _fake_bootstrap(
        _root: Path,
        sim_names: list[str],
        _runops_package: str,
        created: list[str],
        _skipped: list[str],
        **_kwargs: object,
    ) -> None:
        captured_sim_names.append(sim_names)
        created.append(".venv")

    monkeypatch.setattr("runops.cli.init._bootstrap_environment", _fake_bootstrap)
    monkeypatch.setattr(
        "runops.cli.init._prepare_knowledge_imports",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "runops.cli.init.scaffold._create_runops_skeleton",
        lambda _root, created: created.append(".runops"),
    )

    result = runner.invoke(app, ["setup", "--path", str(project_dir)])

    assert result.exit_code == 0
    assert "Warning: failed to read project config" in result.output
    assert captured_sim_names == [[]]
