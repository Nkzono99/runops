"""Data models for publication export helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PublicationSourceArtifact:
    """One source artifact collected before export materialization."""

    role: str
    source_path: Path
    run_id: str = ""
    caption: str = ""


@dataclass(frozen=True)
class PublicationExportFile:
    """One exported artifact inside a publication bundle."""

    role: str
    source_path: Path
    export_path: Path
    size_bytes: int
    sha256: str
    media_type: str = ""
    run_id: str = ""
    caption: str = ""


@dataclass(frozen=True)
class PublicationExportResult:
    """Result of exporting project artifacts for a paper/manuscript."""

    paper_id: str
    export_name: str
    target_kind: str
    target_path: Path
    export_dir: Path
    manifest_path: Path
    readme_path: Path
    mode: str
    source_run_ids: tuple[str, ...]
    files: tuple[PublicationExportFile, ...]
    warnings: tuple[str, ...] = ()
