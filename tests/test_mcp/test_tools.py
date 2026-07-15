"""Tests for runops MCP tool implementations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from runops.application.execution.submission import SubmitRequest, plan_submit
from runops.core.manifest import ManifestData, write_manifest
from runops.mcp import tools
from runops.mcp._tools import project as project_tools


def _make_project(tmp_path: Path) -> Path:
    (tmp_path / "runops.toml").write_text(
        '[project]\nname = "mcp-demo"\ndescription = "demo"\n',
        encoding="utf-8",
    )
    (tmp_path / "simulators.toml").write_text("[simulators]\n", encoding="utf-8")
    (tmp_path / "launchers.toml").write_text("[launchers]\n", encoding="utf-8")
    (tmp_path / "runs").mkdir()
    return tmp_path


def _make_run(
    project_root: Path,
    *,
    status: str = "created",
    job_id: str = "12345",
) -> Path:
    run_dir = project_root / "runs" / "R20260512-0001"
    (run_dir / "submit").mkdir(parents=True)
    (run_dir / "input").mkdir()
    (run_dir / "input" / "params.toml").write_text("x = 1\n", encoding="utf-8")
    (run_dir / "work").mkdir()
    (run_dir / "submit" / "job.sh").write_text(
        "#!/bin/bash\n#SBATCH -t 00:10:00\npython simulate.py\n",
        encoding="utf-8",
    )
    write_manifest(
        run_dir,
        ManifestData(
            run={
                "id": "R20260512-0001",
                "display_name": "demo-run",
                "status": status,
            },
            origin={"case": "demo_case", "survey": ""},
            simulator={"name": "generic", "adapter": "generic"},
            job={
                "scheduler": "slurm",
                "job_id": job_id,
                "partition": "debug",
                "walltime": "00:10:00",
            },
            classification={"tags": ["smoke"]},
        ),
        log_event=False,
    )
    return run_dir


def _make_survey(project_root: Path) -> Path:
    survey_dir = project_root / "runs" / "angle_scan"
    run_dir = survey_dir / "R20260512-0002"
    (run_dir / "analysis").mkdir(parents=True)
    (run_dir / "work").mkdir()
    write_manifest(
        run_dir,
        ManifestData(
            run={
                "id": "R20260512-0002",
                "display_name": "survey-run",
                "status": "completed",
            },
            origin={"case": "demo_case", "survey": "angle_scan"},
            simulator={"name": "generic", "adapter": "generic"},
            classification={"tags": ["survey"]},
        ),
        log_event=False,
    )
    return survey_dir


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_health_returns_contract_envelope() -> None:
    result = tools.health()

    assert result["contract_version"] == "0.1"
    assert result["provider"] == "runops"
    assert result["tool"] == "runops.health"
    assert result["status"] == "ok"
    assert result["data"]["healthy"] is True


def test_provider_info_exposes_codex_plugin_policy() -> None:
    result = tools.provider_info()

    policy = result["data"]["codex_plugin_policy"]
    assert policy["recommendations_advisory"] is True
    assert policy["metadata_checks_supported"] is True
    assert policy["installs_plugins"] is False
    assert policy["enables_plugins"] is False
    assert policy["inspects_user_install_state"] is False
    assert policy["inventory_schema_version"] == 1
    assert policy["inventory_schema"] == "schemas/codex-plugin-inventory.json"
    assert policy["check_result_schema"] == "schemas/codex-plugin-check-result.json"
    assert policy["project_tool"] == "runops.project.plugins"
    assert "recommendations" in policy["inventory_fields"]
    assert "$schema" in policy["inventory_fields"]
    assert "strict_ok" in policy["check_result_fields"]
    assert "$schema" in policy["check_result_fields"]
    assert "sources" in policy["recommendation_fields"]
    assert policy["source_fields"]["sources"] == "machine-readable source label list"


def test_capabilities_exposes_codex_plugin_policy() -> None:
    result = tools.capabilities()

    policy = result["data"]["codex_plugin_policy"]
    assert policy["recommendations_advisory"] is True
    assert policy["metadata_checks_supported"] is True
    assert policy["installs_plugins"] is False
    assert policy["activation_scope"] == "user-local Codex environment"
    assert policy["inventory_schema_version"] == 1
    assert policy["delegated_capabilities_field"] == "delegated_capabilities"


def test_project_status_summarizes_project(tmp_path: Path) -> None:
    project_root = _make_project(tmp_path)
    _make_run(project_root)

    result = tools.project_status(project_root=str(project_root))

    assert result["status"] == "ok"
    assert result["project"]["id"] == "mcp-demo"
    assert result["data"]["runs"]["total"] == 1


def test_project_inspect_includes_codex_plugin_context(tmp_path: Path) -> None:
    """Detailed MCP project context exposes advisory plugin recommendations."""
    project_root = _make_project(tmp_path)
    (project_root / "simulators.toml").write_text(
        "[simulators.emses]\n"
        'adapter = "emses"\n'
        'resolver_mode = "package"\n'
        'executable = "mpiemses3D"\n',
        encoding="utf-8",
    )

    result = tools.project_inspect(project_root=str(project_root))

    assert result["status"] == "ok"
    plugins = result["data"]["context"]["codex_plugins"]
    assert plugins["management"]["runops_installs_plugins"] is False
    assert [plugin["name"] for plugin in plugins["recommendations"]] == [
        "mpiemses3d-context",
        "emout-context",
    ]
    assert plugins["recommendations"][0]["sources"] == ["simulator:emses"]


def test_project_plugins_returns_advisory_check_result(tmp_path: Path) -> None:
    """MCP exposes plugin recommendations and metadata checks directly."""
    project_root = _make_project(tmp_path)
    (project_root / "simulators.toml").write_text(
        "[simulators.emses]\n"
        'adapter = "emses"\n'
        'resolver_mode = "package"\n'
        'executable = "mpiemses3D"\n',
        encoding="utf-8",
    )

    result = tools.project_plugins(project_root=str(project_root))

    assert result["status"] == "ok"
    assert result["tool"] == "runops.project.plugins"
    assert result["data"]["$schema"] == "schemas/codex-plugin-check-result.json"
    assert result["data"]["schema_version"] == 1
    assert result["data"]["ok"] is True
    assert result["data"]["strict_ok"] is True
    assert result["data"]["inventory"]["$schema"] == (
        "schemas/codex-plugin-inventory.json"
    )
    assert result["data"]["inventory"]["management"]["runops_installs_plugins"] is False
    assert result["data"]["inventory"]["delegated_capabilities"][
        "parameter-design"
    ] == ["mpiemses3d-context"]
    assert [
        plugin["name"] for plugin in result["data"]["inventory"]["recommendations"]
    ] == [
        "mpiemses3d-context",
        "emout-context",
    ]
    assert result["data"]["inventory"]["recommendations"][0]["sources"] == [
        "simulator:emses"
    ]


def test_project_plugins_reports_metadata_errors(tmp_path: Path) -> None:
    """Incomplete plugin metadata is surfaced as MCP errors."""
    project_root = _make_project(tmp_path)
    (project_root / "site.toml").write_text(
        '[site]\nname = "test-site"\n'
        "[site.codex_plugins.incomplete]\n"
        'display_name = "Incomplete Plugin"\n',
        encoding="utf-8",
    )

    result = tools.project_plugins(project_root=str(project_root))

    assert result["status"] == "error"
    assert result["data"]["ok"] is False
    assert result["data"]["summary"]["errors"] == 2
    assert [item["code"] for item in result["errors"]] == [
        "codex_plugin_metadata_error",
        "codex_plugin_metadata_error",
    ]


def test_project_plugins_strict_reports_warning_only_checks(
    tmp_path: Path,
) -> None:
    """Strict mode keeps warning-only checks visible for MCP clients."""
    project_root = _make_project(tmp_path)
    (project_root / "site.toml").write_text(
        '[site]\nname = "test-site"\n'
        "[site.codex_plugins.site-context]\n"
        'display_name = "Site Context"\n'
        'reason = "Site-local workflow guidance."\n'
        'install_hint = "codex plugin add site-context@test"\n'
        'visibility = "private"\n',
        encoding="utf-8",
    )

    result = tools.project_plugins(project_root=str(project_root), strict=True)

    assert result["status"] == "warning"
    assert result["data"]["ok"] is True
    assert result["data"]["strict_ok"] is False
    assert result["data"]["strict"] is True
    assert result["warnings"][0]["severity"] == "high"


def test_project_plugins_warns_when_adapter_recommendations_cannot_be_collected(
    tmp_path: Path,
) -> None:
    """MCP surfaces missing external adapters as advisory collection warnings."""
    project_root = _make_project(tmp_path)
    (project_root / "simulators.toml").write_text(
        "[simulators.production]\n"
        'adapter = "missing_external"\n'
        'resolver_mode = "package"\n'
        'executable = "missing-solver"\n',
        encoding="utf-8",
    )

    result = tools.project_plugins(project_root=str(project_root))

    assert result["status"] == "warning"
    assert result["data"]["ok"] is True
    assert result["data"]["strict_ok"] is False
    assert result["data"]["issues"][0]["field"] == "adapter"
    assert result["warnings"][0]["code"] == "codex_plugin_metadata_warning"
    assert "missing_external.adapter" in result["warnings"][0]["message"]


def test_project_doctor_reports_codex_plugin_metadata_errors(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    """MCP doctor includes project-side Codex plugin recommendation checks."""
    project_root = _make_project(tmp_path)
    (project_root / "site.toml").write_text(
        '[site]\nname = "test-site"\n'
        "[site.codex_plugins.incomplete]\n"
        'display_name = "Incomplete Plugin"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(project_tools.shutil, "which", lambda _cmd: "/usr/bin/sbatch")

    result = tools.project_doctor(project_root=str(project_root))

    assert result["status"] == "warning"
    checks = {check["name"]: check for check in result["data"]["checks"]}
    assert checks["codex_plugins"]["ok"] is False
    assert "2 error(s)" in checks["codex_plugins"]["message"]


def test_run_list_filters_by_status_and_tag(tmp_path: Path) -> None:
    project_root = _make_project(tmp_path)
    _make_run(project_root)

    result = tools.run_list(
        project_root=str(project_root),
        status_filter="created",
        tag="smoke",
    )

    assert result["status"] == "ok"
    assert result["data"]["matched_count"] == 1
    assert result["data"]["runs"][0]["run_id"] == "R20260512-0001"


def test_run_logs_returns_latest_log_tail(tmp_path: Path) -> None:
    project_root = _make_project(tmp_path)
    run_dir = _make_run(project_root)
    (run_dir / "work" / "12345.out").write_text(
        "line 1\nline 2\nline 3\n",
        encoding="utf-8",
    )

    result = tools.run_logs(
        "R20260512-0001",
        project_root=str(project_root),
        lines=2,
    )

    assert result["status"] == "ok"
    assert result["data"]["lines"] == ["line 2", "line 3"]


def test_job_plan_submit_reports_sbatch_command(tmp_path: Path) -> None:
    project_root = _make_project(tmp_path)
    run_dir = _make_run(project_root, job_id="")
    plan = plan_submit(
        SubmitRequest(
            run_dir=run_dir,
            queue_name="debug",
            qos="normal",
            afterok="111",
        )
    )
    before = (run_dir / "manifest.toml").read_bytes()

    result = tools.job_plan_submit(
        "R20260512-0001",
        project_root=str(project_root),
        queue_name="debug",
        qos="normal",
        afterok="111",
    )

    assert result["status"] == "ok"
    assert result["data"]["will_submit"] is True
    assert result["data"] == {
        "run_id": plan.run_id,
        "run_dir": str(plan.run_dir),
        "job_script": str(plan.job_script),
        "work_dir": str(plan.work_dir),
        "command": list(plan.command),
        "preconditions": [
            {"name": check.name, "ok": check.passed, "message": check.message}
            for check in plan.preconditions
        ],
        "warnings": list(plan.warnings),
        "dry_run": True,
        "will_submit": plan.ready,
    }
    assert result["next_actions"][0]["arguments"]["run"] == plan.run_id
    assert (run_dir / "manifest.toml").read_bytes() == before
    assert not (run_dir / "status").exists()


def test_job_plan_submit_blocks_with_every_failed_shared_check(tmp_path: Path) -> None:
    project_root = _make_project(tmp_path)
    run_dir = _make_run(project_root, status="running")
    (run_dir / "submit" / "job.sh").unlink()
    for input_file in (run_dir / "input").iterdir():
        input_file.unlink()
    plan = plan_submit(SubmitRequest(run_dir=run_dir))
    before = (run_dir / "manifest.toml").read_bytes()

    result = tools.job_plan_submit(
        "R20260512-0001",
        project_root=str(project_root),
    )

    assert len(plan.failed_preconditions) == 6
    assert result["status"] == "blocked"
    assert result["data"]["will_submit"] is False
    assert result["data"]["command"] == list(plan.command)
    assert result["data"]["preconditions"] == [
        {"name": check.name, "ok": check.passed, "message": check.message}
        for check in plan.preconditions
    ]
    assert [item["code"] for item in result["errors"]] == ["precondition_failed"] * len(
        plan.failed_preconditions
    )
    assert (run_dir / "manifest.toml").read_bytes() == before
    assert not (run_dir / "status").exists()


def test_job_plan_submit_blocks_non_created_run(tmp_path: Path) -> None:
    project_root = _make_project(tmp_path)
    _make_run(project_root, status="running")

    result = tools.job_plan_submit("R20260512-0001", project_root=str(project_root))

    assert result["status"] == "blocked"
    assert result["data"]["will_submit"] is False
    assert result["errors"][0]["code"] == "precondition_failed"


def test_publication_exports_list_and_inspect_manifest(tmp_path: Path) -> None:
    project_root = _make_project(tmp_path)
    export_dir = project_root / "exports" / "papers" / "draft-a" / "fig2-baseline"
    _write_json(
        export_dir / "manifest.json",
        {
            "schema_version": 2,
            "paper_id": "draft-a",
            "export_name": "fig2-baseline",
            "target_kind": "run",
            "created_at": "2026-05-14T00:00:00+00:00",
            "source_run_ids": ["R20260512-0001"],
            "paper": {"id": "draft-a", "slug": "draft-a"},
            "export": {
                "id": "draft-a/fig2-baseline",
                "name": "fig2-baseline",
                "created_at": "2026-05-14T00:00:00+00:00",
            },
            "source": {"kind": "run", "run_count": 1},
            "files": [
                {
                    "role": "run_summary",
                    "source_path": "runs/R20260512-0001/analysis/summary.json",
                    "export_path": "files/summary.json",
                }
            ],
            "warnings": [],
        },
    )
    (export_dir / "README.md").write_text("# Export\n", encoding="utf-8")

    listing = tools.publication_exports_list(
        project_root=str(project_root),
        paper_id="draft-a",
    )
    inspected = tools.publication_export_inspect(
        project_root=str(project_root),
        export="draft-a/fig2-baseline",
    )

    assert listing["status"] == "ok"
    assert listing["data"]["matched_count"] == 1
    assert listing["data"]["exports"][0]["id"] == "draft-a/fig2-baseline"
    assert inspected["status"] == "ok"
    assert inspected["data"]["export"]["source_run_ids"] == ["R20260512-0001"]
    assert inspected["data"]["files"][0]["role"] == "run_summary"


def test_publication_exports_list_reports_broken_manifest(tmp_path: Path) -> None:
    project_root = _make_project(tmp_path)
    export_dir = project_root / "exports" / "papers" / "draft-a" / "broken"
    export_dir.mkdir(parents=True)
    (export_dir / "manifest.json").write_text("{bad json", encoding="utf-8")

    result = tools.publication_exports_list(project_root=str(project_root))

    assert result["status"] == "warning"
    assert result["data"]["exports"][0]["valid"] is False
    assert result["warnings"][0]["code"] == "manifest_invalid"


def test_analysis_artifacts_reads_run_index(tmp_path: Path) -> None:
    project_root = _make_project(tmp_path)
    run_dir = _make_run(project_root)
    (run_dir / "analysis" / "figures").mkdir(parents=True)
    (run_dir / "analysis" / "figures" / "phi.png").write_bytes(b"png")
    (run_dir / "analysis" / "artifacts.toml").write_text(
        """
