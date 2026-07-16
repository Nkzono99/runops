"""Publication-facing export helpers for project-side paper integration."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runops import __version__
from runops.core.discovery import discover_runs
from runops.core.exceptions import ProvenanceError, SimctlError
from runops.core.manifest import read_manifest
from runops.core.models import publication as publication_models
from runops.core.project import find_project_root, load_project
from runops.core.provenance import collect_git_provenance

from . import files as publication_files
from . import sources as publication_sources

_EXPORT_MODES = publication_files.EXPORT_MODES
_PAPER_STATUSES = publication_sources.PAPER_STATUSES

PublicationExportFile = publication_models.PublicationExportFile
PublicationExportResult = publication_models.PublicationExportResult
PublicationSourceArtifact = publication_models.PublicationSourceArtifact

_cleanup_staging_export_dir = publication_files.cleanup_staging_export_dir
_create_staging_export_dir = publication_files.create_staging_export_dir
_ensure_export_dir_available = publication_files.ensure_export_dir_available
_finalize_export_dir = publication_files.finalize_export_dir
_link_or_copy = publication_files.link_or_copy
_compute_sha256 = publication_files.compute_sha256
_materialize_export_files = publication_files.materialize_export_files
_rebase_exported_files = publication_files.rebase_exported_files

_build_run_record = publication_sources.build_run_record
_build_run_source_metadata = publication_sources.build_run_source_metadata
_build_survey_source_metadata = publication_sources.build_survey_source_metadata
_collect_run_export_sources = publication_sources.collect_run_export_sources
_collect_survey_export_sources = publication_sources.collect_survey_export_sources
_relative_to_project = publication_sources.relative_to_project


def _slugify(value: str) -> str:
    text = value.strip().lower()
    chars: list[str] = []
    last_dash = False
    for ch in text:
        if ch.isalnum():
            chars.append(ch)
            last_dash = False
            continue
        if (ch in {"-", "_", ".", "/"} or ch.isspace()) and not last_dash:
            chars.append("-")
            last_dash = True
    slug = "".join(chars).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _infer_target_kind(target_path: Path) -> str:
    if (target_path / "manifest.toml").is_file():
        return "run"
    if discover_runs(target_path):
        return "survey"
    raise SimctlError(
        "Export target must be a run directory or a directory containing runs."
    )


def _default_export_name(
    *,
    target_kind: str,
    target_path: Path,
    project_root: Path,
) -> str:
    if target_kind == "run":
        try:
            run_id = str(
                read_manifest(target_path).run.get("id", target_path.name)
            ).strip()
        except SimctlError:
            run_id = target_path.name
        base = _slugify(run_id) or "run"
    else:
        base = _slugify(_relative_to_project(project_root, target_path)) or "survey"
    return f"{target_kind}-{base}-{_utc_timestamp().lower()}"


def _collect_project_git_info(project_root: Path) -> dict[str, Any]:
    try:
        provenance = collect_git_provenance(project_root)
    except ProvenanceError:
        return {}
    return {
        "git_commit": provenance.git_commit,
        "git_dirty": provenance.git_dirty,
    }


def _write_export_readme(
    path: Path,
    *,
    export_id: str,
    paper_id: str,
    export_name: str,
    target_kind: str,
    target_relpath: str,
    mode: str,
    run_ids: tuple[str, ...],
    files: tuple[PublicationExportFile, ...],
    warnings: tuple[str, ...],
) -> None:
    lines = [
        "# Publication Export",
        "",
        f"- Export ID: `{export_id}`",
        f"- Paper ID: `{paper_id}`",
        f"- Export name: `{export_name}`",
        f"- Target kind: `{target_kind}`",
        f"- Source target: `{target_relpath}`",
        f"- Export mode: `{mode}`",
        f"- Run count: {len(run_ids)}",
        f"- File count: {len(files)}",
        f"- Warning count: {len(warnings)}",
        f"- Generated at: `{datetime.now(timezone.utc).isoformat(timespec='seconds')}`",
        "",
        "## Run IDs",
        "",
    ]
    if run_ids:
        for run_id in run_ids:
            lines.append(f"- `{run_id}`")
    else:
        lines.append("- None")

    lines.extend(["", "## Files", ""])
    for item in files:
        export_relpath = str(item.export_path.relative_to(path.parent)).replace(
            "\\",
            "/",
        )
        details = [item.role]
        if item.run_id:
            details.append(f"run={item.run_id}")
        if item.caption:
            details.append(f"caption={item.caption}")
        details_text = "; ".join(details)
        lines.append(
            f"- `{item.export_path.name}`: `{export_relpath}` ({details_text})"
        )

    if warnings:
        lines.extend(["", "## Warnings", ""])
        for warning in warnings:
            lines.append(f"- {warning}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def export_publication_bundle(
    target_path: Path,
    *,
    paper_id: str,
    name: str = "",
    mode: str = "copy",
    include_figures: bool = True,
    include_plots: bool = True,
    paper_status: str = "",
    accept_incomplete_reason: str = "",
    force: bool = False,
) -> PublicationExportResult:
    """Export publication-facing artifacts for one run or survey-like directory."""
    normalized_mode = mode.strip().lower()
    if normalized_mode not in _EXPORT_MODES:
        raise SimctlError(
            f"Unknown export mode: {mode!r}. Use one of: "
            f"{', '.join(sorted(_EXPORT_MODES))}"
        )

    target_path = target_path.resolve()
    if not target_path.is_dir():
        raise SimctlError(f"Directory not found: {target_path}")

    project_root = find_project_root(target_path)
    project = load_project(project_root)
    target_kind = _infer_target_kind(target_path)

    paper_dir_token = _slugify(paper_id)
    if not paper_dir_token:
        raise SimctlError("Paper ID must contain at least one alphanumeric character.")

    export_name = _slugify(name) if name.strip() else ""
    if not export_name:
        export_name = _default_export_name(
            target_kind=target_kind,
            target_path=target_path,
            project_root=project_root,
        )

    export_id = f"{paper_dir_token}/{export_name}"
    paper_root = project_root / "exports" / "papers" / paper_dir_token
    export_dir = paper_root / export_name
    _ensure_export_dir_available(export_dir, force=force)
    staging_dir = _create_staging_export_dir(export_dir)
    files_dir = staging_dir / "files"

    source_run_ids: tuple[str, ...]
    source_metadata: dict[str, Any]
    warnings: tuple[str, ...]

    try:
        if target_kind == "run":
            source_artifacts, warning_list = _collect_run_export_sources(
                target_path,
                include_figures=include_figures,
            )
            exported_files = _materialize_export_files(
                source_artifacts,
                project_root=project_root,
                files_dir=files_dir,
                mode=normalized_mode,
            )
            run_record = _build_run_record(
                project_root,
                target_path,
                paper_status=paper_status,
                accept_incomplete_reason=accept_incomplete_reason,
            )
            source_run_ids = (str(run_record["run_id"]),)
            source_metadata = _build_run_source_metadata(
                project_root=project_root,
                target_path=target_path,
                run_record=run_record,
                files=exported_files,
            )
            warnings = tuple(warning_list)
        else:
            collection, source_artifacts, warning_list = _collect_survey_export_sources(
                target_path,
                include_figures=include_figures,
                include_plots=include_plots,
            )
            exported_files = _materialize_export_files(
                source_artifacts,
                project_root=project_root,
                files_dir=files_dir,
                mode=normalized_mode,
            )
            run_records = [
                _build_run_record(
                    project_root,
                    run_dir,
                    paper_status=paper_status,
                    accept_incomplete_reason=accept_incomplete_reason,
                )
                for run_dir in discover_runs(target_path)
            ]
            source_run_ids = tuple(record["run_id"] for record in run_records)
            source_metadata = _build_survey_source_metadata(
                project_root=project_root,
                target_path=target_path,
                collection=collection,
                run_records=run_records,
                files=exported_files,
            )
            warnings = tuple(warning_list)

        manifest_path = staging_dir / "manifest.json"
        readme_path = staging_dir / "README.md"
        target_relpath = _relative_to_project(project_root, target_path)

        manifest_payload: dict[str, Any] = {
            "schema_version": 2,
            "paper_id": paper_id,
            "paper_dir": paper_dir_token,
            "export_name": export_name,
            "target_kind": target_kind,
            "target_path": target_relpath,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "mode": normalized_mode,
            "source_run_ids": list(source_run_ids),
            "paper": {
                "id": paper_id,
                "slug": paper_dir_token,
            },
            "export": {
                "id": export_id,
                "name": export_name,
                "dir": _relative_to_project(project_root, export_dir),
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "mode": normalized_mode,
                "tool": {
                    "name": "runops",
                    "version": __version__,
                },
            },
            "project": {
                "name": project.name,
                "root": str(project_root),
                "runops_version": __version__,
                **_collect_project_git_info(project_root),
            },
            "source": source_metadata,
            "files": [
                {
                    "role": item.role,
                    "source_path": _relative_to_project(project_root, item.source_path),
                    "export_path": str(
                        item.export_path.relative_to(staging_dir)
                    ).replace(
                        "\\",
                        "/",
                    ),
                    "run_id": item.run_id,
                    "caption": item.caption,
                    "size_bytes": item.size_bytes,
                    "sha256": item.sha256,
                    "media_type": item.media_type,
                }
                for item in exported_files
            ],
            "warnings": list(warnings),
        }
        staging_dir.mkdir(parents=True, exist_ok=True)
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest_payload, f, indent=2)
            f.write("\n")

        _write_export_readme(
            readme_path,
            export_id=export_id,
            paper_id=paper_id,
            export_name=export_name,
            target_kind=target_kind,
            target_relpath=target_relpath,
            mode=normalized_mode,
            run_ids=source_run_ids,
            files=exported_files,
            warnings=warnings,
        )

        _finalize_export_dir(staging_dir, export_dir, force=force)
        rebased_files = _rebase_exported_files(
            exported_files,
            from_root=staging_dir,
            to_root=export_dir,
        )
    except Exception:
        _cleanup_staging_export_dir(staging_dir)
        raise

    return PublicationExportResult(
        paper_id=paper_id,
        export_name=export_name,
        target_kind=target_kind,
        target_path=target_path,
        export_dir=export_dir,
        manifest_path=export_dir / "manifest.json",
        readme_path=export_dir / "README.md",
        mode=normalized_mode,
        source_run_ids=source_run_ids,
        files=rebased_files,
        warnings=warnings,
    )
