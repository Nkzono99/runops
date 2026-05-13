"""Common test fixtures for runops tests."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture()
def tmp_project(tmp_path: Path) -> Path:
    """Create a minimal runops project directory structure.

    Returns:
        Path to the temporary project root.
    """
    (tmp_path / "runops.toml").write_text('[project]\nname = "test-project"\n')
    (tmp_path / "cases").mkdir()
    (tmp_path / "runs").mkdir()
    return tmp_path


@pytest.fixture()
def mock_init_external_processes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip slow external init side effects in CLI scaffold tests."""
    monkeypatch.setattr(
        "runops.cli.init.command._clone_doc_repos",
        lambda *_args, **_kwargs: ([], []),
    )

    real_run = subprocess.run

    def fake_subprocess_run(
        args: Any,
        *run_args: Any,
        **run_kwargs: Any,
    ) -> subprocess.CompletedProcess[Any]:
        if isinstance(args, (list, tuple)) and args and args[0] == "git":
            command = args[1] if len(args) > 1 else ""
            cwd = run_kwargs.get("cwd")
            if command == "init":
                if cwd is not None:
                    (Path(cwd) / ".git").mkdir(parents=True, exist_ok=True)
                return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
            if command in {"add", "commit"}:
                return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        return real_run(args, *run_args, **run_kwargs)

    monkeypatch.setattr(subprocess, "run", fake_subprocess_run)


@pytest.fixture()
def sample_case_data() -> dict[str, Any]:
    """Return sample case.toml data as a dictionary."""
    return {
        "case": {
            "name": "test_case",
            "simulator": "test_sim",
            "launcher": "slurm_srun",
            "description": "A test case",
        },
        "job": {
            "partition": "debug",
            "nodes": 1,
            "ntasks": 4,
            "walltime": "00:10:00",
        },
        "params": {
            "nx": 64,
            "ny": 64,
            "dt": 1.0e-6,
        },
    }


@pytest.fixture()
def sample_manifest_data() -> dict[str, Any]:
    """Return sample manifest.toml data as a dictionary."""
    return {
        "run": {
            "id": "R20260327-0001",
            "display_name": "test_run",
            "status": "created",
            "created_at": "2026-03-27T13:00:00+09:00",
        },
        "origin": {
            "case": "test_case",
            "survey": "",
            "parent_run": "",
        },
        "simulator": {
            "name": "test_sim",
            "adapter": "test_adapter",
        },
        "job": {
            "scheduler": "slurm",
            "job_id": "",
            "partition": "debug",
            "nodes": 1,
            "ntasks": 4,
            "walltime": "00:10:00",
        },
    }
