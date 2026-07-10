"""Tests for core manifest module."""

from __future__ import annotations

import os
import shutil
import stat
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

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

    def test_empty_sections_omit_optional_but_emit_required_table(self) -> None:
        data = ManifestData(run={"id": "R1"})
        d = data.to_dict()
        assert "run" in d
        assert "origin" not in d  # empty dict omitted
        assert d["simulator_source"] == {}  # required even without known fields
        assert "params_snapshot" in d  # empty snapshot is still a frozen baseline
        assert d["params_snapshot"] == {}

    def test_from_dict_missing_keys(self) -> None:
        data = ManifestData.from_dict({})
        assert data.run == {}
        assert data.params_snapshot == {}

    def test_from_dict_deep_copies_extra_sections(self) -> None:
        raw = {
            "run": {"id": "R20260710-0001", "status": "created"},
            "extensions": {"plugin": {"items": ["a", "b"]}},
        }

        data = ManifestData.from_dict(raw)
        raw["extensions"]["plugin"]["items"].append("source-only")
        serialized = data.to_dict()
        serialized["extensions"]["plugin"]["items"].append("output-only")

        assert data.extra_sections == {"extensions": {"plugin": {"items": ["a", "b"]}}}

    def test_to_dict_canonical_sections_override_extra_sections(self) -> None:
        data = ManifestData(
            run={"id": "R20260710-0001", "status": "created"},
            extra_sections={
                "run": {"id": "shadowed", "status": "failed"},
                "extensions": {"plugin": {"enabled": True}},
            },
        )

        serialized = data.to_dict()

        assert serialized["run"] == {
            "id": "R20260710-0001",
            "status": "created",
        }
        assert serialized["extensions"] == {"plugin": {"enabled": True}}

    def test_from_dict_rejects_non_table_canonical_section(self) -> None:
        with pytest.raises(ManifestError, match=r"run.*table"):
            ManifestData.from_dict({"run": "not-a-table"})


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

    def test_non_utf8_manifest_is_reported_as_manifest_error(
        self,
        tmp_path: Path,
    ) -> None:
        (tmp_path / "manifest.toml").write_bytes(b"[run]\nid = \xff\n")

        with pytest.raises(ManifestError, match="Invalid encoding"):
            read_manifest(tmp_path)

    def test_manifest_io_failure_is_reported_as_manifest_error(
        self,
        tmp_path: Path,
    ) -> None:
        (tmp_path / "manifest.toml").write_text('[run]\nid = "R1"\n')

        with (
            patch("builtins.open", side_effect=PermissionError("access denied")),
            pytest.raises(ManifestError, match="access denied"),
        ):
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

    def test_fsyncs_temp_file_before_replace_and_directory_afterward(
        self,
        tmp_path: Path,
    ) -> None:
        events: list[str] = []
        real_fsync = os.fsync
        real_replace = os.replace

        def tracking_fsync(descriptor: int) -> None:
            kind = "directory" if stat.S_ISDIR(os.fstat(descriptor).st_mode) else "file"
            events.append(f"fsync:{kind}")
            real_fsync(descriptor)

        def tracking_replace(source: str, destination: str) -> None:
            events.append("replace")
            real_replace(source, destination)

        with (
            patch("runops.core.manifest.os.fsync", side_effect=tracking_fsync),
            patch("runops.core.manifest.os.replace", side_effect=tracking_replace),
        ):
            write_manifest(tmp_path, ManifestData(run={"id": "R1"}))

        assert events == ["fsync:file", "replace", "fsync:directory"]

    def test_directory_fsync_failure_is_reported_as_manifest_error(
        self,
        tmp_path: Path,
    ) -> None:
        real_fsync = os.fsync

        def fail_directory_fsync(descriptor: int) -> None:
            if stat.S_ISDIR(os.fstat(descriptor).st_mode):
                raise OSError("directory fsync failed")
            real_fsync(descriptor)

        with (
            patch(
                "runops.core.manifest.os.fsync",
                side_effect=fail_directory_fsync,
            ),
            pytest.raises(ManifestError, match="directory fsync failed"),
        ):
            write_manifest(tmp_path, ManifestData(run={"id": "R1"}))

    def test_manifest_roundtrip_preserves_unknown_sections(
        self, tmp_path: Path
    ) -> None:
        run_dir = tmp_path / "R20260710-0001"
        run_dir.mkdir()
        (run_dir / "manifest.toml").write_text(
            '[run]\nid = "R20260710-0001"\nstatus = "created"\n'
            '[extensions.plugin]\nenabled = true\nitems = ["a", "b"]\n',
            encoding="utf-8",
        )

        manifest = read_manifest(run_dir)
        manifest.run["display_name"] = "kept"
        write_manifest(run_dir, manifest)

        raw = tomllib.loads((run_dir / "manifest.toml").read_text(encoding="utf-8"))
        assert raw["run"]["display_name"] == "kept"
        assert raw["extensions"]["plugin"] == {
            "enabled": True,
            "items": ["a", "b"],
        }

    def test_manifest_roundtrip_preserves_unknown_fields_in_known_sections(
        self, tmp_path: Path
    ) -> None:
        run_dir = tmp_path / "R20260710-0001"
        run_dir.mkdir()
        (run_dir / "manifest.toml").write_text(
            '[run]\nid = "R20260710-0001"\nstatus = "created"\n'
            'future_flag = "preserved"\n'
            '[run.future_metadata]\nitems = ["a", "b"]\n',
            encoding="utf-8",
        )

        manifest = read_manifest(run_dir)
        write_manifest(run_dir, manifest)

        raw = tomllib.loads((run_dir / "manifest.toml").read_text(encoding="utf-8"))
        assert raw["run"]["future_flag"] == "preserved"
        assert raw["run"]["future_metadata"] == {"items": ["a", "b"]}

    def test_update_preserves_present_empty_canonical_tables(
        self,
        tmp_path: Path,
    ) -> None:
        (tmp_path / "manifest.toml").write_text(
            '[run]\nid = "R20260710-0001"\nstatus = "created"\n'
            "[simulator_source]\n"
            "[params_snapshot]\n",
            encoding="utf-8",
        )

        update_manifest(tmp_path, {"run": {"display_name": "kept"}})

        raw = tomllib.loads((tmp_path / "manifest.toml").read_text(encoding="utf-8"))
        assert raw["simulator_source"] == {}
        assert raw["params_snapshot"] == {}


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

    def test_update_preserves_unknown_sections(self, tmp_path: Path) -> None:
        (tmp_path / "manifest.toml").write_text(
            '[run]\nid = "R20260710-0001"\nstatus = "created"\n'
            "[extensions.plugin]\nenabled = true\n",
            encoding="utf-8",
        )

        updated = update_manifest(tmp_path, {"run": {"status": "submitted"}})

        raw = tomllib.loads((tmp_path / "manifest.toml").read_text(encoding="utf-8"))
        assert updated.run["status"] == "submitted"
        assert updated.extra_sections == {"extensions": {"plugin": {"enabled": True}}}
        assert raw["extensions"] == {"plugin": {"enabled": True}}
