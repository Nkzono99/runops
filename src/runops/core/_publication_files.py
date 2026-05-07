"""File materialization helpers for publication exports."""

from __future__ import annotations

import hashlib
import mimetypes
import os
import shutil
import uuid
from dataclasses import replace
from pathlib import Path

from runops.core.exceptions import SimctlError
from runops.core.models import publication as publication_models

PublicationExportFile = publication_models.PublicationExportFile
PublicationSourceArtifact = publication_models.PublicationSourceArtifact

EXPORT_MODES = {"copy", "symlink"}


def ensure_export_dir_available(path: Path, *, force: bool) -> None:
    if not path.exists():
        return
    if not force:
        raise SimctlError(
            f"Export already exists: {path}. Use --name to choose another slot "
            "or --force to replace it."
        )


def create_staging_export_dir(path: Path) -> Path:
    """Return a sibling staging directory for atomic-ish export assembly."""
    return path.parent / f".{path.name}.tmp-{uuid.uuid4().hex}"


def cleanup_staging_export_dir(path: Path) -> None:
    """Best-effort cleanup for an incomplete staging export."""
    if path.exists():
        shutil.rmtree(path)


def finalize_export_dir(staging_dir: Path, export_dir: Path, *, force: bool) -> None:
    """Move a fully-rendered staging export into its final location."""
    if export_dir.exists():
        if not force:
            raise SimctlError(
                f"Export already exists: {export_dir}. "
                "Use --name to choose another slot or --force to replace it."
            )
        shutil.rmtree(export_dir)
    staging_dir.replace(export_dir)


def link_or_copy(source_path: Path, dest_path: Path, *, mode: str) -> None:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    if mode == "copy":
        shutil.copy2(source_path, dest_path)
        return

    if mode != "symlink":
        raise SimctlError(
            f"Unknown export mode: {mode!r}. Use one of: "
            f"{', '.join(sorted(EXPORT_MODES))}"
        )

    target = os.path.relpath(source_path, start=dest_path.parent)
    dest_path.symlink_to(target)


def compute_sha256(path: Path) -> str:
    sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return f"sha256:{sha256.hexdigest()}"


def materialize_export_files(
    artifacts: list[PublicationSourceArtifact],
    *,
    project_root: Path,
    files_dir: Path,
    mode: str,
) -> tuple[PublicationExportFile, ...]:
    exported_files: list[PublicationExportFile] = []
    materialized_paths: set[Path] = set()

    for artifact in artifacts:
        resolved_source = artifact.source_path.resolve()
        rel_source = resolved_source.relative_to(project_root)
        dest_path = files_dir / rel_source
        if dest_path not in materialized_paths:
            link_or_copy(resolved_source, dest_path, mode=mode)
            materialized_paths.add(dest_path)

        media_type = mimetypes.guess_type(str(resolved_source))[0] or ""
        exported_files.append(
            PublicationExportFile(
                role=artifact.role,
                source_path=resolved_source,
                export_path=dest_path,
                size_bytes=resolved_source.stat().st_size,
                sha256=compute_sha256(resolved_source),
                media_type=media_type,
                run_id=artifact.run_id,
                caption=artifact.caption,
            )
        )

    return tuple(exported_files)


def rebase_exported_files(
    files: tuple[PublicationExportFile, ...],
    *,
    from_root: Path,
    to_root: Path,
) -> tuple[PublicationExportFile, ...]:
    """Rebase export paths after moving a staged bundle into place."""
    return tuple(
        replace(
            item,
            export_path=to_root / item.export_path.relative_to(from_root),
        )
        for item in files
    )
