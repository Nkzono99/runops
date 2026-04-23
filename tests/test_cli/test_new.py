"""Tests for `runops case new` (including --minimal and emu auto-run)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from runops.cli.main import app

if TYPE_CHECKING:
    import pytest

runner = CliRunner()


def _make_emses_project(tmp_path: Path) -> Path:
    """Create a minimal EMSES project so ``case new`` can resolve launchers."""
    (tmp_path / "runops.toml").write_text('[project]\nname = "test-project"\n')
    (tmp_path / "simulators.toml").write_text(
        "[simulators.emses]\n"
        'adapter = "emses"\n'
        'executable = "mpiemses3D"\n'
        'resolver_mode = "package"\n'
    )
    (tmp_path / "launchers.toml").write_text(
        '[launchers.srun]\ntype = "srun"\nuse_slurm_ntasks = true\n'
    )
    (tmp_path / "cases").mkdir()
    (tmp_path / "runs").mkdir()
    return tmp_path


def _write_rich_template(project_root: Path) -> Path:
    """Drop a fake rich plasma.toml override under refs/MPIEMSES3D/."""
    refs_dir = project_root / "refs" / "MPIEMSES3D"
    refs_dir.mkdir(parents=True)
    rich = refs_dir / "plasma.toml"
    rich.write_text(
        "# This is the rich (refs/) template, much longer than the bundled one.\n"
        + ("# rich-marker\n" * 50)
    )
    return rich


class TestCaseNewMinimal:
    """Tests for the new --minimal flag."""

    def test_default_uses_rich_template_when_refs_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without --minimal, refs/<sim>/plasma.toml overrides the bundle."""
        project_root = _make_emses_project(tmp_path)
        _write_rich_template(project_root)

        monkeypatch.chdir(project_root)
        result = runner.invoke(app, ["case", "new", "test_case", "-s", "emses"])
        assert result.exit_code == 0, result.output

        plasma_path = project_root / "cases" / "emses" / "test_case" / "plasma.toml"
        assert plasma_path.exists()
        assert "rich-marker" in plasma_path.read_text(encoding="utf-8")

    def test_minimal_skips_rich_template(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--minimal keeps the small bundled template even if refs/ exists."""
        project_root = _make_emses_project(tmp_path)
        _write_rich_template(project_root)

        monkeypatch.chdir(project_root)
        result = runner.invoke(
            app, ["case", "new", "test_case", "-s", "emses", "--minimal"]
        )
        assert result.exit_code == 0, result.output

        plasma_path = project_root / "cases" / "emses" / "test_case" / "plasma.toml"
        assert plasma_path.exists()
        content = plasma_path.read_text(encoding="utf-8")
        # The bundled template ships these markers; the rich one does not.
        assert "rich-marker" not in content
        assert "format_version = 2" in content
        assert "[[species]]" in content

    def test_minimal_short_alias(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``-m`` is an accepted short alias for --minimal."""
        project_root = _make_emses_project(tmp_path)
        _write_rich_template(project_root)

        monkeypatch.chdir(project_root)
        result = runner.invoke(app, ["case", "new", "test_case", "-s", "emses", "-m"])
        assert result.exit_code == 0, result.output

        plasma_path = project_root / "cases" / "emses" / "test_case" / "plasma.toml"
        assert "rich-marker" not in plasma_path.read_text(encoding="utf-8")

    def test_invalid_project_config_warns_and_uses_default_launcher(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Broken launcher config falls back to the default launcher with warning."""
        project_root = _make_emses_project(tmp_path)
        (project_root / "launchers.toml").write_text("[launchers\n", encoding="utf-8")

        monkeypatch.chdir(project_root)
        result = runner.invoke(
            app, ["case", "new", "test_case", "-s", "emses", "--minimal"]
        )

        assert result.exit_code == 0, result.output
        assert "Warning: failed to read project config" in result.output
        case_toml = (
            project_root / "cases" / "emses" / "test_case" / "case.toml"
        ).read_text(encoding="utf-8")
        assert 'launcher = "srun"' in case_toml

    def test_invalid_site_profile_warns_and_uses_standard_resource_style(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Broken site.toml falls back to the standard resource style."""
        project_root = _make_emses_project(tmp_path)
        (project_root / "site.toml").write_text("[site\n", encoding="utf-8")

        monkeypatch.chdir(project_root)
        result = runner.invoke(
            app, ["case", "new", "test_case", "-s", "emses", "--minimal"]
        )

        assert result.exit_code == 0, result.output
        assert "Warning: failed to read site profile" in result.output
        case_toml = (
            project_root / "cases" / "emses" / "test_case" / "case.toml"
        ).read_text(encoding="utf-8")
        assert "ntasks = 1" in case_toml
        assert "processes = 1" not in case_toml


class TestCaseNewEmuAutoRun:
    """Tests for the auto-call to `emu generate -u` after EMSES case creation."""

    def test_emu_missing_is_silent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When ``emu`` is not on PATH, case creation succeeds without noise."""
        project_root = _make_emses_project(tmp_path)

        # Force shutil.which to report emu as missing.
        from runops.cli import new as new_cli

        monkeypatch.setattr(
            new_cli.__dict__.get("shutil", None) or __import__("shutil"),
            "which",
            lambda name: None,
        )

        monkeypatch.chdir(project_root)
        result = runner.invoke(app, ["case", "new", "test_case", "-s", "emses"])
        assert result.exit_code == 0, result.output
        assert "emu generate" not in result.output  # silent

    def test_emu_auto_run_invoked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When ``emu`` is on PATH, ``emu generate -u`` is invoked."""
        project_root = _make_emses_project(tmp_path)

        from runops.cli import new as new_cli

        # Pretend emu exists.
        monkeypatch.setattr(__import__("shutil"), "which", lambda name: "/fake/bin/emu")

        calls: list[list[str]] = []

        class FakeResult:
            returncode = 0
            stderr = ""
            stdout = ""

        def fake_run(cmd: list[str], **kwargs):  # type: ignore[no-untyped-def]
            calls.append(cmd)
            return FakeResult()

        monkeypatch.setattr(
            new_cli.__dict__.get("subprocess", None) or __import__("subprocess"),
            "run",
            fake_run,
        )

        monkeypatch.chdir(project_root)
        result = runner.invoke(app, ["case", "new", "test_case", "-s", "emses"])
        assert result.exit_code == 0, result.output
        assert any(c[:3] == ["emu", "generate", "-u"] for c in calls)
        assert "Populated [meta.physical]" in result.output

    def test_emu_failure_is_warning_not_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An ``emu`` non-zero exit produces a warning but does not fail."""
        project_root = _make_emses_project(tmp_path)

        monkeypatch.setattr(__import__("shutil"), "which", lambda name: "/fake/bin/emu")

        class FakeResult:
            returncode = 1
            stderr = "broken"
            stdout = ""

        def fake_run(cmd: list[str], **kwargs):  # type: ignore[no-untyped-def]
            return FakeResult()

        monkeypatch.setattr(__import__("subprocess"), "run", fake_run)

        monkeypatch.chdir(project_root)
        result = runner.invoke(app, ["case", "new", "test_case", "-s", "emses"])
        # Case creation must still succeed.
        assert result.exit_code == 0, result.output
        case_dir = project_root / "cases" / "emses" / "test_case"
        assert (case_dir / "plasma.toml").exists()
