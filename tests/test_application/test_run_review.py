"""Terminal Run review contract tests."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from runops.application.run_review import RunReviewError, review_run
from runops.core.manifest import ManifestData, read_manifest, write_manifest
from runops.core.run.curation import has_valid_run_review


def _write_run(root: Path, *, status: str) -> Path:
    run_dir = root / "runs" / "case" / "R20260901-0001"
    write_manifest(
        run_dir,
        ManifestData(
            run={"id": "R20260901-0001", "status": status},
            curation={"review_status": "unreviewed", "legacy_note": "keep"},
        ),
    )
    return run_dir


def test_review_terminal_run_writes_complete_record_and_preserves_unknown_fields(
    tmp_path: Path,
) -> None:
    run_dir = _write_run(tmp_path, status="completed")
    now = datetime(2026, 9, 1, 12, 30, tzinfo=timezone.utc)

    result = review_run(
        run_dir,
        reason="  Diagnostics and outputs checked.  ",
        reviewed_by="  operator  ",
        now=now,
    )

    manifest = read_manifest(run_dir)
    assert result.reason == "Diagnostics and outputs checked."
    assert result.reviewed_by == "operator"
    assert result.reviewed_at == "2026-09-01T12:30:00+00:00"
    assert manifest.curation["legacy_note"] == "keep"
    assert manifest.curation["review_status"] == "reviewed"
    assert manifest.curation["reviewed_at"] == result.reviewed_at
    assert manifest.curation["reviewed_by"] == "operator"
    assert manifest.curation["reason"] == result.reason
    assert has_valid_run_review(manifest.curation)


@pytest.mark.parametrize("status", ["created", "submitted", "running"])
def test_review_rejects_nonterminal_run_without_mutation(
    tmp_path: Path,
    status: str,
) -> None:
    run_dir = _write_run(tmp_path, status=status)
    before = (run_dir / "manifest.toml").read_bytes()

    with pytest.raises(RunReviewError, match="not reviewable"):
        review_run(run_dir, reason="Too early.")

    assert (run_dir / "manifest.toml").read_bytes() == before


def test_review_rejects_empty_reason_without_mutation(tmp_path: Path) -> None:
    run_dir = _write_run(tmp_path, status="completed")
    before = (run_dir / "manifest.toml").read_bytes()

    with pytest.raises(RunReviewError, match="non-empty reason"):
        review_run(run_dir, reason="   ")

    assert (run_dir / "manifest.toml").read_bytes() == before
