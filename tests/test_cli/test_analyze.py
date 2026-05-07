"""Tests for runops analyze summarize/collect/plot commands."""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import tomli_w
from typer.testing import CliRunner

from runops.cli.main import app
from runops.core.analysis import ResolvedSurveyPlotRecipe, SurveyPlotRecipe

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

runner = CliRunner()

ADAPTER_PATCH = "runops.core.analysis.workflow.get_adapter"
_PROJECT_TOML: dict[str, Any] = {"project": {"name": "test-project"}}


def _write_project_file(project_root: Path) -> None:
    with open(project_root / "runops.toml", "wb") as f:
        tomli_w.dump(_PROJECT_TOML, f)


def _create_run(
    parent: Path,
    run_id: str,
    *,
    status: str = "completed",
    simulator_name: str = "test_sim",
    adapter_name: str = "test_adapter",
) -> Path:
    """Create a minimal run directory with manifest.toml."""
    run_dir = parent / run_id
    run_dir.mkdir(parents=True)
    for sub in ("input", "submit", "work", "analysis", "status"):
        (run_dir / sub).mkdir()

    manifest: dict[str, Any] = {
        "run": {
            "id": run_id,
            "display_name": "test run",
            "status": status,
        },
        "simulator": {
            "name": simulator_name,
            "adapter": adapter_name,
        },
    }
    with open(run_dir / "manifest.toml", "wb") as f:
        tomli_w.dump(manifest, f)
    return run_dir


class TestNewComparison:
    def test_new_comparison_creates_workspace(self, tmp_path: Path) -> None:
        _write_project_file(tmp_path)
        run_dir = _create_run(tmp_path / "runs", "R20260501-0001")

        with patch("runops.cli.analyze.Path.cwd", return_value=tmp_path):
            result = runner.invoke(
                app,
                [
                    "analyze",
                    "new-comparison",
                    "Landau model comparison",
                    "--source",
                    str(run_dir),
                ],
            )

        assert result.exit_code == 0, result.output
        comparison_dir = tmp_path / "analysis" / "cross_run" / "landau-model-comparison"
        assert comparison_dir.is_dir()
        assert (comparison_dir / "scripts" / ".gitkeep").is_file()
        assert (comparison_dir / "data" / ".gitkeep").is_file()
        assert (comparison_dir / "figures" / ".gitkeep").is_file()
        with open(comparison_dir / "manifest.toml", "rb") as f:
            manifest = tomllib.load(f)
        assert manifest["comparison"]["id"] == "landau-model-comparison"
        assert manifest["sources"][0]["kind"] == "run"
        assert manifest["sources"][0]["run_id"] == "R20260501-0001"
        assert "Comparison workspace created" in result.output

    def test_new_comparison_reports_duplicate_workspace(self, tmp_path: Path) -> None:
        _write_project_file(tmp_path)
        comparison_dir = tmp_path / "analysis" / "cross_run" / "existing"
        comparison_dir.mkdir(parents=True)

        with patch("runops.cli.analyze.Path.cwd", return_value=tmp_path):
            result = runner.invoke(
                app,
                ["analyze", "new-comparison", "Existing", "--id", "existing"],
            )

        assert result.exit_code == 1
        assert "already exists" in result.output


