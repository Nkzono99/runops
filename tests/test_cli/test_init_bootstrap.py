"""Direct tests for init bootstrap helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runops.cli.init.bootstrap import _bootstrap_environment


@dataclass
class _CompletedProcess:
    returncode: int = 0
    stderr: str = ""


def test_bootstrap_creates_venv_runops_and_sim_packages(
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
        "https://example.com/runops.git",
        created,
        skipped,
    )

    assert created == [
        ".venv",
        "tools/runops",
        "uv pip install -e tools/runops",
        "pip install (1 packages)",
    ]
    assert skipped == []
    assert calls == [
        ["/usr/bin/uv", "venv", str(tmp_path / ".venv")],
        [
            "git",
            "clone",
            "https://example.com/runops.git",
            str(tmp_path / "tools" / "runops"),
        ],
        [
            "/usr/bin/uv",
            "pip",
            "install",
            "-e",
            str(tmp_path / "tools" / "runops"),
            "--python",
            str(tmp_path / ".venv" / "bin" / "python"),
        ],
        [
            "/usr/bin/uv",
            "pip",
            "install",
            "emu",
            "--python",
            str(tmp_path / ".venv" / "bin" / "python"),
        ],
    ]

    out = capsys.readouterr().out
    assert "Creating .venv" in out
    assert "Cloning runops into tools/" in out
    assert "Installing runops (editable)" in out
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
        "https://example.com/runops.git",
        created,
        skipped,
    )

    assert created == []
    assert skipped == []
    assert calls == [["uv", "venv", str(tmp_path / ".venv")]]
    assert "Warning: uv venv failed: venv failed" in capsys.readouterr().out


def test_bootstrap_returns_early_when_clone_fails(
    tmp_path: Path,
    monkeypatch: Any,
    capsys: Any,
) -> None:
    """Bootstrap stops after cloning fails and preserves earlier progress."""

    def fake_run(argv, **_kwargs):  # type: ignore[no-untyped-def]
        if argv[:2] == ["uv", "venv"]:
            return _CompletedProcess()
        if argv[:2] == ["git", "clone"]:
            return _CompletedProcess(returncode=1, stderr="clone failed")
        msg = f"unexpected call: {argv}"
        raise AssertionError(msg)

    monkeypatch.setattr("runops.cli.init.bootstrap._find_uv", lambda: "uv")
    monkeypatch.setattr("runops.cli.init.bootstrap.subprocess.run", fake_run)

    created: list[str] = []
    skipped: list[str] = []
    _bootstrap_environment(
        tmp_path,
        [],
        "https://example.com/runops.git",
        created,
        skipped,
    )

    assert created == [".venv"]
    assert skipped == []
    assert "Warning: git clone failed: clone failed" in capsys.readouterr().out


def test_bootstrap_skips_existing_layout_and_surfaces_install_failures(
    tmp_path: Path,
    monkeypatch: Any,
    capsys: Any,
) -> None:
    """Existing .venv/tools are skipped while install failures are reported."""
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    (tmp_path / "tools" / "runops").mkdir(parents=True)
    calls: list[list[str]] = []

    def fake_run(argv, **_kwargs):  # type: ignore[no-untyped-def]
        calls.append(list(argv))
        if "-e" in argv:
            return _CompletedProcess(returncode=1, stderr="editable failed")
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
        "https://example.com/runops.git",
        created,
        skipped,
    )

    assert created == []
    assert skipped == [".venv", "tools/runops"]
    assert calls == [
        [
            "uv",
            "pip",
            "install",
            "-e",
            str(tmp_path / "tools" / "runops"),
            "--python",
            str(tmp_path / ".venv" / "bin" / "python"),
        ],
        [
            "uv",
            "pip",
            "install",
            "beach-extra",
            "--python",
            str(tmp_path / ".venv" / "bin" / "python"),
        ],
    ]

    out = capsys.readouterr().out
    assert "Warning: editable install failed:" in out
    assert "editable failed" in out
    assert "Warning: pip install failed:" in out
    assert "package failed" in out
