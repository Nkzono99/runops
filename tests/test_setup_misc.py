"""init presets, doctor, log, generic templates, case listing."""

from __future__ import annotations

import json
from pathlib import Path

from runops.ops.setup import init_project
from runops.project import Project
from runops.util import load_toml


def test_init_camphor_preset(tmp_path: Path) -> None:
    root = tmp_path / "p"
    init_project(root, ["emses", "mysim=mysim-pkg"], site="camphor", install=False)
    config = load_toml(root / "runops.toml")
    assert config["site"]["resource_style"] == "rsc"
    assert config["simulators"]["emses"]["package"].startswith("MPIEMSES3D")
    assert config["simulators"]["emses"]["modules"][0].startswith("hdf5/")
    assert config["simulators"]["mysim"]["package"] == "mysim-pkg"
    for name in ("LOG.md", "notes/README.md", ".gitignore", "AGENTS.md", "CLAUDE.md"):
        assert (root / name).is_file()
    # no package provides the emses adapter yet -> the bundled port is placed
    assert (root / "adapters/emses.py").is_file()
    assert not (root / "adapters/mysim.py").exists()


def test_init_refuses_existing(project_dir: Path, cli) -> None:  # type: ignore[no-untyped-def]
    res = cli("init", "generic", "--no-install")
    assert res.code == 2 and "already exists" in res.err


def test_doctor_reports_missing_adapter(project_dir: Path, cli) -> None:  # type: ignore[no-untyped-def]
    cfg = project_dir / "runops.toml"
    cfg.write_text(cfg.read_text() + '\n[simulators.ghost]\nadapter = "nosuch"\n')
    res = cli("doctor", "--json")
    assert res.code == 2
    checks = json.loads(res.out)
    assert any(c["level"] == "error" and "nosuch" in c["message"] for c in checks)


def test_log(project_dir: Path, cli, fake_slurm) -> None:  # type: ignore[no-untyped-def]
    (run_id,) = cli("new", "demo", "--submit").run_ids()
    assert cli("log", run_id).code == 2
    m = Project.open(project_dir).resolve_run(run_id)
    (m.run_dir / f"work/{fake_slurm.last_job}.out").write_text(
        "\n".join(f"line{i}" for i in range(100))
    )
    (m.run_dir / f"work/{fake_slurm.last_job}.err").write_text("boom\n")
    res = cli("log", run_id, "-n", "3")
    assert res.out.split() == ["line97", "line98", "line99"]
    assert "boom" in cli("log", run_id, "--err").out


def test_generic_template_error(project_dir: Path, cli) -> None:  # type: ignore[no-untyped-def]
    (project_dir / "cases/demo/input.txt").write_text("{{ missing_value }}\n")
    res = cli("new", "demo")
    assert res.code == 1 and "missing_value" in res.err
    assert not list((project_dir / "runs").rglob("manifest.toml"))
    assert not [p for p in (project_dir / "runs").rglob("*") if p.name.endswith(".staging")]


def test_case_list_and_copy(project_dir: Path, cli) -> None:  # type: ignore[no-untyped-def]
    assert cli("case", "new", "demo2", "--from", "demo").code == 0
    assert load_toml(project_dir / "cases/demo2/case.toml")["case"]["name"] == "demo2"
    rows = json.loads(cli("case", "list", "--json").out)
    assert [r["name"] for r in rows] == ["demo", "demo2"]
    assert cli("case", "new", "bad name", "-s", "generic").code == 2


def test_dest_must_stay_in_runs(project_dir: Path, cli) -> None:  # type: ignore[no-untyped-def]
    assert cli("new", "demo", "--dest", "/tmp").code == 2
    res = cli("new", "demo", "--dest", "topic/a", "--label", "x")
    assert res.code == 0
    (run_id,) = res.run_ids()
    assert (
        Project.open(project_dir).resolve_run(run_id).run_dir.parent == project_dir / "runs/topic/a"
    )


def test_version(cli) -> None:  # type: ignore[no-untyped-def]
    res = cli("--version")
    assert res.code == 0 and res.out.strip().startswith("2.")