class TestSummarize:
    def test_summarize_success(self, tmp_path: Path) -> None:
        run_dir = _create_run(tmp_path, "R20260327-0001")

        mock_adapter = MagicMock()
        mock_adapter.summarize.return_value = {"energy": 42.0, "steps": 1000}

        mock_adapter_cls = MagicMock(return_value=mock_adapter)

        with patch(ADAPTER_PATCH, return_value=mock_adapter_cls):
            result = runner.invoke(app, ["analyze", "summarize", str(run_dir)])

        assert result.exit_code == 0
        assert "Summary written" in result.output

        summary_path = run_dir / "analysis" / "summary.json"
        assert summary_path.exists()
        with open(summary_path) as f:
            data = json.load(f)
        assert data["energy"] == 42.0
        assert data["steps"] == 1000

    def test_summarize_no_adapter(self, tmp_path: Path) -> None:
        run_dir = _create_run(tmp_path, "R20260327-0001")

        with patch(
            ADAPTER_PATCH,
            side_effect=KeyError("not found"),
        ):
            result = runner.invoke(app, ["analyze", "summarize", str(run_dir)])

        assert result.exit_code == 1

    def test_summarize_nonexistent_run(self) -> None:
        result = runner.invoke(app, ["analyze", "summarize", "/nonexistent/run"])
        assert result.exit_code == 1
        assert "Error" in result.output

    def test_summarize_no_simulator_in_manifest(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "R20260327-0001"
        run_dir.mkdir(parents=True)
        for sub in ("input", "submit", "work", "analysis", "status"):
            (run_dir / sub).mkdir()

        manifest: dict[str, Any] = {
            "run": {"id": "R20260327-0001", "status": "completed"},
        }
        with open(run_dir / "manifest.toml", "wb") as f:
            tomli_w.dump(manifest, f)

        result = runner.invoke(app, ["analyze", "summarize", str(run_dir)])
        assert result.exit_code == 1
        out = result.output.lower()
        assert "simulator" in out or "adapter" in out

    def test_summarize_with_case_script(self, tmp_path: Path) -> None:
        """Case-level summarize.py extends the adapter summary."""
        # Project root with runops.toml
        with open(tmp_path / "runops.toml", "wb") as f:
            tomli_w.dump(_PROJECT_TOML, f)

        # Case script
        case_dir = tmp_path / "cases" / "mycase"
        case_dir.mkdir(parents=True)
        (case_dir / "summarize.py").write_text(
            textwrap.dedent("""\
                def summarize(run_dir, base_summary):
                    base_summary["custom_metric"] = 99.9
                    return base_summary
            """),
            encoding="utf-8",
        )

        # Run directory
        runs_dir = tmp_path / "runs"
        run_dir = _create_run(runs_dir, "R20260327-0001")

        # Patch manifest to include origin.case
        manifest: dict[str, Any] = {
            "run": {"id": "R20260327-0001", "status": "completed"},
            "origin": {"case": "mycase"},
            "simulator": {"name": "test_sim", "adapter": "test_adapter"},
        }
        with open(run_dir / "manifest.toml", "wb") as f:
            tomli_w.dump(manifest, f)

        mock_adapter = MagicMock()
        mock_adapter.summarize.return_value = {"energy": 42.0}
        mock_adapter_cls = MagicMock(return_value=mock_adapter)

        with patch(ADAPTER_PATCH, return_value=mock_adapter_cls):
            result = runner.invoke(app, ["analyze", "summarize", str(run_dir)])

        assert result.exit_code == 0
        assert "Applied script" in result.output

        with open(run_dir / "analysis" / "summary.json") as f:
            data = json.load(f)
        assert data["energy"] == 42.0
        assert data["custom_metric"] == 99.9

    def test_summarize_with_project_script(self, tmp_path: Path) -> None:
        """Project-wide scripts/summarize.py is used when no case script."""
        with open(tmp_path / "runops.toml", "wb") as f:
            tomli_w.dump(_PROJECT_TOML, f)

        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "summarize.py").write_text(
            textwrap.dedent("""\
                def summarize(run_dir, base_summary):
                    base_summary["project_wide"] = True
                    return base_summary
            """),
            encoding="utf-8",
        )

        runs_dir = tmp_path / "runs"
        run_dir = _create_run(runs_dir, "R20260327-0001")

        mock_adapter = MagicMock()
        mock_adapter.summarize.return_value = {"steps": 100}
        mock_adapter_cls = MagicMock(return_value=mock_adapter)

        with patch(ADAPTER_PATCH, return_value=mock_adapter_cls):
            result = runner.invoke(app, ["analyze", "summarize", str(run_dir)])

        assert result.exit_code == 0
        with open(run_dir / "analysis" / "summary.json") as f:
            data = json.load(f)
        assert data["project_wide"] is True

    def test_summarize_case_script_takes_priority(self, tmp_path: Path) -> None:
        """Case script takes priority over project script."""
        with open(tmp_path / "runops.toml", "wb") as f:
            tomli_w.dump(_PROJECT_TOML, f)

        # Both case and project scripts
        case_dir = tmp_path / "cases" / "mycase"
        case_dir.mkdir(parents=True)
        (case_dir / "summarize.py").write_text(
            textwrap.dedent("""\
                def summarize(run_dir, base_summary):
                    base_summary["source"] = "case"
                    return base_summary
            """),
            encoding="utf-8",
        )
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "summarize.py").write_text(
            textwrap.dedent("""\
                def summarize(run_dir, base_summary):
                    base_summary["source"] = "project"
                    return base_summary
            """),
            encoding="utf-8",
        )

        runs_dir = tmp_path / "runs"
        run_dir = _create_run(runs_dir, "R20260327-0001")
        manifest: dict[str, Any] = {
            "run": {"id": "R20260327-0001", "status": "completed"},
            "origin": {"case": "mycase"},
            "simulator": {"adapter": "test_adapter"},
        }
        with open(run_dir / "manifest.toml", "wb") as f:
            tomli_w.dump(manifest, f)

        mock_adapter = MagicMock()
        mock_adapter.summarize.return_value = {}
        mock_adapter_cls = MagicMock(return_value=mock_adapter)

        with patch(ADAPTER_PATCH, return_value=mock_adapter_cls):
            result = runner.invoke(app, ["analyze", "summarize", str(run_dir)])

        assert result.exit_code == 0
        with open(run_dir / "analysis" / "summary.json") as f:
            data = json.load(f)
        assert data["source"] == "case"

    def test_summarize_script_failure_is_warning(self, tmp_path: Path) -> None:
        """A broken script produces a warning, not a fatal error."""
        with open(tmp_path / "runops.toml", "wb") as f:
            tomli_w.dump(_PROJECT_TOML, f)

        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "summarize.py").write_text(
            textwrap.dedent("""\
                def summarize(run_dir, base_summary):
                    raise ValueError("intentional error")
            """),
            encoding="utf-8",
        )

        runs_dir = tmp_path / "runs"
        run_dir = _create_run(runs_dir, "R20260327-0001")

        mock_adapter = MagicMock()
        mock_adapter.summarize.return_value = {"ok": True}
        mock_adapter_cls = MagicMock(return_value=mock_adapter)

        with patch(ADAPTER_PATCH, return_value=mock_adapter_cls):
            result = runner.invoke(app, ["analyze", "summarize", str(run_dir)])

        # Should succeed with adapter summary (script failure is warning)
        assert result.exit_code == 0
        assert "Warning" in result.output or "warning" in result.output.lower()
        with open(run_dir / "analysis" / "summary.json") as f:
            data = json.load(f)
        assert data["ok"] is True

    def test_summarize_with_figures(self, tmp_path: Path) -> None:
        """Script can add figures to the summary."""
        with open(tmp_path / "runops.toml", "wb") as f:
            tomli_w.dump(_PROJECT_TOML, f)

        case_dir = tmp_path / "cases" / "mycase"
        case_dir.mkdir(parents=True)
        (case_dir / "summarize.py").write_text(
            textwrap.dedent("""\
                from pathlib import Path

                def summarize(run_dir, base_summary):
                    fig_dir = run_dir / "analysis" / "figures"
                    fig_dir.mkdir(parents=True, exist_ok=True)
                    (fig_dir / "plot.png").write_bytes(b"fake png")

                    base_summary.setdefault("figures", [])
                    base_summary["figures"].append({
                        "path": "figures/plot.png",
                        "caption": "Test plot",
                    })
                    return base_summary
            """),
            encoding="utf-8",
        )

        runs_dir = tmp_path / "runs"
        run_dir = _create_run(runs_dir, "R20260327-0001")
        manifest: dict[str, Any] = {
            "run": {"id": "R20260327-0001", "status": "completed"},
            "origin": {"case": "mycase"},
            "simulator": {"adapter": "test_adapter"},
        }
        with open(run_dir / "manifest.toml", "wb") as f:
            tomli_w.dump(manifest, f)

        mock_adapter = MagicMock()
        mock_adapter.summarize.return_value = {}
        mock_adapter_cls = MagicMock(return_value=mock_adapter)

        with patch(ADAPTER_PATCH, return_value=mock_adapter_cls):
            result = runner.invoke(app, ["analyze", "summarize", str(run_dir)])

        assert result.exit_code == 0
        with open(run_dir / "analysis" / "summary.json") as f:
            data = json.load(f)
        assert len(data["figures"]) == 1
        assert data["figures"][0]["path"] == "figures/plot.png"
        assert (run_dir / "analysis" / "figures" / "plot.png").exists()

    def test_summarize_with_multisim_case_script(self, tmp_path: Path) -> None:
        """Case scripts under cases/<simulator>/<case>/ are discovered."""
        with open(tmp_path / "runops.toml", "wb") as f:
            tomli_w.dump(_PROJECT_TOML, f)

        case_dir = tmp_path / "cases" / "emses" / "mycase"
        case_dir.mkdir(parents=True)
        (case_dir / "summarize.py").write_text(
            textwrap.dedent("""\
                def summarize(run_dir, base_summary):
                    base_summary["source"] = "multi-sim"
                    return base_summary
            """),
            encoding="utf-8",
        )

        runs_dir = tmp_path / "runs"
        run_dir = _create_run(runs_dir, "R20260327-0001")
        manifest: dict[str, Any] = {
            "run": {"id": "R20260327-0001", "status": "completed"},
            "origin": {"case": "mycase"},
            "simulator": {"name": "emses", "adapter": "test_adapter"},
        }
        with open(run_dir / "manifest.toml", "wb") as f:
            tomli_w.dump(manifest, f)

        mock_adapter = MagicMock()
        mock_adapter.summarize.return_value = {}
        mock_adapter_cls = MagicMock(return_value=mock_adapter)

        with patch(ADAPTER_PATCH, return_value=mock_adapter_cls):
            result = runner.invoke(app, ["analyze", "summarize", str(run_dir)])

        assert result.exit_code == 0
        with open(run_dir / "analysis" / "summary.json") as f:
            data = json.load(f)
        assert data["source"] == "multi-sim"


