"""Tests for analysis-readiness evaluation."""

from __future__ import annotations

from pathlib import Path

import tomli_w

from runops.application.execution.readiness import evaluate_run_readiness
from tests.factories import create_run_manifest


def _create_emses_run(
    tmp_path: Path,
    *,
    status: str = "completed",
    final_step: bool = True,
    hdf5: bool = False,
) -> Path:
    run_dir = tmp_path / "runs" / "R20260507-0001"
    create_run_manifest(
        run_dir,
        status=status,
        simulator_name="emses",
        adapter="emses",
    )
    (run_dir / "input").mkdir(parents=True, exist_ok=True)
    (run_dir / "work").mkdir(parents=True, exist_ok=True)
    with (run_dir / "input" / "plasma.toml").open("wb") as f:
        tomli_w.dump({"jobcon": {"nstep": 100}}, f)
    last_step = 100 if final_step else 50
    (run_dir / "work" / "energy").write_text(
        f"{last_step} 1.0 2.0\n",
        encoding="utf-8",
    )
    if hdf5:
        (run_dir / "work" / "ex00_0000.h5").write_bytes(b"")
    return run_dir


def test_completed_emses_run_with_required_hdf5_is_ready(tmp_path: Path) -> None:
    run_dir = _create_emses_run(tmp_path, hdf5=True)

    readiness = evaluate_run_readiness(run_dir)

    assert readiness.analysis_ready is True
    assert readiness.analysis_status == "ready"
    assert readiness.missing_required_artifacts == ()
    assert readiness.to_dict()["checks"][0]["key"] == "hdf5_fields"


def test_completed_emses_run_missing_hdf5_is_incomplete(tmp_path: Path) -> None:
    run_dir = _create_emses_run(tmp_path, hdf5=False)

    readiness = evaluate_run_readiness(run_dir)

    assert readiness.analysis_ready is False
    assert readiness.analysis_status == "incomplete"
    assert readiness.missing_required_artifacts == ("hdf5_fields",)
    assert any("Missing required artifact" in warning for warning in readiness.warnings)


def test_completed_emses_run_before_final_step_is_incomplete(tmp_path: Path) -> None:
    run_dir = _create_emses_run(tmp_path, final_step=False, hdf5=True)

    readiness = evaluate_run_readiness(run_dir)

    assert readiness.analysis_ready is False
    assert readiness.simulator_status == "running"
    assert readiness.missing_required_artifacts == ()
    assert any("Adapter status" in warning for warning in readiness.warnings)


def test_non_completed_run_is_not_checked_for_analysis_readiness(
    tmp_path: Path,
) -> None:
    run_dir = _create_emses_run(tmp_path, status="running", hdf5=True)

    readiness = evaluate_run_readiness(run_dir)

    assert readiness.analysis_ready is False
    assert readiness.analysis_status == "not_completed"
    assert readiness.warnings == ()


def test_unknown_adapter_reports_unknown_readiness(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "R20260507-0002"
    create_run_manifest(run_dir, status="completed", adapter="not_registered")

    readiness = evaluate_run_readiness(run_dir)

    assert readiness.analysis_ready is False
    assert readiness.analysis_status == "unknown"
    assert readiness.warnings == ("Unknown simulator adapter: not_registered.",)
