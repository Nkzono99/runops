"""Tests for publication export helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import tomli_w

from runops.core.publication import (
    PublicationSourceArtifact,
    export_publication_bundle,
)
from runops.core.publication.files import (
    materialize_export_files as _materialize_export_files,
)


def _write_manifest(run_dir: Path, data: dict[str, Any]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    with open(run_dir / "manifest.toml", "wb") as f:
        tomli_w.dump(data, f)


def _create_project(project_root: Path) -> None:
    (project_root / "runops.toml").write_text(
        '[project]\nname = "publication-project"\n',
        encoding="utf-8",
    )


def _create_completed_run(run_root: Path, run_id: str) -> Path:
    run_dir = run_root / run_id
    _write_manifest(
        run_dir,
        {
            "run": {
                "id": run_id,
                "status": "completed",
            },
            "origin": {
                "case": "cases/example",
            },
            "simulator": {
                "name": "test_sim",
                "adapter": "generic",
            },
            "launcher": {
                "name": "srun",
            },
            "classification": {
                "tags": ["baseline"],
            },
        },
    )
    analysis_dir = run_dir / "analysis"
    figure_path = analysis_dir / "figures" / "phi.png"
    figure_path.parent.mkdir(parents=True, exist_ok=True)
    figure_path.write_text("fake image", encoding="utf-8")
    with open(analysis_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "energy": 42.0,
                "figures": [
                    {
                        "path": "figures/phi.png",
                        "caption": "phi",
                    }
                ],
            },
            f,
        )
    return run_dir


def test_export_publication_bundle_supports_symlink_mode(tmp_path: Path) -> None:
    """Symlink mode exports files as relative symlinks inside the bundle."""
    _create_project(tmp_path)
    run_dir = _create_completed_run(tmp_path / "runs", "R20260424-0001")

    try:
        result = export_publication_bundle(
            run_dir,
            paper_id="draft-a",
            name="baseline",
            mode="symlink",
        )
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    assert result.export_dir == tmp_path / "exports" / "papers" / "draft-a" / "baseline"
    exported_summary = (
        result.export_dir
        / "files"
        / "runs"
        / "R20260424-0001"
        / "analysis"
        / "summary.json"
    )
    exported_figure = (
        result.export_dir
        / "files"
        / "runs"
        / "R20260424-0001"
        / "analysis"
        / "figures"
        / "phi.png"
    )
    assert exported_summary.is_symlink()
    assert exported_figure.is_symlink()
    assert exported_summary.resolve() == run_dir / "analysis" / "summary.json"
    assert exported_figure.resolve() == run_dir / "analysis" / "figures" / "phi.png"


def test_export_manifest_separates_execution_and_paper_status(
    tmp_path: Path,
) -> None:
    _create_project(tmp_path)
    run_dir = _create_completed_run(tmp_path / "runs", "R20260507-0001")
    (run_dir / "work").mkdir(exist_ok=True)
    (run_dir / "work" / "exit_code").write_text("0", encoding="utf-8")

    result = export_publication_bundle(
        run_dir,
        paper_id="draft-a",
        name="placeholder",
        paper_status="placeholder",
    )

    with open(result.manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    run_record = manifest["source"]["run"]
    assert run_record["execution_status"] == "completed"
    assert run_record["status"] == "completed"
    assert run_record["analysis_status"] == "ready"
    assert run_record["paper_status"] == "placeholder"
    assert manifest["source"]["paper_status_counts"] == {"placeholder": 1}


def test_force_export_preserves_existing_bundle_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed forced export leaves the existing bundle untouched."""
    _create_project(tmp_path)
    run_dir = _create_completed_run(tmp_path / "runs", "R20260424-0001")
    export_dir = tmp_path / "exports" / "papers" / "draft-a" / "baseline"
    export_dir.mkdir(parents=True, exist_ok=True)
    sentinel = export_dir / "sentinel.txt"
    sentinel.write_text("keep me", encoding="utf-8")

    def fail_readme(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "runops.core.publication.workflow._write_export_readme",
        fail_readme,
    )

    with pytest.raises(RuntimeError, match="boom"):
        export_publication_bundle(
            run_dir,
            paper_id="draft-a",
            name="baseline",
            force=True,
        )

    assert sentinel.read_text(encoding="utf-8") == "keep me"
    assert export_dir.exists()
    assert not list(export_dir.parent.glob(".baseline.tmp-*"))


def test_materialize_export_files_preserves_duplicate_metadata_entries(
    tmp_path: Path,
) -> None:
    _create_project(tmp_path)
    source = tmp_path / "runs" / "R20260424-0001" / "analysis" / "figures" / "phi.png"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("fake image", encoding="utf-8")
    files_dir = tmp_path / "exports" / "files"

    exported = _materialize_export_files(
        [
            PublicationSourceArtifact(
                role="run_figure",
                source_path=source,
                run_id="R20260424-0001",
                caption="Run figure",
            ),
            PublicationSourceArtifact(
                role="survey_plot",
                source_path=source,
                caption="Survey plot reference",
            ),
        ],
        project_root=tmp_path,
        files_dir=files_dir,
        mode="copy",
    )

    assert len(exported) == 2
    assert exported[0].export_path == exported[1].export_path
    assert exported[0].caption == "Run figure"
    assert exported[1].caption == "Survey plot reference"
    assert exported[0].role == "run_figure"
    assert exported[1].role == "survey_plot"
    assert exported[0].export_path.is_file()
