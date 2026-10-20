"""Commands act only on the project found from the cwd (SPEC §7.1, §7.2)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from runops.ops.setup import init_project
from runops.project import Project


@pytest.fixture
def other_project(project_dir: Path, cli, monkeypatch: pytest.MonkeyPatch) -> Path:  # type: ignore[no-untyped-def]
    other = project_dir.parent / "other"
    init_project(other, ["generic"], install=False)
    shutil.copytree(project_dir / "cases", other / "cases", dirs_exist_ok=True)
    monkeypatch.chdir(other)
    assert cli("new", "demo", "--dest", "demo/series").code == 0
    monkeypatch.chdir(project_dir)
    return other


def test_paths_into_another_project_are_refused(
    project_dir: Path, other_project: Path, cli, fake_slurm
) -> None:  # type: ignore[no-untyped-def]
    (theirs,) = Project.open(other_project).iter_runs()
    for args in (
        ("status", str(theirs.run_dir)),
        ("submit", str(theirs.run_dir), "-y"),
        ("submit", "--all", str(other_project / "runs"), "-y"),
        ("list", str(other_project / "runs")),
    ):
        res = cli(*args)
        assert res.code == 2, args
        assert "outside runs/ of this project" in res.err
    assert not any(c[0] == "sbatch" for c in fake_slurm.commands)
    assert Project.open(other_project).resolve_run(theirs.id).status.value == "created"


def test_same_run_id_resolves_in_the_current_project(
    project_dir: Path, other_project: Path, cli
) -> None:  # type: ignore[no-untyped-def]
    (theirs,) = Project.open(other_project).iter_runs()
    (ours,) = cli("new", "demo").run_ids()
    assert ours == theirs.id
    m = Project.open(project_dir).resolve_run(ours)
    assert m.run_dir.is_relative_to(project_dir / "runs")
