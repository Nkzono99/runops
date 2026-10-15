"""Acceptance 9: migrate-v1 on a reduced copy of a real v1 project."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from runops.project import Project
from runops.util import load_toml

FIXTURE = Path(__file__).parent / "fixtures" / "v1-project"


@pytest.fixture
def v1_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "v1"
    shutil.copytree(FIXTURE, root)
    for path in root.rglob("*.toml"):
        path.write_text(path.read_text().replace("@ROOT@", str(root)))
    monkeypatch.chdir(root)
    monkeypatch.setenv("COLUMNS", "250")
    return root


def _snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_dry_run_changes_nothing(v1_root: Path, cli) -> None:  # type: ignore[no-untyped-def]
    before = _snapshot(v1_root)
    res = cli("migrate-v1", "--dry-run")
    assert res.code == 0, res.err
    assert "manifests to convert: 4" in res.out
    assert "cases/beach/plane -> cases/plane" in res.out
    assert ".runops/work/beach-x-abc -> .runops/build/beach-x-abc" in res.out
    assert "adapters/beach.py" in res.out
    assert _snapshot(v1_root) == before


def test_apply(v1_root: Path, cli) -> None:  # type: ignore[no-untyped-def]
    res = cli("migrate-v1", "-y")
    assert res.code == 0, res.err

    config = load_toml(v1_root / "runops.toml")
    assert config["schema"] == 2
    assert config["project"]["name"] == "fixture_v1"
    assert config["site"]["resource_style"] == "rsc"
    assert config["launchers"]["camphor"] == {"kind": "srun", "use_slurm_ntasks": True}
    assert config["defaults"]["launcher"] == "camphor"
    assert config["simulators"]["beach"]["modules"] == ["hdf5/x"]
    assert (
        config["simulators"]["beach_patched"]["executable"] == ".runops/build/beach-x-abc/bin/beach"
    )
    assert "codex_plugins" not in config["simulators"]["beach_patched"]
    assert (v1_root / ".runops/build/beach-x-abc/bin/beach").is_file()
    assert not (v1_root / ".runops/work/beach-x-abc").exists()

    backups = list((v1_root / ".runops/v1-backup").iterdir())
    assert len(backups) == 1
    for name in (
        "simulators.toml",
        "site.toml",
        "AGENTS.md",
        ".codex/rules/a.md",
        "runs/AGENTS.md",
    ):
        assert (backups[0] / name).exists(), name
    assert not (v1_root / "runs/AGENTS.md").exists()
    assert "<!-- runops:begin -->" in (v1_root / "AGENTS.md").read_text()
    assert (v1_root / "CLAUDE.md").read_text() == "@AGENTS.md\n"

    case = (v1_root / "cases/plane/case.toml").read_text()
    assert "[classification]" not in case and "# keep this comment" in case
    assert load_toml(v1_root / "cases/plane/case.toml")["case"]["tags"] == ["sheath", "plane", "2d"]
    assert not (v1_root / "cases/beach").exists()
    assert (v1_root / "adapters/beach.py").is_file()
    assert (v1_root / "research/CURRENT.md").is_file()
    assert (v1_root / ".runops/test-runs/T20260701-0001").is_dir()
    assert "research" in (v1_root / "notes/README.md").read_text()
    assert "migrated to runops v2" in (v1_root / "LOG.md").read_text()

    project = Project.open(v1_root)
    done = project.resolve_run("R20260701-0001")
    assert (done.run_dir / "manifest.v1.toml").is_file()
    assert done.label == "a" and done.why == "explore" and done.pinned
    assert done.params == {"sim.batch_count": 20}
    assert done.tags == ["sheath", "plane", "2d"]
    assert done.data["path"]["run_dir"] == "runs/plane/R20260701-0001--a"
    assert "queue" not in done.job and done.job["attempts"][0]["job_id"] == "100"

    scan = project.resolve_run("R20260701-0002")
    assert scan.sweep == "scan"
    assert scan.section("simulator")["executable"] == str(
        v1_root / ".runops/build/beach-x-abc/bin/beach"
    )

    bundled = project.resolve_run("R20260601-0001")
    assert bundled.status.value == "archived"
    assert bundled.data["path"]["archived_from"] == "runs/plane/R20260601-0001"
    purged = project.resolve_run("R20260702-0001")
    assert purged.status.value == "archived"
    assert purged.data["storage"]["work_purged_at"] == "2026-07-10T00:00:00+00:00"

    rows = json.loads(cli("list", "--all", "--archived", "--json").out)
    assert {r["id"] for r in rows} == {
        "R20260701-0001",
        "R20260701-0002",
        "R20260601-0001",
        "R20260702-0001",
    }
    res = cli("doctor")
    assert "adapter 'beach' resolved via project-local" in res.out

    # the migrated project keeps working
    res = cli("new", "plane", "--set", "sim.batch_count=30", "--why", "after migration")
    assert res.code == 0, res.err
    (new_id,) = res.run_ids()
    new = project.resolve_run(new_id)
    assert load_toml(new.run_dir / "input/beach.toml")["sim"]["batch_count"] == 30
    assert "--rsc p=1:t=8:c=8" in (new.run_dir / "submit/job.sh").read_text()

    # restore of the bundle-archived run goes back to its original place
    assert cli("restore", "R20260601-0001").code == 0
    assert (v1_root / "runs/plane/R20260601-0001/manifest.toml").is_file()

    res = cli("migrate-v1", "--dry-run")
    assert res.code == 2 and "already a runops v2 project" in res.err


def test_apply_deletes_test_runs_on_request(v1_root: Path, cli) -> None:  # type: ignore[no-untyped-def]
    assert cli("migrate-v1", "-y", "--apply-delete-test-runs").code == 0
    assert not (v1_root / ".runops/test-runs/T20260701-0001").exists()
