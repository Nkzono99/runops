"""Manifest (manifest.toml) read/write operations.

The manifest is the single source of truth for a run's metadata,
state, provenance, and job information.
"""

from __future__ import annotations

import copy
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

import tomli_w

from runops.core.event_log import emit_artifact_event
from runops.core.exceptions import ManifestError, ManifestNotFoundError

_MANIFEST_FILE = "manifest.toml"


@dataclass
class ManifestData:
    """Representation of manifest.toml matching SPEC section 12.2.

    This is mutable to allow incremental updates before writing back.

    Attributes:
        run: Run identification section.
        path: Path information section.
        origin: Origin/provenance section (case, survey, parent_run).
        classification: Classification metadata.
        simulator: Simulator configuration.
        launcher: Launcher configuration.
        simulator_source: Simulator source/build provenance.
        job: Slurm job configuration and status.
        variation: Changed keys from survey expansion.
        params_snapshot: Full parameter snapshot.
        files: Standard directory names.
    """

    run: dict[str, Any] = field(default_factory=dict)
    path: dict[str, Any] = field(default_factory=dict)
    origin: dict[str, Any] = field(default_factory=dict)
    classification: dict[str, Any] = field(default_factory=dict)
    simulator: dict[str, Any] = field(default_factory=dict)
    launcher: dict[str, Any] = field(default_factory=dict)
    simulator_source: dict[str, Any] = field(default_factory=dict)
    job: dict[str, Any] = field(default_factory=dict)
    variation: dict[str, Any] = field(default_factory=dict)
    params_snapshot: dict[str, Any] = field(default_factory=dict)
    files: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert the manifest to a TOML-serializable dictionary.

        Returns:
            Dictionary suitable for writing with tomli_w.
        """
        result: dict[str, Any] = {}
        if self.run:
            result["run"] = dict(self.run)
        if self.path:
            result["path"] = dict(self.path)
        if self.origin:
            result["origin"] = dict(self.origin)
        if self.classification:
            result["classification"] = dict(self.classification)
        if self.simulator:
            result["simulator"] = dict(self.simulator)
        if self.launcher:
            result["launcher"] = dict(self.launcher)
        if self.simulator_source:
            result["simulator_source"] = dict(self.simulator_source)
        if self.job:
            result["job"] = dict(self.job)
        if self.variation:
            result["variation"] = dict(self.variation)
        if self.params_snapshot:
            result["params_snapshot"] = dict(self.params_snapshot)
        if self.files:
            result["files"] = dict(self.files)
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ManifestData:
        """Create a ManifestData from a parsed TOML dictionary.

        Args:
            data: Parsed TOML dictionary.

        Returns:
            ManifestData instance.
        """
        return cls(
            run=dict(data.get("run", {})),
            path=dict(data.get("path", {})),
            origin=dict(data.get("origin", {})),
            classification=dict(data.get("classification", {})),
            simulator=dict(data.get("simulator", {})),
            launcher=dict(data.get("launcher", {})),
            simulator_source=dict(data.get("simulator_source", {})),
            job=dict(data.get("job", {})),
            variation=dict(data.get("variation", {})),
            params_snapshot=dict(data.get("params_snapshot", {})),
            files=dict(data.get("files", {})),
        )


def read_manifest(run_dir: Path) -> ManifestData:
    """Read and parse a run's manifest.toml.

    Args:
        run_dir: Path to the run directory.

    Returns:
        Parsed ManifestData instance.

    Raises:
        ManifestNotFoundError: If manifest.toml does not exist.
        ManifestError: If the file cannot be parsed.
    """
    manifest_path = run_dir / _MANIFEST_FILE

    if not manifest_path.exists():
        raise ManifestNotFoundError(f"{_MANIFEST_FILE} not found in {run_dir}")

    try:
        with open(manifest_path, "rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ManifestError(f"Invalid TOML in {manifest_path}: {e}") from e

    return ManifestData.from_dict(data)


def write_manifest(
    run_dir: Path,
    data: ManifestData,
    *,
    event_path: Path | None = None,
    log_event: bool = True,
) -> None:
    """Write manifest data to manifest.toml atomically.

    Uses write-to-temp + rename to avoid partial writes if the process
    is interrupted.  On POSIX systems ``os.replace`` is atomic within
    the same filesystem.

    Args:
        run_dir: Path to the run directory.
        data: ManifestData to write.
        event_path: Optional display path recorded in the event log.  This is
            useful when the manifest is written into a staging directory and
            later atomically moved into its final location.
        log_event: Whether to emit a structured artifact event after the write
            succeeds.  Callers that stage files before an atomic rename can
            disable this and emit a final-path event after commit.

    Raises:
        ManifestError: If the file cannot be written.
    """
    import os
    import tempfile

    manifest_path = run_dir / _MANIFEST_FILE

    display_path = event_path or manifest_path
    existed_before = display_path.exists()

    try:
        run_dir.mkdir(parents=True, exist_ok=True)
        # Write to a temp file in the same directory, then atomic rename
        fd, tmp_path = tempfile.mkstemp(
            dir=str(run_dir), suffix=".tmp", prefix=".manifest_"
        )
        try:
            with os.fdopen(fd, "wb") as f:
                tomli_w.dump(data.to_dict(), f)
            os.replace(tmp_path, str(manifest_path))
        except BaseException:
            import contextlib

            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise
    except OSError as e:
        raise ManifestError(f"Failed to write {manifest_path}: {e}") from e

    if log_event:
        operation = "update" if existed_before else "create"
        emit_artifact_event(
            display_path,
            operation=operation,
            artifact_kind="manifest",
            summary=f"{operation.title()} manifest.toml",
        )


def update_manifest(run_dir: Path, updates: dict[str, Any]) -> ManifestData:
    """Merge updates into an existing manifest.toml.

    Reads the current manifest, deep-merges the updates, and writes
    the result back.

    Args:
        run_dir: Path to the run directory.
        updates: Nested dictionary of sections/keys to update.

    Returns:
        The updated ManifestData.

    Raises:
        ManifestNotFoundError: If manifest.toml does not exist.
        ManifestError: If read or write fails.
    """
    manifest = read_manifest(run_dir)
    current = manifest.to_dict()

    _deep_merge(current, updates)

    updated = ManifestData.from_dict(current)
    write_manifest(run_dir, updated)
    return updated


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> None:
    """Recursively merge overlay into base, mutating base in place.

    Args:
        base: Base dictionary to merge into.
        overlay: Dictionary of updates to apply.
    """
    for key, value in overlay.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = copy.deepcopy(value)
