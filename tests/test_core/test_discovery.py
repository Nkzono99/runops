"""Tests for core discovery module."""

from __future__ import annotations

from pathlib import Path

import pytest
import tomli_w

from runops.core.discovery import (
    RunDiscoveryError,
    check_run_id_uniqueness,
    collect_existing_run_ids,
    discover_active_runs,
    discover_active_runs_checked,
    discover_runs,
    discover_runs_checked,
    resolve_run,
    validate_uniqueness,
)
from runops.core.exceptions import DuplicateRunIdError, RunNotFoundError


def _make_run(
    runs_dir: Path,
    *path_parts: str,
    run_id: str = "R20260327-0001",
    status: str = "created",
) -> Path:
    """Helper to create a run directory with manifest.toml."""
    run_dir = runs_dir.joinpath(*path_parts)
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"run": {"id": run_id, "status": status}}
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

    def test_unpublished_staging_directories_are_never_discovered(
        self, tmp_path: Path
    ) -> None:
        runs_dir = tmp_path / "runs"
        published = _make_run(runs_dir, "survey", "R1", run_id="R1")
        _make_run(runs_dir, "survey", ".tmp-R2", run_id="R2")
        _make_run(runs_dir, "survey", ".delete-R3", run_id="R3")

        assert discover_runs(runs_dir) == [published.resolve()]
        assert discover_active_runs(runs_dir) == [published.resolve()]
        assert collect_existing_run_ids(runs_dir) == {"R1"}

    def test_active_discovery_prunes_archive_roots_and_bundle_markers(
        self, tmp_path: Path
    ) -> None:
        runs_dir = tmp_path / "runs"
        active = _make_run(runs_dir, "survey", "active", run_id="R20260327-0001")
        archived = _make_run(
            runs_dir,
            "_archive",
            "old-survey",
            "archived",
            run_id="R20260327-0002",
        )
        bundle = runs_dir / "moved-bundle"
        bundled = _make_run(bundle, "failed", run_id="R20260327-0003")
        (bundle / ".runops-archive.toml").write_text(
            '[bundle]\narchived_from = "runs/survey"\n', encoding="utf-8"
        )

        assert discover_active_runs(runs_dir) == [active.resolve()]
        assert discover_runs(runs_dir) == sorted(
            [active.resolve(), archived.resolve(), bundled.resolve()]
        )

    def test_active_discovery_excludes_in_place_inactive_states(
        self, tmp_path: Path
    ) -> None:
        runs_dir = tmp_path / "runs"
        active = _make_run(runs_dir, "active", run_id="R20260327-0001")
        _make_run(
            runs_dir,
            "archived",
            run_id="R20260327-0002",
            status="archived",
        )
        _make_run(
            runs_dir,
            "purged",
            run_id="R20260327-0003",
            status="purged",
        )

        assert discover_active_runs(runs_dir) == [active.resolve()]

    def test_checked_discovery_rejects_symlink_namespace_subtree(
        self, tmp_path: Path
    ) -> None:
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        (runs_dir / "hidden").symlink_to(outside, target_is_directory=True)

        with pytest.raises(RunDiscoveryError, match="symbolic link"):
            discover_runs_checked(runs_dir)

    def test_checked_discovery_surfaces_walk_errors(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from runops.core import discovery as discovery_module

        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()

        def fail_walk(*args: object, **kwargs: object) -> list[object]:
            onerror = kwargs["onerror"]
            assert callable(onerror)
            onerror(OSError("unreadable subtree"))
            return []

        monkeypatch.setattr(discovery_module.os, "walk", fail_walk)

        with pytest.raises(RunDiscoveryError, match="unreadable subtree"):
            discover_runs_checked(runs_dir)

    def test_checked_active_discovery_rejects_corrupt_archive_marker(
        self, tmp_path: Path
    ) -> None:
        runs_dir = tmp_path / "runs"
        bundle = runs_dir / "bundle"
        _make_run(bundle, "R20260327-0001")
        (bundle / ".runops-archive.toml").write_text("[bundle\n", encoding="utf-8")

        with pytest.raises(RunDiscoveryError, match="Invalid archive marker"):
            discover_active_runs_checked(runs_dir)


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

    def test_identity_operations_still_include_archived_runs(
        self, tmp_path: Path
    ) -> None:
        runs_dir = tmp_path / "runs"
        _make_run(runs_dir, "active", run_id="R20260327-0001")
        archived = _make_run(
            runs_dir,
            "_archive",
            "old-survey",
            "archived",
            run_id="R20260327-0002",
            status="archived",
        )

        assert collect_existing_run_ids(runs_dir) == {
            "R20260327-0001",
            "R20260327-0002",
        }
        assert resolve_run("R20260327-0002", runs_dir) == archived.resolve()
