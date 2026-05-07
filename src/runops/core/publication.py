"""Publication-facing export helpers for project-side paper integration."""

from __future__ import annotations

import dataclasses as _dataclasses
import hashlib
import json
import mimetypes
import os
import shutil
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runops import __version__
from runops.core import _publication_models
from runops.core.analysis import (
    SurveyCollectionResult,
    collect_survey_summaries,
    extract_run_figures,
    generate_run_summary,
)
from runops.core.discovery import discover_runs
from runops.core.exceptions import ProvenanceError, SimctlError
from runops.core.manifest import ManifestData, read_manifest
from runops.core.project import find_project_root, load_project
from runops.core.provenance import collect_git_provenance
from runops.core.readiness import RunReadiness, evaluate_run_readiness
from runops.core.state import RunState

_EXPORT_MODES = {"copy", "symlink"}
_PAPER_STATUSES = {"accepted", "placeholder", "retry_planned", "excluded", "superseded"}

# Keep historical module attributes available for import compatibility.
dataclass = _dataclasses.dataclass
PublicationExportFile = _publication_models.PublicationExportFile
PublicationExportResult = _publication_models.PublicationExportResult
PublicationSourceArtifact = _publication_models.PublicationSourceArtifact


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


def _relative_to_project(project_root: Path, path: Path) -> str:
    return str(path.resolve().relative_to(project_root.resolve())).replace("\\", "/")


def _normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            result.append(text)
    return result


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


def _ensure_export_dir_available(path: Path, *, force: bool) -> None:
    if not path.exists():
        return
    if not force:
        raise SimctlError(
            f"Export already exists: {path}. Use --name to choose another slot "
            "or --force to replace it."
        )


def _create_staging_export_dir(path: Path) -> Path:
    """Return a sibling staging directory for atomic-ish export assembly."""
    return path.parent / f".{path.name}.tmp-{uuid.uuid4().hex}"


def _cleanup_staging_export_dir(path: Path) -> None:
    """Best-effort cleanup for an incomplete staging export."""
    if path.exists():
        shutil.rmtree(path)


def _finalize_export_dir(staging_dir: Path, export_dir: Path, *, force: bool) -> None:
    """Move a fully-rendered staging export into its final location."""
    if export_dir.exists():
        if not force:
            raise SimctlError(
                f"Export already exists: {export_dir}. "
                "Use --name to choose another slot or --force to replace it."
            )
        shutil.rmtree(export_dir)
    staging_dir.replace(export_dir)


def _link_or_copy(source_path: Path, dest_path: Path, *, mode: str) -> None:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    if mode == "copy":
        shutil.copy2(source_path, dest_path)
        return

    if mode != "symlink":
        raise SimctlError(
            f"Unknown export mode: {mode!r}. Use one of: "
            f"{', '.join(sorted(_EXPORT_MODES))}"
        )

    target = os.path.relpath(source_path, start=dest_path.parent)
    dest_path.symlink_to(target)


def _collect_project_git_info(project_root: Path) -> dict[str, Any]:
    try:
        provenance = collect_git_provenance(project_root)
    except ProvenanceError:
        return {}
    return {
        "git_commit": provenance.git_commit,
        "git_dirty": provenance.git_dirty,
    }


