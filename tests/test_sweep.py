"""Acceptance 4."""

from __future__ import annotations

import json
from pathlib import Path

from runops.project import Project


def test_sweep_preview_and_apply(project_dir: Path, cli) -> None:  # type: ignore[no-untyped-def]
    res = cli("sweep", "demo", "--set", "a=1,2", "--set", "b=x,y", "--json")
    assert res.code == 0, res.err
    plan = json.loads(res.out)
    assert len(plan["points"]) == 4
    assert plan["points"][0] == {
        "ref": "p0001",
        "label": "a1_bx",
        "values": {"a": 1, "b": "x"},
    }
    assert plan["core_hours"] == 16.0
    assert not any((project_dir / "runs").rglob("manifest.toml"))

    res = cli(
        "sweep",
        "demo",
        "--set",
        "a=1,2",
        "--set",
        "b=x,y",
        "--label",
        "ab",
        "--apply",
        "--why",
        "scan",
    )
    assert res.code == 0, res.err
    ids = res.run_ids()
    assert len(ids) == 4
    project = Project.open(project_dir)
    for run_id in ids:
        m = project.resolve_run(run_id)
        assert m.run_dir.parent == project_dir / "runs/demo/ab"
        assert m.data["variation"]["changed_keys"] == ["a", "b"]
        assert m.sweep == "ab"
        assert m.why == "scan"
    assert len(json.loads(cli("list", "--sweep", "ab", "--json").out)) == 4


def test_sweep_rules(project_dir: Path, cli) -> None:  # type: ignore[no-untyped-def]
    assert cli("sweep", "demo", "--set", "a=1", "--set", "a=2").code == 2
    assert cli("sweep", "demo").code == 2
    assert cli("sweep", "demo", "--set", "a=1,2", "--submit").code == 2
    res = cli("sweep", "demo", "--set", "a=1,2,3", "--limit", "2", "--apply")
    assert len(res.run_ids()) == 2
    res = cli("sweep", "demo", "--set", "v=[1,2],[3,4]", "--json")
    values = [p["values"]["v"] for p in json.loads(res.out)["points"]]
    assert values == [[1, 2], [3, 4]]


def test_run_ids_are_unique_and_sequential(project_dir: Path, cli) -> None:  # type: ignore[no-untyped-def]
    ids = cli("sweep", "demo", "--set", "a=1,2,3", "--apply").run_ids()
    ids += cli("new", "demo").run_ids()
    numbers = [int(i.split("-")[1]) for i in ids]
    assert numbers == [1, 2, 3, 4]
