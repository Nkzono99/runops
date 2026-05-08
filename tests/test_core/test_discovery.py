"""Tests for core discovery module."""

from __future__ import annotations

from pathlib import Path

import pytest
import tomli_w

from runops.core.discovery import (
    check_run_id_uniqueness,
    collect_existing_run_ids,
    discover_runs,
    resolve_run,
    validate_uniqueness,
)
from runops.core.exceptions import DuplicateRunIdError, RunNotFoundError


def _make_run(runs_dir: Path, *path_parts: str, run_id: str = "R20260327-0001") -> Path:
    """Helper to create a run directory with manifest.toml."""
    run_dir = runs_dir.joinpath(*path_parts)
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"run": {"id": run_id, "status": "created"}}
    with open(run_dir / "manifest.toml", "wb") as f:
        tomli_w.dump(manifest, f)
    return run_dir


class TestDiscoverRuns:
    """Tests for discover_runs()."""

    def test_find_single_run(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs"
        _make_run(runs_dir, "survey1", "R20260327-0001")
        result = discover_runs(runs_dir)
        assert len(result) == 1

    def test_find_nested_runs(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs"
        _make_run(runs_dir, "cavity", "rect", "survey1", "R20260327-0001")
        _make_run(
            runs_dir,
            "cavity",
            "rect",
            "survey1",
            "R20260327-0002",
            run_id="R20260327-0002",
        )
        _make_run(
            runs_dir, "layer", "survey2", "R20260328-0001", run_id="R20260328-0001"
        )
        result = discover_runs(runs_dir)
        assert len(result) == 3

    def test_empty_dir(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        assert discover_runs(runs_dir) == []

    def test_nonexistent_dir(self, tmp_path: Path) -> None:
        assert discover_runs(tmp_path / "nonexistent") == []

    def test_sorted_results(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs"
        _make_run(runs_dir, "b", "R2", run_id="R2")
        _make_run(runs_dir, "a", "R1", run_id="R1")
        result = discover_runs(runs_dir)
        assert result == sorted(result)


class TestCheckRunIdUniqueness:
    """Tests for check_run_id_uniqueness()."""

    def test_all_unique(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs"
        _make_run(runs_dir, "R1", run_id="R20260327-0001")
        _make_run(runs_dir, "R2", run_id="R20260327-0002")
        assert check_run_id_uniqueness(runs_dir) == []

    def test_duplicates_found(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs"
        _make_run(runs_dir, "survey1", "R1", run_id="R20260327-0001")
        _make_run(runs_dir, "survey2", "R2", run_id="R20260327-0001")
        dups = check_run_id_uniqueness(runs_dir)
        assert "R20260327-0001" in dups


class TestValidateUniqueness:
    """Tests for validate_uniqueness()."""

    def test_passes_when_unique(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs"
        _make_run(runs_dir, "R1", run_id="R20260327-0001")
        validate_uniqueness(runs_dir)  # Should not raise

    def test_raises_on_duplicate(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs"
        _make_run(runs_dir, "a", "R1", run_id="R20260327-0001")
        _make_run(runs_dir, "b", "R2", run_id="R20260327-0001")
        with pytest.raises(DuplicateRunIdError, match="R20260327-0001"):
            validate_uniqueness(runs_dir)


class TestResolveRun:
    """Tests for resolve_run()."""

    def test_resolve_by_run_id(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs"
        run_dir = _make_run(runs_dir, "survey1", "R20260327-0001")
        result = resolve_run("R20260327-0001", runs_dir)
        assert result == run_dir.resolve()

    def test_resolve_by_absolute_path(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs"
        run_dir = _make_run(runs_dir, "survey1", "R20260327-0001")
        result = resolve_run(str(run_dir), runs_dir)
        assert result == run_dir.resolve()

    def test_not_found_by_id(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        with pytest.raises(RunNotFoundError):
            resolve_run("R20260327-9999", runs_dir)

    def test_duplicate_run_id_is_ambiguous(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs"
        _make_run(runs_dir, "a", "R1", run_id="R20260327-0001")
        _make_run(runs_dir, "b", "R2", run_id="R20260327-0001")
        with pytest.raises(DuplicateRunIdError, match="R20260327-0001"):
            resolve_run("R20260327-0001", runs_dir)

    def test_not_found_by_path(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        with pytest.raises(RunNotFoundError):
            resolve_run("/nonexistent/path", runs_dir)


class TestCollectExistingRunIds:
    """Tests for collect_existing_run_ids()."""

    def test_collects_ids(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs"
        _make_run(runs_dir, "R1", run_id="R20260327-0001")
        _make_run(runs_dir, "R2", run_id="R20260327-0002")
        ids = collect_existing_run_ids(runs_dir)
        assert ids == {"R20260327-0001", "R20260327-0002"}

    def test_empty_dir(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        assert collect_existing_run_ids(runs_dir) == set()