def _load_json_summary(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise SimctlError(f"Invalid JSON object at {path}")
    return data


def _compute_sha256(path: Path) -> str:
    sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return f"sha256:{sha256.hexdigest()}"


def _simulator_source_snapshot(manifest: ManifestData) -> dict[str, Any]:
    fields = (
        "source_repo",
        "git_commit",
        "git_dirty",
        "executable",
        "exe_hash",
        "resolver_mode",
        "package_version",
    )
    snapshot: dict[str, Any] = {}
    for field in fields:
        value = manifest.simulator_source.get(field, "")
        if value in ("", None, []):
            continue
        snapshot[field] = value
    return snapshot


def _build_run_record(
    project_root: Path,
    run_dir: Path,
    *,
    paper_status: str = "",
) -> dict[str, Any]:
    manifest = read_manifest(run_dir)
    run_id = str(manifest.run.get("id", run_dir.name)).strip() or run_dir.name
    execution_status = str(manifest.run.get("status", "")).strip()
    readiness = evaluate_run_readiness(run_dir, manifest=manifest)
    summary_path = run_dir / "analysis" / "summary.json"
    summary_available = summary_path.is_file()
    summary_keys: list[str] = []
    figure_count = 0

    if summary_available:
        summary = _load_json_summary(summary_path)
        summary_keys = sorted(str(key) for key in summary)
        figure_count = len(extract_run_figures(run_dir, summary))

    record: dict[str, Any] = {
        "run_id": run_id,
        "path": _relative_to_project(project_root, run_dir),
        "display_name": str(manifest.run.get("display_name", "")).strip(),
        "status": execution_status,
        "execution_status": execution_status,
        "analysis_status": readiness.analysis_status,
        "analysis_ready": readiness.analysis_ready,
        "paper_status": _resolve_paper_status(
            manifest,
            readiness,
            paper_status=paper_status,
        ),
        "retry_status": str(manifest.run.get("retry_status", "")).strip(),
        "case": str(manifest.origin.get("case", "")).strip(),
        "survey": str(manifest.origin.get("survey", "")).strip(),
        "simulator": str(
            manifest.simulator.get("name", manifest.simulator.get("adapter", ""))
        ).strip(),
        "adapter": str(manifest.simulator.get("adapter", "")).strip(),
        "launcher": str(
            manifest.launcher.get("name", manifest.launcher.get("kind", ""))
        ).strip(),
        "tags": _normalize_string_list(manifest.classification.get("tags", [])),
        "summary_available": summary_available,
        "summary_path": (
            _relative_to_project(project_root, summary_path)
            if summary_available
            else ""
        ),
        "summary_keys": summary_keys,
        "figure_count": figure_count,
    }
    simulator_source = _simulator_source_snapshot(manifest)
    if simulator_source:
        record["simulator_source"] = simulator_source
    return record


def _resolve_paper_status(
    manifest: ManifestData,
    readiness: RunReadiness,
    *,
    paper_status: str,
) -> str:
    explicit = paper_status.strip() or str(manifest.run.get("paper_status", "")).strip()
    if explicit:
        _validate_paper_status(explicit)
        return explicit
    retry_status = str(manifest.run.get("retry_status", "")).strip()
    if retry_status == "retry_planned":
        return "retry_planned"
    if readiness.execution_status == RunState.COMPLETED.value:
        return "accepted" if readiness.analysis_ready else "placeholder"
    if retry_status in {"partial", "retry_ready"}:
        return "placeholder"
    return "excluded"


def _validate_paper_status(value: str) -> None:
    if value not in _PAPER_STATUSES:
        raise SimctlError(
            f"Unknown paper status: {value!r}. Use one of: "
            f"{', '.join(sorted(_PAPER_STATUSES))}"
        )


def _collect_run_export_sources(
    run_dir: Path,
    *,
    include_figures: bool,
) -> tuple[list[PublicationSourceArtifact], list[str]]:
    manifest = read_manifest(run_dir)
    run_id = str(manifest.run.get("id", run_dir.name)).strip() or run_dir.name
    warnings: list[str] = []

    summary_path = run_dir / "analysis" / "summary.json"
    if not summary_path.is_file():
        state = str(manifest.run.get("status", "")).strip()
        if state != RunState.COMPLETED.value:
            raise SimctlError(
                f"Run {run_id} has no analysis/summary.json and is not completed."
            )
        generated = generate_run_summary(run_dir)
        summary_path = generated.summary_path
        warnings.extend(generated.warnings)

    files: list[PublicationSourceArtifact] = [
        PublicationSourceArtifact(
            role="run_manifest",
            source_path=run_dir / "manifest.toml",
            run_id=run_id,
        ),
        PublicationSourceArtifact(
            role="run_summary",
            source_path=summary_path,
            run_id=run_id,
        ),
    ]
    if include_figures:
        summary = _load_json_summary(summary_path)
        for figure in extract_run_figures(run_dir, summary):
            figure_path = run_dir / "analysis" / figure["path"]
            if not figure_path.is_file():
                warnings.append(
                    f"{run_id}: missing figure referenced by summary: {figure['path']}"
                )
                continue
            files.append(
                PublicationSourceArtifact(
                    role="run_figure",
                    source_path=figure_path,
                    run_id=run_id,
                    caption=figure["caption"],
                )
            )

    return files, warnings


def _collect_survey_export_sources(
    survey_dir: Path,
    *,
    include_figures: bool,
    include_plots: bool,
) -> tuple[SurveyCollectionResult, list[PublicationSourceArtifact], list[str]]:
    collection = collect_survey_summaries(survey_dir)
    files: list[PublicationSourceArtifact] = [
        PublicationSourceArtifact(
            role="survey_summary_csv",
            source_path=collection.csv_path,
        ),
        PublicationSourceArtifact(
            role="survey_summary_json",
            source_path=collection.json_path,
        ),
        PublicationSourceArtifact(
            role="survey_figures_index",
            source_path=collection.figures_path,
        ),
        PublicationSourceArtifact(
            role="survey_report",
            source_path=collection.report_path,
        ),
    ]
    warnings = list(collection.warnings)

    survey_toml = survey_dir / "survey.toml"
    if survey_toml.is_file():
        files.append(
            PublicationSourceArtifact(
                role="survey_config",
                source_path=survey_toml,
            )
        )

    if include_plots:
        plots_dir = survey_dir / "summary" / "plots"
        if plots_dir.is_dir():
            for path in sorted(plots_dir.rglob("*")):
                if path.is_file():
                    files.append(
                        PublicationSourceArtifact(
                            role="survey_plot",
                            source_path=path,
                        )
                    )

    if include_figures:
        for figure in collection.figures:
            path = survey_dir / figure["path"]
            if not path.is_file():
                warnings.append(
                    f"missing figure indexed in figures_index.json: {figure['path']}"
                )
                continue
            files.append(
                PublicationSourceArtifact(
                    role="run_figure",
                    source_path=path,
                    run_id=str(figure.get("run_id", "")).strip(),
                    caption=str(figure.get("caption", "")).strip(),
                )
            )

    return collection, files, warnings


def _materialize_export_files(
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
            _link_or_copy(resolved_source, dest_path, mode=mode)
            materialized_paths.add(dest_path)

        media_type = mimetypes.guess_type(str(resolved_source))[0] or ""
        exported_files.append(
            PublicationExportFile(
                role=artifact.role,
                source_path=resolved_source,
                export_path=dest_path,
                size_bytes=resolved_source.stat().st_size,
                sha256=_compute_sha256(resolved_source),
                media_type=media_type,
                run_id=artifact.run_id,
                caption=artifact.caption,
            )
        )

    return tuple(exported_files)


def _rebase_exported_files(
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


def _artifact_role_counts(files: tuple[PublicationExportFile, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in files:
        counts[item.role] = counts.get(item.role, 0) + 1
    return counts


def _paper_status_counts(run_records: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in run_records:
        status = str(record.get("paper_status", "")).strip() or "unknown"
        counts[status] = counts.get(status, 0) + 1
    return counts


def _build_run_source_metadata(
    *,
    project_root: Path,
    target_path: Path,
    run_record: dict[str, Any],
    files: tuple[PublicationExportFile, ...],
) -> dict[str, Any]:
    return {
        "kind": "run",
        "path": _relative_to_project(project_root, target_path),
        "run_count": 1,
        "artifact_counts": _artifact_role_counts(files),
        "paper_status_counts": _paper_status_counts([run_record]),
        "runs": [run_record],
        "run": run_record,
    }


def _build_survey_source_metadata(
    *,
    project_root: Path,
    target_path: Path,
    collection: SurveyCollectionResult,
    run_records: list[dict[str, Any]],
    files: tuple[PublicationExportFile, ...],
) -> dict[str, Any]:
    survey_toml = target_path / "survey.toml"
    summary_dir = target_path / "summary"

    return {
        "kind": "survey",
        "path": _relative_to_project(project_root, target_path),
        "run_count": len(run_records),
        "artifact_counts": _artifact_role_counts(files),
        "paper_status_counts": _paper_status_counts(run_records),
        "runs": run_records,
        "survey": {
            "survey_toml": (
                _relative_to_project(project_root, survey_toml)
                if survey_toml.is_file()
                else ""
            ),
            "summary_dir": (
                _relative_to_project(project_root, summary_dir)
                if summary_dir.is_dir()
                else ""
            ),
            "total_runs": collection.total_runs,
            "summaries_collected": collection.summaries_collected,
            "generated_summaries": collection.generated_summaries,
            "missing_summaries": collection.missing_summaries,
            "state_counts": dict(collection.state_counts),
            "figure_count": len(collection.figures),
            "plot_count": sum(1 for item in files if item.role == "survey_plot"),
        },
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
                _build_run_record(project_root, run_dir, paper_status=paper_status)
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
