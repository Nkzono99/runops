"""Analysis artifact checks for ``runo lint``."""

from __future__ import annotations

from pathlib import Path

from runops.application.execution.readiness import evaluate_run_readiness
from runops.application.operator.lint.models import LintContext, LintIssue
from runops.core.discovery import discover_runs
from runops.core.exceptions import SimctlError
from runops.core.manifest import read_manifest


def check_analysis(context: LintContext) -> list[LintIssue]:
    """Check whether analysis outputs are indexed and reproducible enough."""
    issues: list[LintIssue] = []
    for run_dir in discover_runs(context.project_root / "runs"):
        try:
            manifest = read_manifest(run_dir)
        except SimctlError:
            continue

        analysis_dir = run_dir / "analysis"
        summary_path = analysis_dir / "summary.json"
        artifacts_path = analysis_dir / "artifacts.toml"
        status = str(manifest.run.get("status", "")).strip()
        if status == "completed" and not summary_path.is_file():
            run_ref = context.relpath(run_dir).as_posix()
            issues.append(
                LintIssue(
                    severity="warning",
                    issue_id="analysis.completed_summary_missing",
                    path=summary_path,
                    message="completed run has no analysis/summary.json.",
                    recommendation=f"Run `runo analyze summarize {run_ref}`.",
                )
            )
        if status == "completed":
            readiness = evaluate_run_readiness(run_dir, manifest=manifest)
            missing = ", ".join(readiness.missing_required_artifacts)
            if missing:
                issues.append(
                    LintIssue(
                        severity="warning",
                        issue_id="analysis.completed_required_outputs_missing",
                        path=run_dir / "manifest.toml",
                        message=(
                            f"completed run is missing required output(s): {missing}."
                        ),
                        recommendation=(
                            "Inspect the run outputs before using this run as analysis "
                            "evidence."
                        ),
                    )
                )

        figures_dir = analysis_dir / "figures"
        if _has_files(figures_dir) and not artifacts_path.is_file():
            issues.append(
                LintIssue(
                    severity="warning",
                    issue_id="analysis.run_artifact_index_missing",
                    path=artifacts_path,
                    message="analysis figures exist without analysis/artifacts.toml.",
                    recommendation=(
                        "Run `runo analyze summarize` or `runo migrate apply M0-0001` "
                        "to create the artifact index."
                    ),
                    migration="M0-0001",
                )
            )

    issues.extend(_check_survey_summaries(context))
    return issues


def _check_survey_summaries(context: LintContext) -> list[LintIssue]:
    issues: list[LintIssue] = []
    runs_root = context.project_root / "runs"
    if not runs_root.is_dir():
        return issues

    for summary_dir in sorted(runs_root.rglob("summary")):
        if not summary_dir.is_dir():
            continue
        artifacts_path = summary_dir / "artifacts.toml"
        if (summary_dir / "figures_index.json").is_file():
            issues.append(
                LintIssue(
                    severity="warning",
                    issue_id="analysis.legacy_figures_index",
                    path=summary_dir / "figures_index.json",
                    message="legacy summary/figures_index.json is present.",
                    recommendation=(
                        "Run `runo migrate apply M0-0003` to remove the legacy index."
                    ),
                    migration="M0-0003",
                )
            )

        has_summary = (
            (summary_dir / "survey_summary.csv").is_file()
            or (summary_dir / "survey_summary.json").is_file()
            or (summary_dir / "survey_summary.md").is_file()
        )
        if has_summary and not artifacts_path.is_file():
            issues.append(
                LintIssue(
                    severity="warning",
                    issue_id="analysis.survey_artifact_index_missing",
                    path=artifacts_path,
                    message="survey summary exists without summary/artifacts.toml.",
                    recommendation=(
                        "Run `runo analyze collect` or `runo migrate apply M0-0001` "
                        "to create the survey artifact index."
                    ),
                    migration="M0-0001",
                )
            )

    return issues


def _has_files(path: Path) -> bool:
    if not path.is_dir():
        return False
    return any(child.is_file() for child in path.rglob("*"))
