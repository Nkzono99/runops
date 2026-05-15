"""Tests for runops MCP tool implementations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from runops.core.manifest import ManifestData, write_manifest
from runops.mcp import tools


def _make_project(tmp_path: Path) -> Path:
    (tmp_path / "runops.toml").write_text(
        '[project]\nname = "mcp-demo"\ndescription = "demo"\n',
        encoding="utf-8",
    )
    (tmp_path / "simulators.toml").write_text("[simulators]\n", encoding="utf-8")
    (tmp_path / "launchers.toml").write_text("[launchers]\n", encoding="utf-8")
    (tmp_path / "runs").mkdir()
    return tmp_path


def _make_run(project_root: Path, *, status: str = "created") -> Path:
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
                "job_id": "12345",
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


def _paper_request_kwargs(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "request_type": "analysis_request",
        "title": "Add sheath width comparison",
        "paper_context": "Results / Figure 2",
        "desired_artifact": "comparison table",
        "source_link": "refs/links.toml#paper.draft-a",
        "paper_id": "draft-a",
        "priority": "medium",
        "related_runs": ["R20260512-0002"],
        "human_gate": True,
    }
    data.update(overrides)
    return data


def test_health_returns_contract_envelope() -> None:
    result = tools.health()

    assert result["contract_version"] == "0.1"
    assert result["provider"] == "runops"
    assert result["tool"] == "runops.health"
    assert result["status"] == "ok"
    assert result["data"]["healthy"] is True


def test_project_status_summarizes_project(tmp_path: Path) -> None:
    project_root = _make_project(tmp_path)
    _make_run(project_root)

    result = tools.project_status(project_root=str(project_root))

    assert result["status"] == "ok"
    assert result["project"]["id"] == "mcp-demo"
    assert result["data"]["runs"]["total"] == 1


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
    _make_run(project_root)

    result = tools.job_plan_submit(
        "R20260512-0001",
        project_root=str(project_root),
        queue_name="debug",
        qos="normal",
        afterok="111",
    )

    assert result["status"] == "ok"
    assert result["data"]["will_submit"] is True
    assert result["data"]["command"][:2] == [
        "sbatch",
        f"--chdir={project_root / 'runs' / 'R20260512-0001' / 'work'}",
    ]
    assert "--dependency=afterok:111" in result["data"]["command"]
    assert "--partition=debug" in result["data"]["command"]
    assert "--qos=normal" in result["data"]["command"]


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


def test_paper_requests_list_and_plan(tmp_path: Path) -> None:
    project_root = _make_project(tmp_path)
    (project_root / "research").mkdir()
    (project_root / "research" / "paper_requests.toml").write_text(
        """
schema_version = 1

