"""Tests for project lint checks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from runops.application.operator.lint import run_project_lint
from runops.core.manifest import ManifestData, read_manifest, write_manifest
from runops.harness.builder import GITIGNORE_MANAGED_END, GITIGNORE_MANAGED_START
from tests.factories import write_toml

_REQUIRED_MANIFEST_TABLES = (
    "run",
    "origin",
    "simulator",
    "launcher",
    "simulator_source",
    "job",
    "params_snapshot",
)

_REQUIRED_MANIFEST_FIELDS = (
    ("run", "id"),
    ("run", "status"),
    ("origin", "case"),
    ("simulator", "name"),
    ("launcher", "name"),
    ("job", "scheduler"),
    ("job", "job_id"),
    ("job", "submitted_at"),
)


def _write_project(path: Path) -> None:
    (path / "runops.toml").write_text(
        """
[project]
name = "demo"
""".lstrip(),
        encoding="utf-8",
    )
    (path / "campaign.toml").write_text('[campaign]\ngoal = "demo"\n')
    research_dir = path / "research"
    (research_dir / "journal" / "archive").mkdir(parents=True)
    (research_dir / "results").mkdir()
    (research_dir / "archive" / "results").mkdir(parents=True)
    (research_dir / "CURRENT.md").write_text(
        "# Current Research State\n",
        encoding="utf-8",
    )
    (research_dir / "journal" / "active.md").write_text(
        "# Research Journal\n\n", encoding="utf-8"
    )
    (path / ".gitignore").write_text(
        f"{GITIGNORE_MANAGED_START}\nwork/\n{GITIGNORE_MANAGED_END}\n",
        encoding="utf-8",
    )


def _canonical_manifest(path: Path, run_id: str, status: str) -> ManifestData:
    return ManifestData(
        run={
            "id": run_id,
            "display_name": run_id,
            "status": status,
            "created_at": "2026-05-08T12:00:00+09:00",
        },
        path={"run_dir": path.as_posix()},
        origin={"case": "demo", "survey": "", "parent_run": ""},
        classification={"model": "demo", "submodel": "", "tags": []},
        simulator={
            "name": "demo",
            "adapter": "generic",
            "resolver_mode": "package",
        },
        launcher={"name": "srun"},
        simulator_source={
            "resolver_mode": "package",
            "source_repo": "",
            "git_commit": "abc123",
            "git_dirty": False,
            "build_command": "",
            "executable": "solver",
            "exe_hash": "sha256:demo",
            "package_version": "1.0.0",
        },
        job={
            "scheduler": "slurm",
            "job_id": "",
            "partition": "debug",
            "submitted_at": "",
        },
        variation={"changed_keys": []},
        params_snapshot={},
        files={
            "input_dir": "input",
            "submit_dir": "submit",
            "work_dir": "work",
            "analysis_dir": "analysis",
            "status_dir": "status",
        },
    )


def _write_run(path: Path, run_id: str, status: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    write_manifest(path, _canonical_manifest(path, run_id, status))


def _write_run_with_slurm_state(path: Path, status: str, slurm_state: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    manifest = _canonical_manifest(path, path.name, status)
    manifest.run["last_slurm_state"] = slurm_state
    write_manifest(path, manifest)


def _write_manifest_dict(path: Path, manifest: dict[str, Any]) -> None:
    write_toml(path / "manifest.toml", manifest)


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
    assert "structure.research_current_missing" in ids
    assert "structure.research_journal_missing" in ids
    assert report.error_count == 1


def test_project_lint_reports_invalid_manifest(tmp_path: Path) -> None:
    _write_project(tmp_path)
    run_dir = tmp_path / "runs" / "R20260508-0001"
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.toml").write_text("[run\n", encoding="utf-8")

    report = run_project_lint(tmp_path, scopes=("runs",))

    assert [issue.issue_id for issue in report.issues] == ["runs.manifest_invalid"]
    assert report.error_count == 1


def test_project_lint_reports_non_utf8_manifest_without_aborting(
    tmp_path: Path,
) -> None:
    _write_project(tmp_path)
    run_dir = tmp_path / "runs" / "R20260508-0001"
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.toml").write_bytes(b"[run]\nid = \xff\n")

    report = run_project_lint(tmp_path, scopes=("runs",))

    assert [issue.issue_id for issue in report.issues] == ["runs.manifest_invalid"]
    assert "Invalid encoding" in report.issues[0].message


@pytest.mark.parametrize("table", _REQUIRED_MANIFEST_TABLES)
def test_project_lint_reports_each_missing_required_manifest_table(
    tmp_path: Path,
    table: str,
) -> None:
    _write_project(tmp_path)
    run_dir = tmp_path / "runs" / "R20260508-0001"
    manifest = _canonical_manifest(
        run_dir,
        "R20260508-0001",
        "created",
    ).to_dict()
    del manifest[table]
    _write_manifest_dict(run_dir, manifest)

    report = run_project_lint(tmp_path, scopes=("runs",))

    issue = next(
        issue
        for issue in report.issues
        if issue.issue_id == "runs.manifest_table_missing"
    )
    assert f"[{table}]" in issue.message


@pytest.mark.parametrize(("table", "field"), _REQUIRED_MANIFEST_FIELDS)
def test_project_lint_reports_each_missing_required_manifest_field(
    tmp_path: Path,
    table: str,
    field: str,
) -> None:
    _write_project(tmp_path)
    run_dir = tmp_path / "runs" / "R20260508-0001"
    manifest = _canonical_manifest(
        run_dir,
        "R20260508-0001",
        "created",
    ).to_dict()
    del manifest[table][field]
    _write_manifest_dict(run_dir, manifest)

    report = run_project_lint(tmp_path, scopes=("runs",))

    issue = next(
        issue
        for issue in report.issues
        if issue.issue_id == "runs.manifest_field_missing"
    )
    assert f"[{table}].{field}" in issue.message


@pytest.mark.parametrize(("table", "field"), _REQUIRED_MANIFEST_FIELDS)
def test_project_lint_reports_each_invalid_required_manifest_field_type(
    tmp_path: Path,
    table: str,
    field: str,
) -> None:
    _write_project(tmp_path)
    run_dir = tmp_path / "runs" / "R20260508-0001"
    manifest = _canonical_manifest(
        run_dir,
        "R20260508-0001",
        "created",
    ).to_dict()
    manifest[table][field] = 42
    _write_manifest_dict(run_dir, manifest)

    report = run_project_lint(tmp_path, scopes=("runs",))

    issue = next(
        issue for issue in report.issues if issue.issue_id == "runs.manifest_field_type"
    )
    assert f"[{table}].{field}" in issue.message


@pytest.mark.parametrize("table", _REQUIRED_MANIFEST_TABLES)
def test_project_lint_reports_each_invalid_required_manifest_table_type(
    tmp_path: Path,
    table: str,
) -> None:
    _write_project(tmp_path)
    run_dir = tmp_path / "runs" / "R20260508-0001"
    manifest = _canonical_manifest(
        run_dir,
        "R20260508-0001",
        "created",
    ).to_dict()
    manifest[table] = "not-a-table"
    _write_manifest_dict(run_dir, manifest)

    report = run_project_lint(tmp_path, scopes=("runs",))

    assert [issue.issue_id for issue in report.issues] == ["runs.manifest_invalid"]
    assert f"{table!r} must be a TOML table" in report.issues[0].message


def test_project_lint_keeps_sparse_legacy_manifest_readable(tmp_path: Path) -> None:
    _write_project(tmp_path)
    run_dir = tmp_path / "runs" / "R20260508-0001"
    _write_manifest_dict(
        run_dir,
        {"run": {"id": "R20260508-0001", "status": "created"}},
    )

    manifest = read_manifest(run_dir)
    report = run_project_lint(tmp_path, scopes=("runs",))

    assert manifest.run == {"id": "R20260508-0001", "status": "created"}
    assert "runs.manifest_invalid" not in {issue.issue_id for issue in report.issues}
    assert (
        sum(issue.issue_id == "runs.manifest_table_missing" for issue in report.issues)
        == 6
    )


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


def test_project_lint_reports_oversized_current_state(tmp_path: Path) -> None:
    _write_project(tmp_path)
    (tmp_path / "research" / "CURRENT.md").write_text(
        "x" * 20_001,
        encoding="utf-8",
    )

    report = run_project_lint(tmp_path, scopes=("knowledge",))

    assert any(
        issue.issue_id == "knowledge.current.too_large" for issue in report.issues
    )


def test_project_lint_warns_when_current_state_exceeds_line_guidance(
    tmp_path: Path,
) -> None:
    _write_project(tmp_path)
    (tmp_path / "research" / "CURRENT.md").write_text(
        "\n".join(f"line {index}" for index in range(51)) + "\n",
        encoding="utf-8",
    )

    report = run_project_lint(tmp_path, scopes=("knowledge",))

    issue = next(
        issue
        for issue in report.issues
        if issue.issue_id == "knowledge.current.too_many_lines"
    )
    assert issue.severity == "warning"
    assert "research/results" in issue.recommendation
    assert report.status == "warning"


def test_project_lint_warns_for_dispersed_experiment_narratives(
    tmp_path: Path,
) -> None:
    _write_project(tmp_path)
    case = tmp_path / "cases" / "base"
    case.mkdir(parents=True)
    (case / "case.toml").write_text("[case]\nname = 'base'\n", encoding="utf-8")
    (case / "notes.md").write_text("trial notes\n", encoding="utf-8")
    (case / "idea.md").write_text("another trial\n", encoding="utf-8")
    (case / "AGENTS.md").write_text("policy\n", encoding="utf-8")

    survey = tmp_path / "runs" / "scan"
    survey.mkdir(parents=True)
    (survey / "survey.toml").write_text("[survey]\nid = 'scan'\n", encoding="utf-8")
    (survey / "notes.md").write_text("survey notes\n", encoding="utf-8")
    (survey / "summary").mkdir()
    (survey / "summary" / "survey_summary.md").write_text(
        "generated report\n", encoding="utf-8"
    )

    run_dir = survey / "R20260801-0001"
    (run_dir / "analysis").mkdir(parents=True)
    (run_dir / "manifest.toml").write_text(
        '[run]\nid = "R20260801-0001"\nstatus = "created"\n',
        encoding="utf-8",
    )
    (run_dir / "analysis" / "notes.md").write_text(
        "run analysis notes\n", encoding="utf-8"
    )
    (run_dir / "analysis" / "tmp-summary-v2.md").write_text(
        "temporary summary\n", encoding="utf-8"
    )

    top_notes = tmp_path / "notes" / "experiment-alpha.md"
    top_notes.parent.mkdir()
    top_notes.write_text("old experiment note\n", encoding="utf-8")
    top_analysis = tmp_path / "analysis" / "analysis-notes.md"
    top_analysis.parent.mkdir()
    top_analysis.write_text("cross-run narrative\n", encoding="utf-8")
    experiment_note = tmp_path / "experiments" / "E20260801-0001-notes.md"
    experiment_note.parent.mkdir()
    experiment_note.write_text("experiment prose\n", encoding="utf-8")
    scratch_note = tmp_path / "scratch" / "renamed-observation.md"
    scratch_note.parent.mkdir()
    scratch_note.write_text("scratch prose\n", encoding="utf-8")
    (tmp_path / "idea.md").write_text("root idea\n", encoding="utf-8")
    disguised = tmp_path / "scratch" / "README.md"
    disguised.write_text("disguised experiment prose\n", encoding="utf-8")
    nested_journal = tmp_path / "research" / "journal" / "topic" / "note.md"
    nested_journal.parent.mkdir(parents=True)
    nested_journal.write_text("unbounded journal branch\n", encoding="utf-8")

    for path in (
        tmp_path / "docs" / "notes.md",
        tmp_path / "_handoff" / "new_rules.md",
        tmp_path / "materials" / "README.md",
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("allowed markdown\n", encoding="utf-8")

    report = run_project_lint(tmp_path, scopes=("knowledge",))
    narrative_issues = [
        issue
        for issue in report.issues
        if issue.issue_id == "knowledge.dispersed_experiment_narrative"
    ]

    actual_paths = {
        issue.path.relative_to(tmp_path).as_posix() for issue in narrative_issues
    }
    assert actual_paths == {
        "analysis/analysis-notes.md",
        "cases/base/idea.md",
        "cases/base/notes.md",
        "experiments/E20260801-0001-notes.md",
        "idea.md",
        "notes/experiment-alpha.md",
        "research/journal/topic/note.md",
        "runs/scan/notes.md",
        "runs/scan/R20260801-0001/analysis/notes.md",
        "runs/scan/R20260801-0001/analysis/tmp-summary-v2.md",
        "scratch/renamed-observation.md",
        "scratch/README.md",
    }
    assert all(issue.severity == "warning" for issue in narrative_issues)


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