class TestCollect:
    def test_collect_success(self, tmp_path: Path) -> None:
        # Create two runs with summaries
        for i, run_id in enumerate(["R20260327-0001", "R20260327-0002"], start=1):
            run_dir = _create_run(tmp_path, run_id)
            summary = {"energy": float(i * 10), "steps": i * 100}
            with open(run_dir / "analysis" / "summary.json", "w") as f:
                json.dump(summary, f)

        result = runner.invoke(app, ["analyze", "collect", str(tmp_path)])
        assert result.exit_code == 0
        assert "Collected 2 summaries" in result.output

        csv_path = tmp_path / "summary" / "survey_summary.csv"
        json_path = tmp_path / "summary" / "survey_summary.json"
        figures_path = tmp_path / "summary" / "figures_index.json"
        report_path = tmp_path / "summary" / "survey_summary.md"
        assert csv_path.exists()
        assert json_path.exists()
        assert figures_path.exists()
        assert report_path.exists()
        content = csv_path.read_text()
        assert "run_id" in content
        assert "energy" in content
        assert "R20260327-0001" in content
        assert "R20260327-0002" in content

    def test_collect_no_runs(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["analyze", "collect", str(tmp_path)])
        assert result.exit_code == 1
        assert "No runs found" in result.output

    def test_collect_no_summaries(self, tmp_path: Path) -> None:
        _create_run(tmp_path, "R20260327-0001")

        result = runner.invoke(app, ["analyze", "collect", str(tmp_path)])
        assert result.exit_code == 1
        assert "No summaries found" in result.output

    def test_collect_partial_summaries(self, tmp_path: Path) -> None:
        run1 = _create_run(tmp_path, "R20260327-0001")
        _create_run(tmp_path, "R20260327-0002")  # no summary

        with open(run1 / "analysis" / "summary.json", "w") as f:
            json.dump({"energy": 10.0}, f)

        result = runner.invoke(app, ["analyze", "collect", str(tmp_path)])
        assert result.exit_code == 0
        assert "Collected 1 summaries" in result.output
        assert "1 runs missing" in result.output

    def test_collect_does_not_auto_summarize_completed_runs(
        self, tmp_path: Path
    ) -> None:
        run_dir = _create_run(tmp_path, "R20260327-0001")

        mock_adapter = MagicMock()
        mock_adapter.summarize.return_value = {"energy": 12.5}
        mock_adapter_cls = MagicMock(return_value=mock_adapter)

        with patch(ADAPTER_PATCH, return_value=mock_adapter_cls):
            result = runner.invoke(app, ["analyze", "collect", str(tmp_path)])

        assert result.exit_code == 1
        assert "No summaries found" in result.output
        assert "Auto-summarized" not in result.output
        assert not (run_dir / "analysis" / "summary.json").exists()
        mock_adapter.summarize.assert_not_called()

    def test_collect_flattens_nested_metrics_and_indexes_figures(
        self, tmp_path: Path
    ) -> None:
        run_dir = _create_run(tmp_path, "R20260327-0001")
        figures_dir = run_dir / "analysis" / "figures"
        figures_dir.mkdir(exist_ok=True)
        (figures_dir / "plot.png").write_bytes(b"fake png")

        with open(run_dir / "analysis" / "summary.json", "w", encoding="utf-8") as f:
            json.dump(
                {
                    "energy": 10.0,
                    "output_counts": {"logs": 2},
                    "figures": [
                        {"path": "figures/plot.png", "caption": "Test plot"},
                    ],
                },
                f,
            )

        result = runner.invoke(app, ["analyze", "collect", str(tmp_path)])
        assert result.exit_code == 0

        csv_content = (tmp_path / "summary" / "survey_summary.csv").read_text(
            encoding="utf-8"
        )
        assert "output_counts.logs" in csv_content

        figures_index = json.loads(
            (tmp_path / "summary" / "figures_index.json").read_text(encoding="utf-8")
        )
        assert figures_index["figures"][0]["path"].endswith("figures/plot.png")
        assert figures_index["figures"][0]["caption"] == "Test plot"

    def test_collect_includes_manifest_context_columns(self, tmp_path: Path) -> None:
        run_dir = _create_run(tmp_path, "R20260327-0001")
        manifest: dict[str, Any] = {
            "run": {
                "id": "R20260327-0001",
                "display_name": "u400_a4",
                "status": "completed",
            },
            "origin": {"case": "cavity_base", "survey": "u_scan"},
            "classification": {
                "model": "cavity",
                "submodel": "rectangular",
                "tags": ["scan"],
            },
            "simulator": {"name": "test_sim", "adapter": "test_adapter"},
            "launcher": {"name": "srun"},
            "variation": {"u": 400000.0},
            "params_snapshot": {"u": 400000.0, "aspect": 4.0},
        }
        with open(run_dir / "manifest.toml", "wb") as f:
            tomli_w.dump(manifest, f)
        with open(run_dir / "analysis" / "summary.json", "w", encoding="utf-8") as f:
            json.dump({"energy": 10.0}, f)

        result = runner.invoke(app, ["analyze", "collect", str(tmp_path)])
        assert result.exit_code == 0

        csv_content = (tmp_path / "summary" / "survey_summary.csv").read_text(
            encoding="utf-8"
        )
        assert "origin.case" in csv_content
        assert "classification.model" in csv_content
        assert "variation.u" in csv_content
        assert "param.u" in csv_content
        assert "param.aspect" in csv_content

        aggregate = json.loads(
            (tmp_path / "summary" / "survey_summary.json").read_text(encoding="utf-8")
        )
        assert aggregate["runs"][0]["flat_metadata"]["origin.case"] == "cavity_base"
        assert aggregate["runs"][0]["flat_metadata"]["param.u"] == 400000.0

    def test_collect_includes_readiness_diagnostics(self, tmp_path: Path) -> None:
        ready_run = _create_run(
            tmp_path,
            "R20260507-0001",
            simulator_name="emses",
            adapter_name="emses",
        )
        incomplete_run = _create_run(
            tmp_path,
            "R20260507-0002",
            simulator_name="emses",
            adapter_name="emses",
        )
        for run_dir in (ready_run, incomplete_run):
            with open(run_dir / "input" / "plasma.toml", "wb") as f:
                tomli_w.dump({"jobcon": {"nstep": 100}}, f)
            (run_dir / "work" / "energy").write_text(
                "100 1.0 2.0\n",
                encoding="utf-8",
            )
            with open(
                run_dir / "analysis" / "summary.json",
                "w",
                encoding="utf-8",
            ) as f:
                json.dump({"status": "completed", "energy": 10.0}, f)
        (ready_run / "work" / "ex00_0000.h5").write_bytes(b"")

        result = runner.invoke(app, ["analyze", "collect", str(tmp_path)])

        assert result.exit_code == 0, result.output
        assert "Readiness issues: 1 run(s)" in result.output

        csv_content = (tmp_path / "summary" / "survey_summary.csv").read_text(
            encoding="utf-8"
        )
        assert "analysis_status" in csv_content
        assert "missing_required_artifacts" in csv_content

        aggregate = json.loads(
            (tmp_path / "summary" / "survey_summary.json").read_text(encoding="utf-8")
        )
        assert aggregate["readiness_counts"]["ready"] == 1
        assert aggregate["readiness_counts"]["incomplete"] == 1
        assert aggregate["readiness_issues"][0]["missing_required_artifacts"] == [
            "hdf5_fields"
        ]

        report = (tmp_path / "summary" / "survey_summary.md").read_text(
            encoding="utf-8"
        )
        assert "## Analysis Readiness" in report
        assert "R20260507-0002" in report

    def test_collect_nonexistent_dir(self) -> None:
        result = runner.invoke(app, ["analyze", "collect", "/nonexistent/path"])
        assert result.exit_code == 1
        assert "Error" in result.output


