"""Direct tests for init bootstrap helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runops.cli.init.bootstrap import _bootstrap_environment, _python_in_venv


@dataclass
class _CompletedProcess:
    returncode: int = 0
    stderr: str = ""


def test_bootstrap_creates_venv_and_installs_packages(
    tmp_path: Path,
    monkeypatch: Any,
    capsys: Any,
) -> None:
    """Bootstrap runs the expected commands on a fresh project."""
    calls: list[list[str]] = []

    def fake_run(argv, **_kwargs):  # type: ignore[no-untyped-def]
        calls.append(list(argv))
        return _CompletedProcess()

    monkeypatch.setattr("runops.cli.init.bootstrap._find_uv", lambda: "/usr/bin/uv")
    monkeypatch.setattr(
        "runops.cli.init.bootstrap._collect_pip_packages",
        lambda _sim_names: ["emu"],
    )
    monkeypatch.setattr("runops.cli.init.bootstrap.subprocess.run", fake_run)

    created: list[str] = []
    skipped: list[str] = []
    _bootstrap_environment(
        tmp_path,
        ["emses"],
        "runops==1.2.3",
        created,
        skipped,
    )

    assert created == [
        ".venv",
        "uv pip install runops==1.2.3",
        "pip install (1 packages)",
    ]
    assert skipped == []
    expected_python = str(_python_in_venv(tmp_path / ".venv"))
    assert calls == [
        ["/usr/bin/uv", "venv", str(tmp_path / ".venv")],
        [
            "/usr/bin/uv",
            "pip",
            "install",
            "runops==1.2.3",
            "--python",
            expected_python,
        ],
        [
            "/usr/bin/uv",
            "pip",
            "install",
            "emu",
            "--python",
            expected_python,
        ],
    ]

    out = capsys.readouterr().out
    assert "Creating .venv" in out
    assert "Installing runops==1.2.3" in out
    assert "Installing: emu" in out
    assert "Then: runo doctor" in out


def test_bootstrap_returns_early_when_venv_creation_fails(
    tmp_path: Path,
    monkeypatch: Any,
    capsys: Any,
) -> None:
    """Bootstrap stops immediately when ``uv venv`` fails."""
    calls: list[list[str]] = []

    def fake_run(argv, **_kwargs):  # type: ignore[no-untyped-def]
        calls.append(list(argv))
        return _CompletedProcess(returncode=1, stderr="venv failed")

    monkeypatch.setattr("runops.cli.init.bootstrap._find_uv", lambda: "uv")
    monkeypatch.setattr("runops.cli.init.bootstrap.subprocess.run", fake_run)

    created: list[str] = []
    skipped: list[str] = []
    _bootstrap_environment(
        tmp_path,
        [],
        "runops==1.2.3",
        created,
        skipped,
    )

    assert created == []
    assert skipped == []
    assert calls == [["uv", "venv", str(tmp_path / ".venv")]]
    assert "Warning: uv venv failed: venv failed" in capsys.readouterr().out


def test_bootstrap_surfaces_runops_install_failure(
    tmp_path: Path,
    monkeypatch: Any,
    capsys: Any,
) -> None:
    """Bootstrap reports runops install failures and continues to sim packages."""

    def fake_run(argv, **_kwargs):  # type: ignore[no-untyped-def]
        if argv[:2] == ["uv", "venv"]:
            return _CompletedProcess()
        if argv[:3] == ["uv", "pip", "install"]:
            return _CompletedProcess(returncode=1, stderr="install failed")
        msg = f"unexpected call: {argv}"
        raise AssertionError(msg)

    monkeypatch.setattr("runops.cli.init.bootstrap._find_uv", lambda: "uv")
    monkeypatch.setattr("runops.cli.init.bootstrap.subprocess.run", fake_run)

    created: list[str] = []
    skipped: list[str] = []
    _bootstrap_environment(
        tmp_path,
        [],
        "runops==1.2.3",
        created,
        skipped,
    )

    assert created == [".venv"]
    assert skipped == []
    assert "Warning: runops install failed:" in capsys.readouterr().out


def test_bootstrap_skips_existing_venv_and_surfaces_package_failures(
    tmp_path: Path,
    monkeypatch: Any,
    capsys: Any,
) -> None:
    """Existing .venv is skipped while package failures are reported."""
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    calls: list[list[str]] = []

    def fake_run(argv, **_kwargs):  # type: ignore[no-untyped-def]
        calls.append(list(argv))
        return _CompletedProcess(returncode=1, stderr="package failed")

    monkeypatch.setattr("runops.cli.init.bootstrap._find_uv", lambda: "uv")
    monkeypatch.setattr(
        "runops.cli.init.bootstrap._collect_pip_packages",
        lambda _sim_names: ["beach-extra"],
    )
    monkeypatch.setattr("runops.cli.init.bootstrap.subprocess.run", fake_run)

    created: list[str] = []
    skipped: list[str] = []
    _bootstrap_environment(
        tmp_path,
        ["beach"],
        "runops==1.2.3",
        created,
        skipped,
    )

    assert created == []
    assert skipped == [".venv"]
    expected_python = str(_python_in_venv(tmp_path / ".venv"))
    assert calls == [
        [
            "uv",
            "pip",
            "install",
            "runops==1.2.3",
            "--python",
            expected_python,
        ],
        [
            "uv",
            "pip",
            "install",
            "beach-extra",
            "--python",
            expected_python,
        ],
    ]

    out = capsys.readouterr().out
    assert "Warning: runops install failed:" in out
    assert "Warning: pip install failed:" in out
    assert "package failed" in out
