"""Tests for retry suggestion helpers."""

from __future__ import annotations

from pathlib import Path

import tomli_w

from runops.core.retry import (
    assess_retry_for_run,
    get_attempt_count,
    suggest_retry,
    suggest_retry_for_run,
)


def _create_failed_run(
    run_dir: Path,
    *,
    failure_reason: str = "timeout",
    attempts: list[dict[str, str]] | None = None,
    attempt: int | None = None,
) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, object] = {
        "run": {
            "id": run_dir.name,
            "status": "failed",
            "failure_reason": failure_reason,
        },
        "job": {},
    }
    job = manifest["job"]
    assert isinstance(job, dict)
    if attempts is not None:
        job["attempts"] = attempts
    if attempt is not None:
        job["attempt"] = attempt

    with open(run_dir / "manifest.toml", "wb") as f:
        tomli_w.dump(manifest, f)


def test_get_attempt_count_prefers_attempts_history() -> None:
    count = get_attempt_count(
        {
            "attempt": 1,
            "attempts": [
                {"attempt": "1"},
                {"attempt": "2"},
            ],
        }
    )
    assert count == 2


def test_suggest_retry_for_run_respects_max_attempts_from_attempts_list(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "R20260330-0001"
    _create_failed_run(
        run_dir,
        attempts=[
            {"attempt": "1"},
            {"attempt": "2"},
            {"attempt": "3"},
        ],
    )

    suggestions = suggest_retry_for_run(run_dir)

    assert len(suggestions) == 1
    assert suggestions[0].action == "show_log"
    assert "Max attempts" in suggestions[0].rationale


def test_get_attempt_count_handles_scalar_and_job_metadata_fallbacks() -> None:
    assert get_attempt_count({"attempt": "2"}) == 2
    assert get_attempt_count({"attempt": "abc"}) == 0
    assert get_attempt_count({"job_id": "12345"}) == 1
    assert get_attempt_count({}) == 0


def test_suggest_retry_returns_known_and_unknown_reason_actions() -> None:
    timeout = suggest_retry("timeout", attempt=1)
    unknown = suggest_retry("mystery_failure", attempt=1)

    assert timeout[0].action == "retry_run"
    assert timeout[0].adjustments == {"walltime_factor": 1.5}
    assert unknown[0].action == "show_log"
    assert "Unknown failure reason" in unknown[0].rationale


def test_suggest_retry_for_run_returns_empty_for_non_failed_run(tmp_path: Path) -> None:
    run_dir = tmp_path / "R20260330-0002"
    run_dir.mkdir(parents=True, exist_ok=True)
    with open(run_dir / "manifest.toml", "wb") as f:
        tomli_w.dump(
            {
                "run": {
                    "id": "R20260330-0002",
                    "status": "completed",
                },
                "job": {},
            },
            f,
        )

    assert suggest_retry_for_run(run_dir) == []


def test_assess_retry_for_run_detects_partial_outputs(tmp_path: Path) -> None:
    run_dir = tmp_path / "R20260507-0001"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "work").mkdir()
    (run_dir / "work" / "ex00_0000.h5").write_bytes(b"")
    with open(run_dir / "manifest.toml", "wb") as f:
        tomli_w.dump(
            {
                "run": {
                    "id": "R20260507-0001",
                    "status": "failed",
                    "failure_reason": "timeout",
                },
                "job": {"attempt": 1},
                "simulator": {"name": "emses", "adapter": "emses"},
            },
            f,
        )

    assessment = assess_retry_for_run(run_dir)

    assert assessment.retry_status == "partial"
    assert assessment.has_partial_outputs is True
    assert assessment.partial_outputs == {"hdf5_fields": 1}
    assert "Partial outputs detected" in assessment.warnings[0]