[[requests]]
id = "PAPER-REQ-0001"
type = "experiment_request"
title = "Run one more angle"
paper_id = "draft-a"
paper_context = "Results section"
desired_artifact = "comparison table"
source_link = "refs/links.toml#paper.draft-a"
priority = "high"
status = "open"
related_runs = ["R20260512-0002"]
human_gate = true
""".lstrip(),
        encoding="utf-8",
    )

    listing = tools.paper_requests_list(
        project_root=str(project_root),
        paper_id="draft-a",
    )
    plan = tools.paper_request_plan(
        "PAPER-REQ-0001",
        project_root=str(project_root),
    )

    assert listing["status"] == "ok"
    assert listing["data"]["matched_count"] == 1
    assert listing["data"]["requests"][0]["priority"] == "high"
    assert plan["status"] == "ok"
    assert plan["data"]["route"] == "research/proposals/"
    assert plan["data"]["will_submit"] is False


def test_paper_requests_list_accepts_empty_queue(tmp_path: Path) -> None:
    project_root = _make_project(tmp_path)
    (project_root / "research").mkdir()
    (project_root / "research" / "paper_requests.toml").write_text(
        "schema_version = 1\n",
        encoding="utf-8",
    )

    listing = tools.paper_requests_list(project_root=str(project_root))

    assert listing["status"] == "ok"
    assert listing["data"]["matched_count"] == 0
    assert listing["data"]["requests"] == []


def test_paper_request_draft_accepts_empty_queue(tmp_path: Path) -> None:
    project_root = _make_project(tmp_path)
    (project_root / "research").mkdir()
    (project_root / "research" / "paper_requests.toml").write_text(
        "schema_version = 1\n",
        encoding="utf-8",
    )

    result = tools.paper_request_draft(
        project_root=str(project_root),
        **_paper_request_kwargs(request_type="figure_request"),
    )

    assert result["status"] == "ok"
    assert result["data"]["valid"] is True
    assert result["data"]["request"]["id"] == "PAPER-REQ-0001"
    assert result["data"]["request"]["type"] == "figure_request"
    assert result["data"]["existing_queue"]["request_count"] == 0
    assert result["data"]["will_mutate_files"] is False
    assert "[[requests]]" in result["data"]["toml_snippet"]
    assert 'type = "figure_request"' in result["data"]["toml_snippet"]


def test_paper_request_draft_uses_next_id_for_existing_queue(tmp_path: Path) -> None:
    project_root = _make_project(tmp_path)
    (project_root / "research").mkdir()
    (project_root / "research" / "paper_requests.toml").write_text(
        """
schema_version = 1

[[requests]]
id = "PAPER-REQ-0001"
type = "analysis_request"
title = "Existing request"
paper_context = "Results"
desired_artifact = "table"
source_link = "refs/links.toml#paper.draft-a"
priority = "medium"
status = "open"
""".lstrip(),
        encoding="utf-8",
    )

    result = tools.paper_request_draft(
        project_root=str(project_root),
        **_paper_request_kwargs(),
    )

    assert result["status"] == "ok"
    assert result["data"]["request"]["id"] == "PAPER-REQ-0002"
    assert result["data"]["existing_queue"]["exists"] is True
    assert result["data"]["existing_queue"]["request_count"] == 1


def test_paper_request_draft_warns_on_duplicate_id(tmp_path: Path) -> None:
    project_root = _make_project(tmp_path)
    (project_root / "research").mkdir()
    (project_root / "research" / "paper_requests.toml").write_text(
        """
schema_version = 1

[[requests]]
id = "PAPER-REQ-0001"
type = "analysis_request"
title = "Existing request"
paper_context = "Results"
desired_artifact = "table"
source_link = "refs/links.toml#paper.draft-a"
priority = "medium"
status = "open"
""".lstrip(),
        encoding="utf-8",
    )

    result = tools.paper_request_draft(
        project_root=str(project_root),
        **_paper_request_kwargs(request_id="PAPER-REQ-0001"),
    )

    assert result["status"] == "warning"
    assert result["data"]["valid"] is True
    assert result["data"]["existing_queue"]["duplicate_id"] is True
    assert result["warnings"][0]["code"] == "paper_request_duplicate_id"


def test_paper_request_draft_reports_invalid_enums(tmp_path: Path) -> None:
    project_root = _make_project(tmp_path)
    (project_root / "research").mkdir()
    (project_root / "research" / "paper_requests.toml").write_text(
        "schema_version = 1\n",
        encoding="utf-8",
    )

    result = tools.paper_request_draft(
        project_root=str(project_root),
        **_paper_request_kwargs(
            request_type="bad_type",
            priority="immediate",
            status="waiting",
        ),
    )

    error_codes = {item["code"] for item in result["errors"]}
    assert result["status"] == "warning"
    assert result["data"]["valid"] is False
    assert result["data"]["toml_snippet"] == ""
    assert "paper_request_invalid_type" in error_codes
    assert "paper_request_invalid_priority" in error_codes
    assert "paper_request_invalid_status" in error_codes