class TestPlot:
    def test_plot_requires_x_and_y(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["analyze", "plot", str(tmp_path)])
        assert result.exit_code == 1
        assert "--x and --y are required" in result.output

    def test_plot_lists_columns(self, tmp_path: Path) -> None:
        run_dir = _create_run(tmp_path, "R20260327-0001")
        manifest: dict[str, Any] = {
            "run": {
                "id": "R20260327-0001",
                "display_name": "u400_a4",
                "status": "completed",
            },
            "simulator": {"name": "test_sim", "adapter": "test_adapter"},
            "params_snapshot": {"u": 400000.0},
        }
        with open(run_dir / "manifest.toml", "wb") as f:
            tomli_w.dump(manifest, f)
        with open(run_dir / "analysis" / "summary.json", "w", encoding="utf-8") as f:
            json.dump({"energy": 10.0}, f)

        result = runner.invoke(
            app,
            ["analyze", "plot", str(tmp_path), "--list-columns"],
        )

        assert result.exit_code == 0
        assert "Available columns" in result.output
        assert "param.u" in result.output
        assert "energy" in result.output

    def test_plot_success(self, tmp_path: Path) -> None:
        output_path = tmp_path / "summary" / "plots" / "energy_vs_param_u.png"
        mock_result = MagicMock()
        mock_result.output_path = output_path
        mock_result.kind = "line"
        mock_result.points_plotted = 2
        mock_result.generated_summaries = 0

        with patch("runops.cli.analyze.render_survey_plot", return_value=mock_result):
            result = runner.invoke(
                app,
                ["analyze", "plot", str(tmp_path), "--x", "param.u", "--y", "energy"],
            )

        assert result.exit_code == 0
        assert "Plot written" in result.output
        assert "Kind: line" in result.output

    def test_plot_lists_recipes(self, tmp_path: Path) -> None:
        recipe = SurveyPlotRecipe(
            name="energy-vs-u",
            adapter="test_adapter",
            description="Check energy against u.",
            x_candidates=("param.u",),
            y_candidates=("energy",),
            kind="line",
            group_by_candidates=("origin.case",),
            title="Energy vs u",
        )

        with patch(
            "runops.cli.analyze.list_survey_plot_recipes",
            return_value=(recipe,),
        ):
            result = runner.invoke(
                app,
                ["analyze", "plot", str(tmp_path), "--list-recipes"],
            )

        assert result.exit_code == 0
        assert "Available plot recipes" in result.output
        assert "energy-vs-u" in result.output
        assert "param.u" in result.output

    def test_plot_recipe_resolves_columns_before_render(self, tmp_path: Path) -> None:
        output_path = tmp_path / "summary" / "plots" / "energy_vs_param_u.png"
        resolved_recipe = ResolvedSurveyPlotRecipe(
            recipe=SurveyPlotRecipe(
                name="energy-vs-u",
                adapter="test_adapter",
                description="Check energy against u.",
                x_candidates=("param.u",),
                y_candidates=("energy",),
                kind="line",
                group_by_candidates=("origin.case",),
                title="Energy vs u",
            ),
            x="param.u",
            y="energy",
            group_by="origin.case",
        )
        mock_result = MagicMock()
        mock_result.output_path = output_path
        mock_result.kind = "line"
        mock_result.points_plotted = 2
        mock_result.generated_summaries = 0

        with (
            patch(
                "runops.cli.analyze.resolve_survey_plot_recipe",
                return_value=resolved_recipe,
            ),
            patch(
                "runops.cli.analyze.render_survey_plot",
                return_value=mock_result,
            ) as render_mock,
        ):
            result = runner.invoke(
                app,
                ["analyze", "plot", str(tmp_path), "--recipe", "energy-vs-u"],
            )

        assert result.exit_code == 0
        assert "Recipe: energy-vs-u" in result.output
        render_mock.assert_called_once()
        _, kwargs = render_mock.call_args
        assert kwargs["x"] == "param.u"
        assert kwargs["y"] == "energy"
        assert kwargs["group_by"] == "origin.case"
        assert kwargs["kind"] == "line"


