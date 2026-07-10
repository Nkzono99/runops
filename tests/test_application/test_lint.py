"""Tests for project lint checks."""

from __future__ import annotations

from pathlib import Path

from runops.application.operator.lint import run_project_lint
from runops.core.manifest import ManifestData, write_manifest
from runops.harness.builder import GITIGNORE_MANAGED_END, GITIGNORE_MANAGED_START


def _write_project(path: Path) -> None:
    (path / "runops.toml").write_text(
        """
[project]
name = "demo"
""".lstrip(),
        encoding="utf-8",
    )
    (path / "campaign.toml").write_text('[campaign]\ngoal = "demo"\n')
    notes_dir = path / "notes"
    notes_dir.mkdir(parents=True)
    (notes_dir / "README.md").write_text("# Notes\n", encoding="utf-8")
    research_dir = path / "research"
    research_dir.mkdir(parents=True)
    (research_dir / "agenda.md").write_text(
        """
# Research Agenda

## Current Decision

- Decision: Keep the current plan.

## Next Actions

1. Action: inspect latest run.
   - Evidence path to produce: notes/2026-05-08.md
""".lstrip(),
        encoding="utf-8",
    )
    (path / ".gitignore").write_text(
        f"{GITIGNORE_MANAGED_START}\nwork/\n{GITIGNORE_MANAGED_END}\n",
        encoding="utf-8",
    )


