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
