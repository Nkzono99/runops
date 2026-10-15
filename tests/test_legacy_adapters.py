"""The ported EMSES / BEACH adapters in examples/adapters work as project-local adapters."""

from __future__ import annotations

import shutil
from pathlib import Path

from runops.project import Project
from runops.util import load_toml

EXAMPLES = Path(__file__).parents[1] / "src" / "runops" / "legacy_adapters"


def _add_sim(project_dir: Path, name: str, case_files: dict[str, str], job: str) -> None:
    (project_dir / "adapters").mkdir(exist_ok=True)
    shutil.copy(EXAMPLES / f"{name}.py", project_dir / "adapters" / f"{name}.py")
    cfg = project_dir / "runops.toml"
    cfg.write_text(
        cfg.read_text()
        + f'\n[simulators.{name}]\nadapter = "{name}"\nresolver_mode = "local_executable"\n'
        f'executable = "/opt/{name}/bin/{name}"\n'
    )
    case = project_dir / "cases" / f"{name}case"
    case.mkdir()
    (case / "case.toml").write_text(f'[case]\nsimulator = "{name}"\n[job]\n{job}\n')
    for filename, text in case_files.items():
        (case / filename).write_text(text)


def test_beach_adapter(project_dir: Path, cli, fake_slurm) -> None:  # type: ignore[no-untyped-def]
    _add_sim(
        project_dir,
        "beach",
        {"beach.toml": "[sim]\nbatch_count = 100\n"},
        'walltime = "1:00:00"\nprocesses = 1\nthreads = 8\ncores = 8',
    )
    res = cli("new", "beachcase", "--set", "sim.batch_count=200", "--submit")
    assert res.code == 0, res.err
    (run_id,) = res.run_ids()
    m = Project.open(project_dir).resolve_run(run_id)
    assert m.section("simulator")["adapter_source"] == "project-local"
    config = load_toml(m.run_dir / "input/beach.toml")
    assert config["sim"]["batch_count"] == 200
    assert config["output"]["dir"] == "work/latest"
    assert "/opt/beach/bin/beach input/beach.toml" in (m.run_dir / "submit/job.sh").read_text()
    assert m.label == "batch_count200"

    (m.run_dir / "work/latest/summary.txt").write_text("batches = 200\nmean = 1.5\n")
    fake_slurm.states[fake_slurm.last_job] = "COMPLETED"
    cli("sync")
    m = Project.open(project_dir).resolve_run(run_id)
    assert m.status.value == "completed"
    cli("summarize", run_id)
    summary = (m.run_dir / "analysis/summary.json").read_text()
    assert '"batches": 200' in summary


def test_beach_failure_from_stderr(project_dir: Path, cli, fake_slurm) -> None:  # type: ignore[no-untyped-def]
    _add_sim(project_dir, "beach", {"beach.toml": "[sim]\n"}, 'walltime = "1:00:00"')
    (run_id,) = cli("new", "beachcase", "--submit").run_ids()
    m = Project.open(project_dir).resolve_run(run_id)
    (m.run_dir / f"work/{fake_slurm.last_job}.err").write_text("forrtl: severe error\n")
    (m.run_dir / "work/latest/summary.txt").write_text("x = 1\n")
    fake_slurm.states[fake_slurm.last_job] = "COMPLETED"
    cli("sync")
    assert Project.open(project_dir).resolve_run(run_id).status.value == "failed"


def test_emses_adapter_and_continue(project_dir: Path, cli, fake_slurm) -> None:  # type: ignore[no-untyped-def]
    _add_sim(
        project_dir,
        "emses",
        {"plasma.toml": "[jobcon]\nnstep = 100\n\n[tmgrid]\nnx = 16\n"},
        'walltime = "1:00:00"\nntasks = 4',
    )
    (run_id,) = cli("new", "emsescase", "--set", "tmgrid.nx=32", "--submit").run_ids()
    m = Project.open(project_dir).resolve_run(run_id)
    assert load_toml(m.run_dir / "input/plasma.toml")["tmgrid"]["nx"] == 32
    job = (m.run_dir / "submit/job.sh").read_text()
    assert "input/plasma.toml -o work/latest" in job
    assert "export EMSES_DEBUG=no" in job

    (m.run_dir / "work/latest/energy").write_text("50 1.0\n100 1.0\n")
    (m.run_dir / "work/latest/SNAPSHOT1").mkdir()
    fake_slurm.states[fake_slurm.last_job] = "COMPLETED"
    cli("sync")
    assert Project.open(project_dir).resolve_run(run_id).status.value == "completed"

    res = cli("new", "--from", run_id, "--continue", "--why", "longer", "--set", "jobcon.nstep=200")
    assert res.code == 0, res.err
    (cont,) = res.run_ids()
    c = Project.open(project_dir).resolve_run(cont)
    plasma = load_toml(c.run_dir / "input/plasma.toml")
    assert plasma["jobcon"] == {"nstep": 200, "jobnum": [1, 1]}
    assert plasma["tmgrid"]["nx"] == 32
    link = c.run_dir / "work/latest/SNAPSHOT0"
    assert link.is_symlink() and link.resolve() == (m.run_dir / "work/latest/SNAPSHOT1").resolve()
    assert c.label.endswith("-cont")
