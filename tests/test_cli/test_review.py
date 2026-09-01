"""CLI tests for canonical terminal Run review."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from runops.cli.main import app
from runops.core.manifest import ManifestData, read_manifest, write_manifest
from runops.core.run.curation import has_valid_run_review

if TYPE_CHECKING:
    import pytest

runner = CliRunner()


def test_review_resolves_run_id_and_writes_complete_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "runops.toml").write_text(
        '[project]\nname = "review-test"\n',
        encoding="utf-8",
    )
    run_id = "R20260901-0001"
    run_dir = tmp_path / "runs" / "case" / run_id
    write_manifest(
        run_dir,
        ManifestData(
            run={"id": run_id, "status": "completed"},
            curation={"review_status": "unreviewed"},
        ),
    )
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app,
        [
            "runs",
            "review",
            run_id,
            "--reason",
            "Checked terminal diagnostics.",
            "--reviewed-by",
            "operator",
        ],
    )

    assert result.exit_code == 0, result.output
    assert f"Reviewed {run_id} at " in result.output
    curation = read_manifest(run_dir).curation
    assert curation["reviewed_by"] == "operator"
    assert curation["reason"] == "Checked terminal diagnostics."
    assert has_valid_run_review(curation)
