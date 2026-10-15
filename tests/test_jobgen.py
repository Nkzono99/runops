"""Acceptance 8: job.sh golden files for MPI/standard and OpenMP/rsc."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from runops.config import LauncherConfig, SimulatorConfig, SiteConfig
from runops.errors import UsageError
from runops.jobgen import render_job_script

GOLDEN = Path(__file__).parent / "golden"
RUN_DIR = Path("/work/proj/runs/case/R20261015-0001--x")


def _check(name: str, text: str) -> None:
    path = GOLDEN / name
    if os.environ.get("UPDATE_GOLDEN"):
        path.write_text(text)
    assert text == path.read_text()


def test_mpi_standard() -> None:
    text = render_job_script(
        run_dir=RUN_DIR,
        run_id="R20261015-0001",
        job={
            "partition": "gr20001a",
            "nodes": 2,
            "ntasks": 64,
            "walltime": "12:00:00",
            "qos": "high",
        },
        site=SiteConfig(modules=["intel/2023.2"], env={"OMP_NUM_THREADS": "1"}),
        launcher=LauncherConfig(
            name="srun", kind="srun", command="srun", modules=["intelmpi/2023.2"]
        ),
        sim=SimulatorConfig(name="emses", adapter="emses", modules=["hdf5/1.12"]),
        program=["/opt/bin/mpiemses3D", "input/plasma.toml"],
        prelude=["rm -f work/*_0000.h5"],
    )
    _check("mpi_standard.sh", text)


def test_openmp_rsc() -> None:
    text = render_job_script(
        run_dir=RUN_DIR,
        run_id="R20261015-0001",
        job={
            "partition": "gr20001a",
            "processes": 1,
            "threads": 112,
            "cores": 112,
            "walltime": "48:00:00",
            "pre_commands": [
                "export OMP_NUM_THREADS=${SLURM_DPC_CPUS:-112}",
                "export OMP_PROC_BIND=spread",
            ],
        },
        site=SiteConfig(
            name="camphor",
            resource_style="rsc",
            modules=["intel/2023.2"],
            stdout="stdout.%J.log",
            stderr="stderr.%J.log",
        ),
        launcher=LauncherConfig(name="omp", kind="none"),
        sim=SimulatorConfig(name="beach", adapter="beach"),
        program=["/proj/.runops/build/beach-abc/bin/beach", "input/beach.toml"],
        venv_activate=Path("/work/proj/.venv/bin/activate"),
    )
    _check("openmp_rsc.sh", text)


def test_bad_walltime() -> None:
    with pytest.raises(UsageError):
        render_job_script(
            run_dir=RUN_DIR,
            run_id="R1",
            job={"walltime": "12h"},
            site=SiteConfig(),
            launcher=LauncherConfig(name="srun"),
            sim=SimulatorConfig(name="s", adapter="s"),
            program=["a"],
        )
