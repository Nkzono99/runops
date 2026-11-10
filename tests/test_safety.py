"""Concurrent and failure paths: duplicate submits, purge without keep rules,
nested runs, id reuse after delete, and `new --from` after the case changed."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from runops.adapters.generic import GenericAdapter
from runops.errors import UsageError
from runops.manifest import Manifest
from runops.ops.submit import submit_run
from runops.project import Project


def _manifest(project_dir: Path, run_id: str) -> Manifest:
    return Project.open(project_dir).resolve_run(run_id)


def _sbatch_calls(fake_slurm) -> int:  # type: ignore[no-untyped-def]
    return sum(1 for c in fake_slurm.commands if c[0] == "sbatch")


def test_same_run_twice_submits_once(project_dir: Path, cli, fake_slurm) -> None:  # type: ignore[no-untyped-def]
    (run_id,) = cli("new", "demo").run_ids()
    run_dir = str(_manifest(project_dir, run_id).run_dir)
    res = cli("submit", run_id, run_dir, run_id, "-y")
    assert res.code == 0, res.err
    assert _sbatch_calls(fake_slurm) == 1
    m = _manifest(project_dir, run_id)
    assert [a["job_id"] for a in m.job["attempts"]] == [m.job_id]


def test_stale_manifest_is_reloaded_before_submit(project: Project, cli, fake_slurm) -> None:  # type: ignore[no-untyped-def]
    (run_id,) = cli("new", "demo").run_ids()
    first = project.resolve_run(run_id)
    stale = project.resolve_run(run_id)
    submit_run(project, first, runner=fake_slurm)
    with pytest.raises(UsageError, match="is submitted"):
        submit_run(project, stale, runner=fake_slurm)
    assert _sbatch_calls(fake_slurm) == 1
    assert len(project.resolve_run(run_id).job["attempts"]) == 1


def test_concurrent_submits_sbatch_once(project: Project, cli, fake_slurm) -> None:  # type: ignore[no-untyped-def]
    (run_id,) = cli("new", "demo").run_ids()
    copies = [project.resolve_run(run_id) for _ in range(4)]
    barrier = threading.Barrier(len(copies))
    errors: list[Exception] = []

    def worker(m: Manifest) -> None:
        barrier.wait()
        try:
            submit_run(project, m, runner=fake_slurm)
        except UsageError as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(m,)) for m in copies]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert _sbatch_calls(fake_slurm) == 1
    assert len(errors) == len(copies) - 1


def test_purge_refuses_when_adapter_fails(
    project_dir: Path, cli, fake_slurm, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    (run_id,) = cli("new", "demo", "--submit").run_ids()
    fake_slurm.states[fake_slurm.last_job] = "COMPLETED"
    cli("sync")
    work = _manifest(project_dir, run_id).run_dir / "work"
    (work / "checkpoint.h5").write_text("keep me")
    (work / "big.dat").write_text("x")

    def broken(*_args: object) -> object:
        raise UsageError("adapter 'generic' could not be imported")

    monkeypatch.setattr("runops.ops.tidy.run_sim_context", broken)
    res = cli("tidy", "--purge-work", run_id, "-y")
    assert res.code == 2
    assert "nothing was deleted" in res.err
    assert (work / "checkpoint.h5").exists() and (work / "big.dat").exists()
    assert not _manifest(project_dir, run_id).data["storage"]["work_purged_at"]


def test_dest_inside_a_run_is_refused(project_dir: Path, cli) -> None:  # type: ignore[no-untyped-def]
    (run_id,) = cli("new", "demo").run_ids()
    run_dir = _manifest(project_dir, run_id).run_dir
    for dest in (str(run_dir), str(run_dir / "analysis" / "sub")):
        res = cli("new", "demo", "--dest", dest)
        assert res.code == 2 and "inside the run" in res.err


def test_delete_refuses_nested_run(project_dir: Path, cli) -> None:  # type: ignore[no-untyped-def]
    (outer,) = cli("new", "demo", "--scratch").run_ids()
    (inner,) = cli("new", "demo", "--scratch").run_ids()
    outer_dir = _manifest(project_dir, outer).run_dir
    inner_dir = _manifest(project_dir, inner).run_dir
    inner_dir.rename(outer_dir / "analysis" / inner_dir.name)  # moved in by hand
    res = cli("delete", outer, "-y")
    assert res.code == 2 and "contains another run" in res.err
    assert outer_dir.is_dir()


def test_deleted_id_is_not_reused(project_dir: Path, cli) -> None:  # type: ignore[no-untyped-def]
    (first,) = cli("new", "demo", "--scratch").run_ids()
    assert cli("delete", first, "-y").code == 0
    (second,) = cli("new", "demo").run_ids()
    assert second != first
    assert int(second[-4:]) == int(first[-4:]) + 1


def test_ids_survive_lost_counter(project_dir: Path, cli) -> None:  # type: ignore[no-untyped-def]
    (first,) = cli("new", "demo").run_ids()
    (project_dir / ".runops/last_run_id").unlink()
    (second,) = cli("new", "demo").run_ids()
    assert int(second[-4:]) == int(first[-4:]) + 1


def test_new_from_warns_when_case_inputs_changed(project_dir: Path, cli) -> None:  # type: ignore[no-untyped-def]
    (src,) = cli("new", "demo", "--set", "x=5").run_ids()
    res = cli("new", "--from", src, "--set", "name=b")
    assert res.code == 0 and "input files changed" not in res.err
    (project_dir / "cases/demo/input.txt").write_text("x = {{ x }}\nname = {{ name }}\nnew = 1\n")
    res = cli("new", "--from", src, "--set", "name=c")
    assert res.code == 0
    assert "input files changed" in res.err and src in res.err
    assert "input.txt" in res.err  # a file that is not TOML is named as a whole


def _toml_case(project_dir: Path, text: str) -> None:
    (project_dir / "cases/demo/input.toml").write_text(text)


def test_new_from_lists_the_input_keys_the_case_changed(project_dir: Path, cli) -> None:  # type: ignore[no-untyped-def]
    base = "[plasma]\nn = {{ plasma.n }}\n[[species]]\nt = 0.1\n[[species]]\nt = 2.0\n"
    _toml_case(project_dir, base)
    (src,) = cli("new", "demo", "--set", "plasma.n=1").run_ids()
    _toml_case(project_dir, base.replace("t = 0.1", "t = 10.0") + "[extra]\nn = 1\n")
    res = cli("new", "--from", src, "--set", "plasma.n=2")
    assert res.code == 0
    assert "species.0.t: 0.1 -> 10.0" in res.err
    assert "extra.n: - -> 1" in res.err
    assert "plasma.n:" not in res.err  # --set is listed with the params, not as a surprise


def test_new_from_is_quiet_when_a_case_edit_changes_no_input_value(project_dir: Path, cli) -> None:  # type: ignore[no-untyped-def]
    _toml_case(project_dir, "t = 0.1\n")
    (src,) = cli("new", "demo").run_ids()
    _toml_case(project_dir, "# a comment about t\nt = 0.1\n")
    res = cli("new", "--from", src)
    assert res.code == 0 and "input files changed" not in res.err


def test_new_from_shows_the_first_input_changes_and_counts_the_rest(project_dir: Path, cli) -> None:  # type: ignore[no-untyped-def]
    _toml_case(project_dir, "".join(f"k{i:02d} = 0\n" for i in range(13)))
    (src,) = cli("new", "demo").run_ids()
    _toml_case(project_dir, "".join(f"k{i:02d} = 1\n" for i in range(13)))
    res = cli("new", "--from", src)
    assert "k09: 0 -> 1" in res.err and "k10" not in res.err and "and 3 more" in res.err


def test_continue_leaves_out_the_keys_the_adapter_writes(  # type: ignore[no-untyped-def]
    project_dir: Path, cli, monkeypatch: pytest.MonkeyPatch
) -> None:
    def extend_inputs(self, src_run: Path, run_dir: Path, params: dict) -> list[str]:  # type: ignore[no-untyped-def]
        path = run_dir / "input" / "input.toml"
        path.write_text(path.read_text() + f'[restart]\nfrom = "{src_run.name}"\n')
        return ["input/input.toml"]

    monkeypatch.setattr(GenericAdapter, "extend_inputs", extend_inputs, raising=False)
    _toml_case(project_dir, "t = 0.1\n")
    (src,) = cli("new", "demo").run_ids()
    _toml_case(project_dir, "t = 10.0\n")
    res = cli("new", "--from", src, "--continue")
    assert res.code == 0
    assert "t: 0.1 -> 10.0" in res.err and "restart.from" not in res.err


def test_sync_reports_setup_failure(project_dir: Path, cli, fake_slurm) -> None:  # type: ignore[no-untyped-def]
    (run_id,) = cli("new", "demo", "--submit").run_ids()
    m = _manifest(project_dir, run_id)
    fake_slurm.unknown.add(m.job_id)
    (m.run_dir / "submit" / f"exit.{m.job_id}").write_text(
        'exit_code = 127\nstarted_at = ""\nfinished_at = ""\nhostname = "n1"\nstage = "setup"\n'
    )
    (result,) = json.loads(cli("sync", "--json").out)
    assert result["after"] == "failed"
    assert "setup failed" in result["message"]
