"""Tests for core manifest module."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from runops.core.exceptions import ManifestError, ManifestNotFoundError
from runops.core.manifest import (
    ManifestData,
    read_manifest,
    update_manifest,
    write_manifest,
)

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


class TestManifestData:
    """Tests for ManifestData dataclass."""

    def test_to_dict_roundtrip(self) -> None:
        data = ManifestData(
            run={"id": "R20260327-0001", "status": "created"},
            origin={"case": "test"},
            params_snapshot={"nx": 64},
        )
        d = data.to_dict()
        restored = ManifestData.from_dict(d)
        assert restored.run == data.run
        assert restored.origin == data.origin
        assert restored.params_snapshot == data.params_snapshot

    def test_empty_sections_omitted(self) -> None:
        data = ManifestData(run={"id": "R1"})
        d = data.to_dict()
        assert "run" in d
        assert "origin" not in d  # empty dict omitted
        assert "params_snapshot" in d  # empty snapshot is still a frozen baseline
        assert d["params_snapshot"] == {}

    def test_from_dict_missing_keys(self) -> None:
        data = ManifestData.from_dict({})
        assert data.run == {}
        assert data.params_snapshot == {}


class TestReadManifest:
    """Tests for read_manifest()."""

    def test_read_sample_manifest(self, tmp_path: Path) -> None:
        shutil.copy(FIXTURES_DIR / "sample_manifest.toml", tmp_path / "manifest.toml")
        manifest = read_manifest(tmp_path)
        assert manifest.run["id"] == "R20260327-0001"
        assert manifest.run["status"] == "created"
        assert manifest.origin["case"] == "cavity_base"
        assert manifest.simulator["name"] == "lunar_pic"
        assert manifest.params_snapshot["u"] == 4.0e5

    def test_missing_manifest(self, tmp_path: Path) -> None:
        with pytest.raises(ManifestNotFoundError, match=r"manifest\.toml not found"):
            read_manifest(tmp_path)

    def test_invalid_toml(self, tmp_path: Path) -> None:
        (tmp_path / "manifest.toml").write_text("invalid [[[")
        with pytest.raises(ManifestError, match="Invalid TOML"):
            read_manifest(tmp_path)


class TestWriteManifest:
    """Tests for write_manifest()."""

    def test_write_and_read_back(self, tmp_path: Path) -> None:
        data = ManifestData(
            run={"id": "R20260327-0001", "status": "created"},
            origin={"case": "test_case"},
            params_snapshot={"nx": 64, "dt": 1e-6},
        )
        write_manifest(tmp_path, data)
        assert (tmp_path / "manifest.toml").exists()

        readback = read_manifest(tmp_path)
        assert readback.run["id"] == "R20260327-0001"
        assert readback.params_snapshot["nx"] == 64

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        deep_dir = tmp_path / "a" / "b" / "c"
        data = ManifestData(run={"id": "R1"})
        write_manifest(deep_dir, data)
        assert (deep_dir / "manifest.toml").exists()


class TestUpdateManifest:
    """Tests for update_manifest()."""

    def test_update_status(self, tmp_path: Path) -> None:
        data = ManifestData(
            run={"id": "R20260327-0001", "status": "created"},
        )
        write_manifest(tmp_path, data)

        updated = update_manifest(tmp_path, {"run": {"status": "submitted"}})
        assert updated.run["status"] == "submitted"
        assert updated.run["id"] == "R20260327-0001"  # preserved

    def test_add_new_section(self, tmp_path: Path) -> None:
        data = ManifestData(run={"id": "R1"})
        write_manifest(tmp_path, data)

        updated = update_manifest(
            tmp_path, {"job": {"job_id": "12345", "scheduler": "slurm"}}
        )
        assert updated.job["job_id"] == "12345"
        assert updated.run["id"] == "R1"

    def test_update_nonexistent_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ManifestNotFoundError):
            update_manifest(tmp_path, {"run": {"status": "submitted"}})