schema_version = 1
scope = "run"
generated_by = "test"

[[artifacts]]
kind = "figure"
path = "figures/phi.png"
title = "Potential"
status = "draft"
""".lstrip(),
        encoding="utf-8",
    )

    result = tools.analysis_artifacts(
        "R20260512-0001",
        project_root=str(project_root),
        kind="figure",
    )

    assert result["status"] == "ok"
    assert result["data"]["matched_count"] == 1
    artifact = result["data"]["artifacts"][0]
    assert artifact["title"] == "Potential"
    assert artifact["project_relative_path"].endswith(
        "runs/R20260512-0001/analysis/figures/phi.png"
    )


def test_survey_summary_and_plot_columns_read_existing_summary(tmp_path: Path) -> None:
    project_root = _make_project(tmp_path)
    survey_dir = _make_survey(project_root)
    _write_json(
        survey_dir / "summary" / "survey_summary.json",
        {
            "total_runs": 1,
            "summaries_collected": 1,
            "missing_summaries": 0,
            "state_counts": {"completed": 1},
            "readiness_counts": {"ready": 1},
            "numeric_stats": {"metric.alpha": {"count": 1.0, "mean": 0.5}},
            "readiness_issues": [],
            "warnings": [],
            "runs": [
                {
                    "run_id": "R20260512-0002",
                    "display_name": "survey-run",
                    "status": "completed",
                    "analysis_status": "ready",
                    "analysis_ready": True,
                    "flat_summary": {"metric.alpha": 0.5},
                    "flat_metadata": {"param.angle": 30},
                }
            ],
        },
    )

    summary = tools.survey_summary(
        "runs/angle_scan",
        project_root=str(project_root),
        include_runs=True,
    )
    columns = tools.analysis_plot_columns(
        "runs/angle_scan",
        project_root=str(project_root),
    )

    assert summary["status"] == "ok"
    assert summary["data"]["run_count"] == 1
    assert summary["data"]["runs"][0]["run_id"] == "R20260512-0002"
    assert columns["status"] == "ok"
    assert "metric.alpha" in columns["data"]["columns"]
    assert "param.angle" in columns["data"]["columns"]
