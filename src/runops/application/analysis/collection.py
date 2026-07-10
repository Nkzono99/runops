"""Survey summary collection and table preparation helpers."""

from __future__ import annotations

import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runops.application.execution.readiness import evaluate_run_readiness
from runops.core.discovery import discover_runs
from runops.core.exceptions import SimctlError
from runops.core.manifest import ManifestData, read_manifest
from runops.core.models import analysis as analysis_models

from .artifacts import (
    artifact_path_relative_to_summary,
    build_survey_artifacts,
    collect_run_artifacts,
    figures_from_artifacts,
    read_artifacts_index,
    write_artifacts_index,
)
from .report import write_survey_report

SurveyCollectionResult = analysis_models.SurveyCollectionResult
SurveyTableResult = analysis_models.SurveyTableResult


def _flatten_summary(summary: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in summary.items():
        flat_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            nested = _flatten_summary(value, flat_key)
            if nested:
                flat.update(nested)
            else:
                flat[flat_key] = value
            continue
        flat[flat_key] = value
    return flat


def _csv_cell_value(value: Any) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _flatten_manifest_context(manifest: ManifestData) -> dict[str, Any]:
    flat: dict[str, Any] = {}
    sections = {
        "origin": manifest.origin,
        "classification": manifest.classification,
        "simulator": manifest.simulator,
        "launcher": manifest.launcher,
        "variation": manifest.variation,
        "param": manifest.params_snapshot,
    }
    for prefix, section in sections.items():
        if not section:
            continue
        flat.update(_flatten_summary(section, prefix))
    return flat


def _collect_numeric_stats(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    metric_values: dict[str, list[float]] = {}
    for row in rows:
        for key, value in row.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            numeric = float(value)
            if not math.isfinite(numeric):
                continue
            metric_values.setdefault(key, []).append(numeric)

    stats: dict[str, dict[str, float]] = {}
    for key, values in metric_values.items():
        if not values:
            continue
        stats[key] = {
            "count": float(len(values)),
            "min": min(values),
            "max": max(values),
            "mean": sum(values) / len(values),
        }
    return stats


def _extract_figures(run_dir: Path, summary: dict[str, Any]) -> list[dict[str, str]]:
    artifacts = collect_run_artifacts(run_dir, summary)
    return figures_from_artifacts(artifacts)


def extract_run_figures(
    run_dir: Path, summary: dict[str, Any]
) -> tuple[dict[str, str], ...]:
    """Return normalized figure metadata for a run summary."""

    return tuple(_extract_figures(run_dir, summary))


def _ordered_columns(rows: list[dict[str, Any]]) -> list[str]:
    columns: set[str] = set()
    for row in rows:
        columns.update(row.keys())
    preferred = [
        "run_id",
        "display_name",
        "status",
        "analysis_status",
        "analysis_ready",
        "simulator_status",
        "summary_available",
        "summary_status",
        "summary_partial",
        "missing_required_artifacts",
    ]
    return [
        *[column for column in preferred if column in columns],
        *sorted(columns - set(preferred)),
    ]


def _load_survey_aggregate(json_path: Path) -> dict[str, Any]:
    with open(json_path, encoding="utf-8") as f:
        aggregate = json.load(f)
    if not isinstance(aggregate, dict):
        raise SimctlError(f"Invalid survey aggregate at {json_path}")
    return aggregate


def _flatten_aggregate_run_row(run: dict[str, Any]) -> dict[str, Any]:
    row = {
        "run_id": run.get("run_id", ""),
        "display_name": run.get("display_name", ""),
        "status": run.get("status", ""),
    }
    for key in (
        "analysis_status",
        "analysis_ready",
        "simulator_status",
        "summary_available",
        "summary_status",
        "summary_partial",
        "missing_required_artifacts",
    ):
        if key in run:
            row[key] = run[key]
    flat_metadata = run.get("flat_metadata", {})
    if isinstance(flat_metadata, dict):
        row.update(flat_metadata)
    flat_summary = run.get("flat_summary", {})
    if isinstance(flat_summary, dict):
        row.update(flat_summary)
    return row


def _load_or_create_run_artifacts(
    run_dir: Path,
    summary: dict[str, Any],
    *,
    run_id: str,
    display_name: str,
) -> list[dict[str, Any]]:
    artifacts_path = run_dir / "analysis" / "artifacts.toml"
    if artifacts_path.is_file():
        return read_artifacts_index(artifacts_path)

    artifacts = collect_run_artifacts(
        run_dir,
        summary,
        run_id=run_id,
        display_name=display_name,
    )
    write_artifacts_index(
        artifacts_path,
        scope="run",
        generated_by="runo analyze collect",
        artifacts=artifacts,
    )
    return artifacts


def _survey_artifact_from_run_artifact(
    artifact: dict[str, Any],
    *,
    run_dir: Path,
    survey_dir: Path,
    summary_dir: Path,
    run_id: str,
    display_name: str,
) -> dict[str, Any]:
    survey_artifact = dict(artifact)
    artifact_path = str(artifact.get("path", "")).strip()
    if artifact_path:
        survey_rel_path = (
            (run_dir / "analysis" / artifact_path).relative_to(survey_dir).as_posix()
        )
        survey_artifact["path"] = artifact_path_relative_to_summary(
            survey_dir,
            summary_dir,
            survey_rel_path,
        )
        survey_artifact["source_path"] = survey_rel_path
    survey_artifact.setdefault("run_id", run_id)
    if display_name:
        survey_artifact.setdefault("display_name", display_name)
    return survey_artifact


def load_survey_plot_table(survey_dir: Path) -> SurveyTableResult:
    """Collect survey summaries and expose a flat table for plotting."""
    collection = collect_survey_summaries(survey_dir)
    aggregate = _load_survey_aggregate(collection.json_path)

    rows: list[dict[str, Any]] = []
    raw_runs = aggregate.get("runs", [])
    if isinstance(raw_runs, list):
        for item in raw_runs:
            if not isinstance(item, dict):
                continue
            rows.append(_flatten_aggregate_run_row(item))

    return SurveyTableResult(
        survey_dir=survey_dir,
        collection=collection,
        rows=tuple(rows),
        columns=tuple(_ordered_columns(rows)),
    )


def collect_survey_summaries(survey_dir: Path) -> SurveyCollectionResult:
    """Collect run summaries from a survey and write aggregate artifacts."""
    survey_dir = Path(survey_dir).resolve()
    run_dirs = discover_runs(survey_dir)
    if not run_dirs:
        raise SimctlError("No runs found in survey directory.")

    run_rows: list[dict[str, Any]] = []
    csv_rows: list[dict[str, Any]] = []
    figure_rows: list[dict[str, str]] = []
    artifact_rows: list[dict[str, Any]] = []
    state_counts: dict[str, int] = {}
    readiness_counts: dict[str, int] = {}
    readiness_issues: list[dict[str, Any]] = []
    generated_count = 0
    missing_count = 0
    warnings: list[str] = []
    summary_dir = survey_dir / "summary"

    for run_dir in run_dirs:
        run_id = run_dir.name
        display_name = ""
        state = ""
        flat_metadata: dict[str, Any] = {}
        metadata_sections: dict[str, Any] = {}
        analysis_ready = False
        analysis_status = ""
        simulator_status = ""
        missing_required_artifacts: list[str] = []
        readiness_warnings: list[str] = []
        try:
            manifest = read_manifest(run_dir)
            run_id = str(manifest.run.get("id", run_id))
            display_name = str(manifest.run.get("display_name", ""))
            state = str(manifest.run.get("status", ""))
            if state:
                state_counts[state] = state_counts.get(state, 0) + 1
            flat_metadata = _flatten_manifest_context(manifest)
            metadata_sections = {
                "origin": dict(manifest.origin),
                "classification": dict(manifest.classification),
                "simulator": dict(manifest.simulator),
                "launcher": dict(manifest.launcher),
                "variation": dict(manifest.variation),
                "param": dict(manifest.params_snapshot),
            }
            readiness = evaluate_run_readiness(run_dir, manifest=manifest)
            analysis_ready = readiness.analysis_ready
            analysis_status = readiness.analysis_status
            simulator_status = readiness.simulator_status
            missing_required_artifacts = list(readiness.missing_required_artifacts)
            readiness_warnings = list(readiness.warnings)
        except SimctlError:
            manifest = None

        summary_path = run_dir / "analysis" / "summary.json"
        row: dict[str, Any] = {
            "run_id": run_id,
            "display_name": display_name,
            "status": state,
            "summary_available": summary_path.is_file(),
            "summary_path": (
                str(summary_path.relative_to(survey_dir)).replace("\\", "/")
                if summary_path.is_file()
                else ""
            ),
            "analysis_status": analysis_status,
            "analysis_ready": analysis_ready,
            "simulator_status": simulator_status,
            "missing_required_artifacts": missing_required_artifacts,
            "readiness_warnings": readiness_warnings,
        }

        if not summary_path.is_file():
            missing_count += 1
            if state == "completed":
                analysis_ready = False
                if analysis_status in {"", "ready"}:
                    analysis_status = "incomplete"
                readiness_warnings.append("analysis/summary.json missing")
                row["analysis_status"] = analysis_status
                row["analysis_ready"] = analysis_ready
                row["readiness_warnings"] = readiness_warnings
            if analysis_status:
                readiness_counts[analysis_status] = (
                    readiness_counts.get(analysis_status, 0) + 1
                )
            if state == "completed" and not analysis_ready:
                readiness_issues.append(
                    {
                        "run_id": run_id,
                        "run_dir": str(run_dir),
                        "analysis_status": analysis_status or "unknown",
                        "missing_required_artifacts": missing_required_artifacts,
                        "warnings": readiness_warnings,
                    }
                )
                warnings.extend(
                    f"{run_id}: {warning}" for warning in readiness_warnings
                )
            run_rows.append(row)
            continue

        with open(summary_path, encoding="utf-8") as f:
            summary: dict[str, Any] = json.load(f)
        summary_status = str(summary.get("status", "")).strip()
        summary_partial = bool(summary.get("partial", False))
        if summary_status and summary_status != "completed":
            summary_partial = True
        if summary_partial:
            analysis_ready = False
            if analysis_status in {"", "ready"}:
                analysis_status = "incomplete"
            warning_status = summary_status or "partial"
            readiness_warnings.append(
                f"analysis/summary.json status is {warning_status}"
            )

        flat_summary = _flatten_summary(summary)
        csv_row: dict[str, Any] = {
            "run_id": run_id,
            "display_name": display_name,
            "status": state,
            "analysis_status": analysis_status,
            "analysis_ready": analysis_ready,
            "simulator_status": simulator_status,
            "summary_available": True,
            "summary_status": summary_status,
            "summary_partial": summary_partial,
            "missing_required_artifacts": missing_required_artifacts,
        }
        csv_row.update(flat_metadata)
        csv_row.update(flat_summary)
        csv_rows.append(csv_row)

        run_artifacts = _load_or_create_run_artifacts(
            run_dir,
            summary,
            run_id=run_id,
            display_name=display_name,
        )
        figures = figures_from_artifacts(run_artifacts)
        for figure in figures:
            figure_path = (run_dir / "analysis" / figure["path"]).relative_to(
                survey_dir
            )
            figure_rows.append(
                {
                    "run_id": run_id,
                    "display_name": display_name,
                    "path": str(figure_path).replace("\\", "/"),
                    "caption": figure["caption"],
                }
            )
        for artifact in run_artifacts:
            artifact_rows.append(
                _survey_artifact_from_run_artifact(
                    artifact,
                    run_dir=run_dir,
                    survey_dir=survey_dir,
                    summary_dir=summary_dir,
                    run_id=run_id,
                    display_name=display_name,
                )
            )

        row["summary"] = summary
        row["analysis_status"] = analysis_status
        row["analysis_ready"] = analysis_ready
        row["summary_status"] = summary_status
        row["summary_partial"] = summary_partial
        row["readiness_warnings"] = readiness_warnings
        row["metadata"] = metadata_sections
        row["flat_metadata"] = {
            key: _csv_cell_value(value) for key, value in flat_metadata.items()
        }
        row["flat_summary"] = {
            key: _csv_cell_value(value) for key, value in flat_summary.items()
        }
        row["figures"] = figures
        if analysis_status:
            readiness_counts[analysis_status] = (
                readiness_counts.get(analysis_status, 0) + 1
            )
        if state == "completed" and not analysis_ready:
            readiness_issues.append(
                {
                    "run_id": run_id,
                    "run_dir": str(run_dir),
                    "analysis_status": analysis_status or "unknown",
                    "missing_required_artifacts": missing_required_artifacts,
                    "warnings": readiness_warnings,
                }
            )
            warnings.extend(f"{run_id}: {warning}" for warning in readiness_warnings)
        run_rows.append(row)

    if not csv_rows:
        raise SimctlError("No summaries found. Run 'runops analyze summarize' first.")

    ordered_columns = _ordered_columns(csv_rows)

    summary_dir.mkdir(parents=True, exist_ok=True)
    csv_path = summary_dir / "survey_summary.csv"
    json_path = summary_dir / "survey_summary.json"
    artifacts_path = summary_dir / "artifacts.toml"
    report_path = summary_dir / "survey_summary.md"

    csv_output_rows: list[dict[str, object]] = []
    for row in csv_rows:
        csv_output_rows.append(
            {key: _csv_cell_value(value) for key, value in row.items()}
        )

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ordered_columns, extrasaction="ignore")
        writer.writeheader()
        for row in csv_output_rows:
            writer.writerow(row)

    numeric_stats = _collect_numeric_stats(csv_rows)
    aggregate = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "survey_dir": str(survey_dir),
        "total_runs": len(run_dirs),
        "summaries_collected": len(csv_rows),
        "generated_summaries": generated_count,
        "missing_summaries": missing_count,
        "readiness_counts": readiness_counts,
        "readiness_issues": readiness_issues,
        "state_counts": state_counts,
        "numeric_stats": numeric_stats,
        "warnings": warnings,
        "runs": run_rows,
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(aggregate, f, indent=2)
        f.write("\n")

    survey_artifacts = build_survey_artifacts(
        summary_dir=summary_dir,
        run_artifacts=artifact_rows,
    )
    write_artifacts_index(
        artifacts_path,
        scope="survey",
        generated_by="runo analyze collect",
        artifacts=survey_artifacts,
    )

    write_survey_report(
        report_path,
        survey_dir=survey_dir,
        total_runs=len(run_dirs),
        summaries_collected=len(csv_rows),
        generated_summaries=generated_count,
        missing_summaries=missing_count,
        readiness_counts=readiness_counts,
        readiness_issues=readiness_issues,
        state_counts=state_counts,
        numeric_stats=numeric_stats,
        figures=figure_rows,
        warnings=warnings,
    )

    return SurveyCollectionResult(
        survey_dir=survey_dir,
        total_runs=len(run_dirs),
        summaries_collected=len(csv_rows),
        generated_summaries=generated_count,
        missing_summaries=missing_count,
        readiness_counts=readiness_counts,
        readiness_issues=tuple(readiness_issues),
        state_counts=state_counts,
        csv_path=csv_path,
        json_path=json_path,
        artifacts_path=artifacts_path,
        report_path=report_path,
        artifacts=tuple(survey_artifacts),
        figures=tuple(figure_rows),
        warnings=tuple(warnings),
    )
