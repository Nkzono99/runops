"""Per-run [job]: `--job` overrides and `new --from` inheriting the source's resources."""

from __future__ import annotations

import json
from pathlib import Path

from runops.manifest import Manifest
from runops.project import Project


def _manifest(project_dir: Path, run_id: str) -> Manifest:
    return Project.open(project_dir).resolve_run(run_id)


def _set_case_walltime(project_dir: Path, walltime: str) -> None:
    case = project_dir / "cases/demo/case.toml"
    text = case.read_text()
    case.write_text(text.replace('walltime = "1:00:00"', f'walltime = "{walltime}"'))


def test_job_override_on_new_and_sweep(project_dir: Path, cli) -> None:  # type: ignore[no-untyped-def]
    res = cli("new", "demo", "--job", "walltime=72:00:00", "--job", "processes=8", "--why", "w")
    assert res.code == 0, res.err
    (run_id,) = res.run_ids()
    m = _manifest(project_dir, run_id)
    assert m.job["walltime"] == "72:00:00" and m.job["processes"] == 8
    assert m.section("variation")["job_changed_keys"] == ["walltime", "processes"]
    assert "job vs case: walltime 1:00:00 -> 72:00:00" in res.out
    assert "#SBATCH" in (m.run_dir / "submit/job.sh").read_text()
    assert "72:00:00" in (m.run_dir / "submit/job.sh").read_text()

    preview = json.loads(
        cli("sweep", "demo", "--set", "x=1,2", "--job", "walltime=2:00:00", "--json").out
    )
    assert preview["job"]["walltime"] == "2:00:00"
    res = cli("sweep", "demo", "--set", "x=1,2", "--job", "walltime=2:00:00", "--apply")
    assert all(_manifest(project_dir, r).job["walltime"] == "2:00:00" for r in res.run_ids())

    (quoted,) = cli("new", "demo", "--job", 'walltime="12:00:00"').run_ids()
    assert _manifest(project_dir, quoted).job["walltime"] == "12:00:00"
    res = cli("new", "demo", "--job", "colour=red")
    assert res.code == 2 and "not a job key" in res.err


def test_new_from_inherits_source_job(project_dir: Path, cli) -> None:  # type: ignore[no-untyped-def]
    (src,) = cli("new", "demo", "--job", "walltime=72:00:00", "--set", "x=1").run_ids()
    _set_case_walltime(project_dir, "3:00:00")
    case = project_dir / "cases/demo/case.toml"
    case.write_text(case.read_text().replace("ntasks = 4", 'ntasks = 4\nqos = "high"'))

    res = cli("new", "--from", src, "--set", "x=2", "--why", "next x")
    assert res.code == 0, res.err
    (derived,) = res.run_ids()
    assert _manifest(project_dir, derived).job["walltime"] == "72:00:00"
    assert _manifest(project_dir, derived).job["qos"] == "high"  # only the case has it
    assert f"params vs {src}: x 1 -> 2" in res.out
    assert f"job vs {src}: qos - -> high" in res.out
    summary = json.loads(cli("status", derived, "--json").out)[0]
    assert summary["resources"]["walltime"] == "72:00:00"

    res = cli("new", "--from", src, "--job", "walltime=96:00:00")
    (longer,) = res.run_ids()
    assert _manifest(project_dir, longer).job["walltime"] == "96:00:00"
    assert f"job vs {src}: walltime 72:00:00 -> 96:00:00" in res.out

    (from_case,) = cli("new", "--from", src, "--job-from-case").run_ids()
    assert _manifest(project_dir, from_case).job["walltime"] == "3:00:00"
    res = cli("new", "demo", "--job-from-case")
    assert res.code == 2 and "needs --from" in res.err