def _write_run(path: Path, run_id: str, status: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    write_manifest(
        path,
        ManifestData(
            run={"id": run_id, "status": status},
            simulator_source={
                "git_commit": "abc123",
                "exe_hash": "sha256:demo",
                "package_version": "1.0.0",
            },
        ),
    )


def _write_run_with_slurm_state(path: Path, status: str, slurm_state: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    write_manifest(
        path,
        ManifestData(
            run={
                "id": path.name,
                "status": status,
                "last_slurm_state": slurm_state,
            },
        ),
    )


def test_project_lint_accepts_healthy_minimal_project(tmp_path: Path) -> None:
    _write_project(tmp_path)

    report = run_project_lint(tmp_path)

    assert report.status == "ok"
    assert report.issues == ()


def test_project_lint_reports_missing_structure(tmp_path: Path) -> None:
    (tmp_path / "runops.toml").write_text(
        '[project]\nname = "demo"\n',
        encoding="utf-8",
    )

    report = run_project_lint(tmp_path, scopes=("structure",))

    ids = {issue.issue_id for issue in report.issues}
    assert "structure.campaign_missing" in ids
    assert "structure.research_agenda_missing" in ids
    assert report.error_count == 1


def test_project_lint_reports_invalid_manifest(tmp_path: Path) -> None:
    _write_project(tmp_path)
    run_dir = tmp_path / "runs" / "R20260508-0001"
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.toml").write_text("[run\n", encoding="utf-8")

    report = run_project_lint(tmp_path, scopes=("runs",))

    assert [issue.issue_id for issue in report.issues] == ["runs.manifest_invalid"]
    assert report.error_count == 1


def test_project_lint_reports_duplicate_run_id(tmp_path: Path) -> None:
    _write_project(tmp_path)
    _write_run(tmp_path / "runs" / "a", "R20260508-0001", "created")
    _write_run(tmp_path / "runs" / "b", "R20260508-0001", "created")

    report = run_project_lint(tmp_path, scopes=("runs",))

    assert any(issue.issue_id == "runs.run_id_duplicate" for issue in report.issues)
    assert report.error_count == 1


def test_project_lint_reports_status_slurm_conflict(tmp_path: Path) -> None:
    _write_project(tmp_path)
    _write_run_with_slurm_state(
        tmp_path / "runs" / "R20260508-0001",
        "completed",
        "FAILED",
    )

    report = run_project_lint(tmp_path, scopes=("runs",))

    assert any(
        issue.issue_id == "runs.status_slurm_conflict" for issue in report.issues
    )
    assert report.error_count == 1


def test_project_lint_reports_missing_analysis_summary(tmp_path: Path) -> None:
    _write_project(tmp_path)
    _write_run(tmp_path / "runs" / "R20260508-0001", "R20260508-0001", "completed")

    report = run_project_lint(tmp_path, scopes=("analysis",))

    assert any(
        issue.issue_id == "analysis.completed_summary_missing"
        for issue in report.issues
    )


def test_project_lint_reports_legacy_figures_index(tmp_path: Path) -> None:
    _write_project(tmp_path)
    summary_dir = tmp_path / "runs" / "angle_scan" / "summary"
    summary_dir.mkdir(parents=True)
    (summary_dir / "figures_index.json").write_text("{}\n", encoding="utf-8")

    report = run_project_lint(tmp_path, scopes=("analysis",))

    issue = next(
        issue
        for issue in report.issues
        if issue.issue_id == "analysis.legacy_figures_index"
    )
    assert issue.migration == "M0-0003"


def test_project_lint_reports_agenda_without_evidence_path(tmp_path: Path) -> None:
    _write_project(tmp_path)
    (tmp_path / "research" / "agenda.md").write_text(
        """
# Research Agenda

## Current Decision

- Decision: Keep the current plan.

## Next Actions

1. Action: run a new comparison.
""".lstrip(),
        encoding="utf-8",
    )

    report = run_project_lint(tmp_path, scopes=("knowledge",))

    assert any(
        issue.issue_id == "knowledge.next_actions_evidence_missing"
        for issue in report.issues
    )


def test_project_lint_reports_incomplete_codex_plugin_metadata(
    tmp_path: Path,
) -> None:
    """Plugin recommendation metadata errors are project health errors."""
    _write_project(tmp_path)
    (tmp_path / "site.toml").write_text(
        '[site]\nname = "test-site"\n'
        "[site.codex_plugins.incomplete]\n"
        'display_name = "Incomplete Plugin"\n',
        encoding="utf-8",
    )

    report = run_project_lint(tmp_path, scopes=("plugins",))

    assert report.status == "fail"
    assert report.error_count == 2
    assert [issue.issue_id for issue in report.issues] == [
        "plugins.metadata_error",
        "plugins.metadata_error",
    ]
    assert all(issue.path == tmp_path / "site.toml" for issue in report.issues)


def test_project_lint_reports_codex_plugin_metadata_warnings(
    tmp_path: Path,
) -> None:
    """Plugin recommendation metadata warnings remain non-fatal by default."""
    _write_project(tmp_path)
    (tmp_path / "site.toml").write_text(
        '[site]\nname = "test-site"\n'
        "[site.codex_plugins.site-context]\n"
        'display_name = "Site Context"\n'
        'reason = "Site-local workflow guidance."\n'
        'install_hint = "codex plugin add site-context@test"\n'
        'visibility = "private"\n',
        encoding="utf-8",
    )

    report = run_project_lint(tmp_path, scopes=("plugins",))

    assert report.status == "warning"
    assert report.error_count == 0
    assert report.warning_count == 1
    issue = report.issues[0]
    assert issue.issue_id == "plugins.metadata_warning"
    assert issue.path == tmp_path / "site.toml"


def test_project_lint_points_project_plugin_issues_to_runops_toml(
    tmp_path: Path,
) -> None:
    """Project-level plugin metadata issues point users back to runops.toml."""
    _write_project(tmp_path)
    (tmp_path / "runops.toml").write_text(
        '[project]\nname = "demo"\ncodex_plugins = ["broken"]\n',
        encoding="utf-8",
    )

    report = run_project_lint(tmp_path, scopes=("plugins",))

    assert report.status == "warning"
    assert report.warning_count == 1
    issue = report.issues[0]
    assert issue.issue_id == "plugins.metadata_warning"
    assert issue.path == tmp_path / "runops.toml"
