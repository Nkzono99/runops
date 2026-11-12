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


def test_new_and_sweep_name_case_directories_runs_do_not_get(project_dir: Path, cli) -> None:  # type: ignore[no-untyped-def]
    case = project_dir / "cases/demo"
    (case / "tables").mkdir()
    (case / "tables/contact.csv").write_text("a,b\n")
    (case / "input").mkdir()
    (case / "input/extra.txt").write_text("x\n")
    (case / ".cache").mkdir()
    note = (
        "case demo: tables/ not copied into runs (runs get the case's top-level files and input/)"
    )

    res = cli("new", "demo")
    assert res.code == 0 and note in res.out and "warning" not in res.out
    (run_id,) = res.run_ids()
    run_dir = Project.open(project_dir).resolve_run(run_id).run_dir
    assert (run_dir / "input/extra.txt").is_file() and not (run_dir / "input/tables").exists()

    res = cli("new", "demo", "--json")
    assert note in res.err and json.loads(res.out)

    res = cli("sweep", "demo", "--set", "x=1,2,3", "--apply")
    assert res.out.count(note) == 1  # once per sweep, not per run

    (case / "tables/contact.csv").unlink()
    (case / "tables").rmdir()
    assert "not copied" not in cli("new", "demo").out
