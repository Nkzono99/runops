"""Tests for execution environment detection helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runops.core.environment import (
    EnvironmentInfo,
    PartitionInfo,
    detect_environment,
    load_environment,
    save_environment,
)
from runops.core.environment.runtime import (
    _command_exists,
    _detect_cluster_name,
    _parse_module_list_output,
    _parse_sinfo_output,
)


@dataclass
class _CompletedProcess:
    returncode: int = 0
    stdout: str = ""


def test_load_environment_parses_cluster_partitions_and_modules(tmp_path: Path) -> None:
    """Loading environment.toml produces typed metadata."""
    runops_dir = tmp_path / ".runops"
    runops_dir.mkdir()
    (runops_dir / "environment.toml").write_text(
        """
[cluster]
name = "camphor"
scheduler = "slurm"
scratch_path = "/scratch/$USER"

[cluster.constraints]
qos = "debug"

[cluster.partitions.cpu]
max_nodes = 32
max_walltime = "72:00:00"
default = true

[cluster.partitions.gpu]
max_nodes = 4
gpu = true

[modules]
current = ["gcc/13.2", "openmpi/5.0"]
bad = "ignored"
""".strip()
        + "\n",
        encoding="utf-8",
    )

    info = load_environment(tmp_path)

    assert info is not None
    assert info.cluster_name == "camphor"
    assert info.scheduler == "slurm"
    assert info.scratch_path == "/scratch/$USER"
    assert info.constraints == {"qos": "debug"}
    assert info.modules == {"current": ["gcc/13.2", "openmpi/5.0"]}
    assert info.partitions == [
        PartitionInfo(
            name="cpu",
            max_nodes=32,
            max_walltime="72:00:00",
            default=True,
        ),
        PartitionInfo(
            name="gpu",
            max_nodes=4,
            gpu=True,
        ),
    ]


def test_parse_sinfo_output_handles_default_and_infinite_walltime() -> None:
    """The sinfo parser normalizes defaults and infinite walltime."""
    partitions = _parse_sinfo_output("debug* 2 01:00:00\nbatch 10 infinite\nbroken\n")

    assert partitions == [
        PartitionInfo(
            name="debug",
            max_nodes=2,
            max_walltime="01:00:00",
            default=True,
        ),
        PartitionInfo(
            name="batch",
            max_nodes=10,
            max_walltime="",
        ),
    ]


def test_parse_module_list_output_extracts_current_modules() -> None:
    """The module parser ignores headings and keeps module names only."""
    modules = _parse_module_list_output(
        """
Currently Loaded Modulefiles:
 1) gcc/13.2   2) openmpi/5.0
--------/opt/apps/modulefiles--------
 3) hdf5/1.14
"""
    )

    assert modules == {"current": ["gcc/13.2", "openmpi/5.0", "hdf5/1.14"]}


def test_detect_cluster_name_prefers_env_over_hostname(monkeypatch: Any) -> None:
    """SLURM_CLUSTER_NAME short-circuits the hostname probe."""
    calls: list[list[str]] = []

    def fake_run(argv, **_kwargs):  # type: ignore[no-untyped-def]
        calls.append(list(argv))
        return _CompletedProcess(stdout="ignored\n")

    monkeypatch.setenv("SLURM_CLUSTER_NAME", "camphor")
    monkeypatch.setattr("runops.core.environment.runtime.subprocess.run", fake_run)

    assert _detect_cluster_name() == "camphor"
    assert calls == []


def test_detect_cluster_name_falls_back_to_hostname(
    monkeypatch: Any,
) -> None:
    """Hostname is used when SLURM_CLUSTER_NAME is absent."""

    def fake_run(argv, **_kwargs):  # type: ignore[no-untyped-def]
        assert list(argv) == ["hostname", "-s"]
        return _CompletedProcess(stdout="camphor-node\n")

    monkeypatch.delenv("SLURM_CLUSTER_NAME", raising=False)
    monkeypatch.setattr("runops.core.environment.runtime.subprocess.run", fake_run)

    assert _detect_cluster_name() == "camphor-node"


def test_command_exists_uses_shutil_which(monkeypatch: Any) -> None:
    """Command detection delegates to shutil.which."""
    monkeypatch.setattr(
        "runops.core.environment.runtime.shutil.which", lambda cmd: f"/bin/{cmd}"
    )
    assert _command_exists("sinfo") is True

    monkeypatch.setattr(
        "runops.core.environment.runtime.shutil.which",
        lambda _cmd: None,
    )
    assert _command_exists("missing") is False


def test_detect_environment_collects_scheduler_modules_and_cluster_name(
    monkeypatch: Any,
) -> None:
    """Public detection wires together the helper probes."""
    monkeypatch.setattr(
        "runops.core.environment.runtime._command_exists", lambda cmd: cmd == "sinfo"
    )
    monkeypatch.setattr(
        "runops.core.environment.runtime._detect_slurm_partitions",
        lambda: [PartitionInfo(name="debug", max_nodes=2, default=True)],
    )
    monkeypatch.setattr(
        "runops.core.environment.runtime._detect_cluster_name",
        lambda: "camphor",
    )
    monkeypatch.setattr(
        "runops.core.environment.runtime._detect_modules",
        lambda: {"current": ["gcc/13.2"]},
    )

    info = detect_environment()

    assert info.scheduler == "slurm"
    assert info.cluster_name == "camphor"
    assert info.partitions == [PartitionInfo(name="debug", max_nodes=2, default=True)]
    assert info.modules == {"current": ["gcc/13.2"]}


def test_save_environment_round_trips_via_load(tmp_path: Path) -> None:
    """Saving then loading preserves the structured environment info."""
    info = EnvironmentInfo(
        cluster_name="camphor",
        scheduler="slurm",
        partitions=[
            PartitionInfo(
                name="cpu",
                max_nodes=32,
                max_walltime="72:00:00",
                default=True,
            )
        ],
        modules={"current": ["gcc/13.2"]},
        scratch_path="/scratch/$USER",
        constraints={"qos": "debug"},
    )

    saved_path = save_environment(tmp_path, info)
    loaded = load_environment(tmp_path)

    assert saved_path == tmp_path / ".runops" / "environment.toml"
    assert loaded is not None
    assert loaded.cluster_name == "camphor"
    assert loaded.modules == {"current": ["gcc/13.2"]}
    assert loaded.partitions == info.partitions
    assert loaded.constraints == {"qos": "debug"}
