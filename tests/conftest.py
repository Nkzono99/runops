"""Shared fixtures: a generic project and a fake Slurm."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from runops import slurm
from runops.cli import main
from runops.ops.setup import init_project
from runops.project import Project
from runops.slurm import CommandResult

CASE_TOML = """\
[case]
name = "demo"
simulator = "generic"
tags = ["t1"]

[job]
partition = "gr1"
walltime = "1:00:00"
ntasks = 4

[params]
x = 1
name = "a"
"""


@dataclass
class FakeSlurm:
    """Records commands; job states are set per job id."""

    next_id: int = 1000
    states: dict[str, str] = field(default_factory=dict)  # job id -> state
    unknown: set[str] = field(default_factory=set)
    commands: list[list[str]] = field(default_factory=list)
    fail_sbatch: bool = False

    def __call__(self, cmd: list[str]) -> CommandResult:
        self.commands.append(cmd)
        tool = cmd[0]
        if tool == "sbatch":
            if self.fail_sbatch:
                return CommandResult(1, "", "sbatch: error: invalid partition")
            self.next_id += 1
            job = str(self.next_id)
            self.states[job] = "PENDING"
            return CommandResult(0, f"Submitted batch job {job}\n", "")
        if tool == "scancel":
            self.states[cmd[1]] = "CANCELLED"
            return CommandResult(0, "", "")
        if tool in ("squeue", "sacct"):
            jobs = next(a for a in cmd if a.startswith("--jobs=")).removeprefix("--jobs=")
            lines = []
            for job in jobs.split(","):
                state = self.states.get(job, "")
                if job in self.unknown or not state:
                    continue
                if tool == "squeue":
                    if state in ("PENDING", "RUNNING"):
                        lines.append(f"{job} {state}")
                else:
                    lines.append(f"{job}|{state}|0:0\n{job}.batch|{state}|0:0")
            return CommandResult(0, "".join(line + "\n" for line in lines), "")
        raise AssertionError(f"unexpected command {cmd}")

    def scheduler_calls(self) -> list[list[str]]:
        return [c for c in self.commands if c[0] in ("squeue", "sacct")]

    @property
    def last_job(self) -> str:
        return str(self.next_id)


@pytest.fixture(autouse=True)
def fixed_hostname(monkeypatch: pytest.MonkeyPatch) -> None:
    """Site detection must not depend on the machine running the tests."""
    monkeypatch.setattr("runops.ops.setup.hostname", lambda: "testhost")


@pytest.fixture
def fake_slurm(monkeypatch: pytest.MonkeyPatch) -> FakeSlurm:
    fake = FakeSlurm()
    monkeypatch.setattr(slurm, "default_runner", fake)
    return fake


@pytest.fixture
def project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "proj"
    init_project(root, ["generic"], install=False)
    case = root / "cases" / "demo"
    case.mkdir(parents=True)
    (case / "case.toml").write_text(CASE_TOML)
    (case / "input.txt").write_text("x = {{ x }}\nname = {{ name }}\n")
    monkeypatch.chdir(root)
    monkeypatch.setenv("COLUMNS", "250")
    monkeypatch.setenv("RUNOPS_ACTOR", "test")
    return root


@pytest.fixture
def project(project_dir: Path) -> Project:
    return Project.open(project_dir)


class CliResult:
    def __init__(self, code: int, out: str, err: str) -> None:
        self.code = code
        self.out = out
        self.err = err

    def run_ids(self) -> list[str]:
        return re.findall(r"created (R\d{8}-\d{4})", self.out)


@pytest.fixture
def cli(capsys: pytest.CaptureFixture[str]):  # type: ignore[no-untyped-def]
    def run(*args: str) -> CliResult:
        code = 0
        try:
            main(list(args))
        except SystemExit as exc:
            code = int(exc.code or 0)
        captured = capsys.readouterr()
        return CliResult(code, captured.out, captured.err)

    return run