class TestExport:
    def test_export_run_writes_publication_bundle(self, tmp_path: Path) -> None:
        _write_project_file(tmp_path)
        run_dir = _create_run(tmp_path / "runs", "R20260327-0001")
        with open(run_dir / "analysis" / "summary.json", "w", encoding="utf-8") as f:
            json.dump({"energy": 42.0, "figures": [{"path": "figures/phi.png"}]}, f)
        figure_path = run_dir / "analysis" / "figures" / "phi.png"
        figure_path.parent.mkdir(parents=True, exist_ok=True)
        figure_path.write_text("fake image", encoding="utf-8")

        result = runner.invoke(
            app,
            [
                "analyze",
                "export",
                str(run_dir),
                "--paper",
                "draft-a",
                "--name",
                "fig2-baseline",
                "--paper-status",
                "placeholder",
            ],
        )

        export_dir = tmp_path / "exports" / "papers" / "draft-a" / "fig2-baseline"
        exported_summary = (
            export_dir
            / "files"
            / "runs"
            / "R20260327-0001"
            / "analysis"
            / "summary.json"
        )
        exported_figure = (
            export_dir
            / "files"
            / "runs"
            / "R20260327-0001"
            / "analysis"
            / "figures"
            / "phi.png"
        )
        assert result.exit_code == 0
        assert "Export written" in result.output
        assert (export_dir / "manifest.json").exists()
        assert (export_dir / "README.md").exists()
        assert exported_summary.exists()
        assert exported_figure.exists()

        with open(export_dir / "manifest.json", encoding="utf-8") as f:
            manifest = json.load(f)
        assert manifest["paper_id"] == "draft-a"
        assert manifest["schema_version"] == 2
        assert manifest["target_kind"] == "run"
        assert manifest["source_run_ids"] == ["R20260327-0001"]
        assert manifest["paper"]["id"] == "draft-a"
        assert manifest["export"]["id"] == "draft-a/fig2-baseline"
        assert manifest["source"]["run_count"] == 1
        assert manifest["source"]["run"]["figure_count"] == 1
        assert manifest["source"]["run"]["execution_status"] == "completed"
        assert manifest["source"]["run"]["paper_status"] == "placeholder"
        assert manifest["files"][0]["sha256"].startswith("sha256:")

    def test_export_survey_collects_summary_outputs(self, tmp_path: Path) -> None:
        _write_project_file(tmp_path)
        survey_dir = tmp_path / "runs" / "angle_scan"
        survey_dir.mkdir(parents=True)
        (survey_dir / "survey.toml").write_text(
            "[survey]\n"
            'id = "S20260412-angle"\n'
            'name = "angle_scan"\n'
            'base_case = "base"\n',
            encoding="utf-8",
        )
        run_dir = _create_run(survey_dir, "R20260327-0001")
        with open(run_dir / "analysis" / "summary.json", "w", encoding="utf-8") as f:
            json.dump({"energy": 5.0}, f)
        plot_path = survey_dir / "summary" / "plots" / "energy.png"
        plot_path.parent.mkdir(parents=True, exist_ok=True)
        plot_path.write_text("fake plot", encoding="utf-8")

        result = runner.invoke(
            app,
            [
                "analyze",
                "export",
                str(survey_dir),
                "--paper",
                "draft-a",
                "--name",
                "angle-scan-main",
            ],
        )

        export_dir = tmp_path / "exports" / "papers" / "draft-a" / "angle-scan-main"
        assert result.exit_code == 0
        assert (export_dir / "manifest.json").exists()
        assert (
            export_dir
            / "files"
            / "runs"
            / "angle_scan"
            / "summary"
            / "survey_summary.csv"
        ).exists()
        assert (
            export_dir
            / "files"
            / "runs"
            / "angle_scan"
            / "summary"
            / "survey_summary.json"
        ).exists()
        assert (
            export_dir
            / "files"
            / "runs"
            / "angle_scan"
            / "summary"
            / "plots"
            / "energy.png"
        ).exists()

        with open(export_dir / "manifest.json", encoding="utf-8") as f:
            manifest = json.load(f)
        assert manifest["schema_version"] == 2
        assert manifest["source"]["kind"] == "survey"
        assert manifest["source"]["survey"]["summaries_collected"] == 1
        assert manifest["source"]["survey"]["plot_count"] == 1
        assert manifest["source"]["run_count"] == 1
