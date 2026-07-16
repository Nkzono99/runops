"""Source metadata and artifact discovery for publication exports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from runops.application.analysis import (
    SurveyCollectionResult,
    collect_survey_summaries,
    extract_run_figures,
    generate_run_summary,
)
from runops.application.analysis.artifacts import (
    collect_run_artifacts,
    write_artifacts_index,
)
from runops.application.execution.readiness import RunReadiness, resolve_run_readiness
from runops.core.exceptions import SimctlError
from runops.core.manifest import ManifestData, read_manifest
from runops.core.models import publication as publication_models
from runops.core.state import RunState

PublicationExportFile = publication_models.PublicationExportFile
PublicationSourceArtifact = publication_models.PublicationSourceArtifact

PAPER_STATUSES = {"accepted", "placeholder", "retry_planned", "excluded", "superseded"}


def relative_to_project(project_root: Path, path: Path) -> str:
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


def _load_json_summary(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise SimctlError(f"Invalid JSON object at {path}")
    return data


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


def _validate_paper_status(value: str) -> None:
    if value not in PAPER_STATUSES:
        raise SimctlError(
            f"Unknown paper status: {value!r}. Use one of: "
            f"{', '.join(sorted(PAPER_STATUSES))}"
        )


def _resolve_paper_status(
    manifest: ManifestData,
    readiness: RunReadiness,
    *,
    paper_status: str,
    accept_incomplete_reason: str,
) -> str:
    explicit = paper_status.strip() or str(manifest.run.get("paper_status", "")).strip()
    if explicit:
        _validate_paper_status(explicit)
        if (
            explicit == "accepted"
            and not readiness.analysis_ready
            and not accept_incomplete_reason.strip()
        ):
            raise SimctlError(
                "Cannot mark an analysis-incomplete run as accepted without "
                "--accept-incomplete-reason <WHY>."
            )
        return explicit
    retry_status = str(manifest.run.get("retry_status", "")).strip()
    if retry_status == "retry_planned":
        return "retry_planned"
    if readiness.execution_status == RunState.COMPLETED.value:
        return "accepted" if readiness.analysis_ready else "placeholder"
    if retry_status in {"partial", "retry_ready"}:
        return "placeholder"
    return "excluded"


def build_run_record(
    project_root: Path,
    run_dir: Path,
    *,
    paper_status: str = "",
    accept_incomplete_reason: str = "",
) -> dict[str, Any]:
    manifest = read_manifest(run_dir)
    run_id = str(manifest.run.get("id", run_dir.name)).strip() or run_dir.name
    execution_status = str(manifest.run.get("status", "")).strip()
    readiness = resolve_run_readiness(run_dir, manifest=manifest)
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
        "path": relative_to_project(project_root, run_dir),
        "display_name": str(manifest.run.get("display_name", "")).strip(),
        "status": execution_status,
        "execution_status": execution_status,
        "analysis_status": readiness.analysis_status,
        "analysis_ready": readiness.analysis_ready,
        "readiness_reason_codes": list(readiness.reason_codes),
        "recommended_action": readiness.recommended_action,
        "paper_status": _resolve_paper_status(
            manifest,
            readiness,
            paper_status=paper_status,
            accept_incomplete_reason=accept_incomplete_reason,
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
            relative_to_project(project_root, summary_path) if summary_available else ""
        ),
        "summary_keys": summary_keys,
        "figure_count": figure_count,
    }
    simulator_source = _simulator_source_snapshot(manifest)
    if (
        record["paper_status"] == "accepted"
        and not readiness.analysis_ready
        and accept_incomplete_reason.strip()
    ):
        record["readiness_acceptance_reason"] = accept_incomplete_reason.strip()
    if simulator_source:
        record["simulator_source"] = simulator_source
    return record


def collect_run_export_sources(
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

    artifacts_path = run_dir / "analysis" / "artifacts.toml"
    if not artifacts_path.is_file():
        summary = _load_json_summary(summary_path)
        write_artifacts_index(
            artifacts_path,
            scope="run",
            generated_by="runo analyze export",
            artifacts=collect_run_artifacts(
                run_dir,
                summary,
                run_id=run_id,
                display_name=str(manifest.run.get("display_name", "")),
            ),
        )

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
        PublicationSourceArtifact(
            role="run_artifacts",
            source_path=artifacts_path,
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


def collect_survey_export_sources(
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
            role="survey_artifacts",
            source_path=collection.artifacts_path,
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
                    f"missing figure indexed in survey artifacts: {figure['path']}"
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


def build_run_source_metadata(
    *,
    project_root: Path,
    target_path: Path,
    run_record: dict[str, Any],
    files: tuple[PublicationExportFile, ...],
) -> dict[str, Any]:
    return {
        "kind": "run",
        "path": relative_to_project(project_root, target_path),
        "run_count": 1,
        "artifact_counts": _artifact_role_counts(files),
        "paper_status_counts": _paper_status_counts([run_record]),
        "runs": [run_record],
        "run": run_record,
    }


def build_survey_source_metadata(
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
        "path": relative_to_project(project_root, target_path),
        "run_count": len(run_records),
        "artifact_counts": _artifact_role_counts(files),
        "paper_status_counts": _paper_status_counts(run_records),
        "runs": run_records,
        "survey": {
            "survey_toml": (
                relative_to_project(project_root, survey_toml)
                if survey_toml.is_file()
                else ""
            ),
            "summary_dir": (
                relative_to_project(project_root, summary_dir)
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
