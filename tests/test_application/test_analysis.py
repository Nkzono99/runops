"""Tests for survey analysis helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import tomli_w

from runops.application.analysis import (
    collect_survey_summaries,
    list_survey_plot_recipes,
    prepare_survey_plot_data,
    resolve_survey_plot_recipe,
)
from runops.core.exceptions import SimctlError

ADAPTER_PATCH = "runops.application.analysis.workflow.get_adapter"


def _create_run(
    parent: Path,
    run_id: str,
    *,
    manifest: dict[str, Any],
    summary: dict[str, Any],
) -> Path:
    run_dir = parent / run_id
    run_dir.mkdir(parents=True)
    for sub in ("input", "submit", "work", "analysis", "status"):
        (run_dir / sub).mkdir()

    with open(run_dir / "manifest.toml", "wb") as f:
        tomli_w.dump(manifest, f)
    with open(run_dir / "analysis" / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f)

    return run_dir


def test_prepare_survey_plot_data_uses_numeric_manifest_columns(
    tmp_path: Path,
) -> None:
    _create_run(
        tmp_path,
        "R20260401-0001",
        manifest={
            "run": {
                "id": "R20260401-0001",
                "display_name": "baseline",
                "status": "completed",
            },
            "origin": {"case": "cavity_base"},
            "simulator": {"name": "test_sim", "adapter": "test_adapter"},
            "params_snapshot": {"u": 400000.0},
        },
        summary={"energy": 10.0},
    )

    plot_data = prepare_survey_plot_data(tmp_path, x="param.u", y="energy")

    assert plot_data.kind == "line"
    assert plot_data.points_plotted == 1
    assert plot_data.series[0].label == "all"
    assert plot_data.series[0].points[0][0] == 400000.0
    assert plot_data.series[0].points[0][1] == 10.0


def test_prepare_survey_plot_data_auto_uses_bar_for_categorical_x(
    tmp_path: Path,
) -> None:
    _create_run(
        tmp_path,
        "R20260401-0001",
        manifest={
            "run": {
                "id": "R20260401-0001",
                "display_name": "baseline",
                "status": "completed",
            },
            "origin": {"case": "flat_surface"},
            "simulator": {"name": "test_sim", "adapter": "test_adapter"},
        },
        summary={"energy": 10.0},
    )

    plot_data = prepare_survey_plot_data(tmp_path, x="origin.case", y="energy")

    assert plot_data.kind == "bar"
    assert plot_data.series[0].points[0][0] == "flat_surface"


def test_prepare_survey_plot_data_rejects_unknown_columns(tmp_path: Path) -> None:
    _create_run(
        tmp_path,
        "R20260401-0001",
        manifest={
            "run": {
                "id": "R20260401-0001",
                "display_name": "baseline",
                "status": "completed",
            },
            "simulator": {"name": "test_sim", "adapter": "test_adapter"},
        },
        summary={"energy": 10.0},
    )

    with pytest.raises(SimctlError, match="Unknown x column"):
        prepare_survey_plot_data(tmp_path, x="param.u", y="energy")


def test_list_survey_plot_recipes_reads_adapter_recipes(tmp_path: Path) -> None:
    _create_run(
        tmp_path,
        "R20260401-0001",
        manifest={
            "run": {
                "id": "R20260401-0001",
                "display_name": "baseline",
                "status": "completed",
            },
            "simulator": {"name": "test_sim", "adapter": "test_adapter"},
            "params_snapshot": {"u": 400000.0},
        },
        summary={"energy": 10.0},
    )

    mock_adapter_cls = MagicMock()
    mock_adapter_cls.default_plot_recipes.return_value = {
        "energy-vs-u": {
            "description": "Check energy against velocity.",
            "x": ["param.u"],
            "y": ["energy"],
            "kind": "line",
            "group_by": ["origin.case"],
            "title": "Energy vs u",
        }
    }

    with patch(ADAPTER_PATCH, return_value=mock_adapter_cls):
        recipes = list_survey_plot_recipes(tmp_path)

    assert len(recipes) == 1
    assert recipes[0].name == "energy-vs-u"
    assert recipes[0].kind == "line"
    assert recipes[0].x_candidates == ("param.u",)


def test_resolve_survey_plot_recipe_uses_first_available_candidates(
    tmp_path: Path,
) -> None:
    _create_run(
        tmp_path,
        "R20260401-0001",
        manifest={
            "run": {
                "id": "R20260401-0001",
                "display_name": "baseline",
                "status": "completed",
            },
            "origin": {"case": "flat_surface"},
            "simulator": {"name": "test_sim", "adapter": "test_adapter"},
            "params_snapshot": {"u": 400000.0},
        },
        summary={"energy": 10.0},
    )

    mock_adapter_cls = MagicMock()
    mock_adapter_cls.default_plot_recipes.return_value = {
        "energy-vs-u": {
            "x": ["param.missing", "param.u"],
            "y": ["missing.energy", "energy"],
            "group_by": ["origin.case"],
            "kind": "line",
        }
    }

    with patch(ADAPTER_PATCH, return_value=mock_adapter_cls):
        resolved = resolve_survey_plot_recipe(tmp_path, "energy-vs-u")

    assert resolved.x == "param.u"
    assert resolved.y == "energy"
    assert resolved.group_by == "origin.case"


def test_collect_survey_summaries_accepts_relative_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Relative survey_dir should not raise ValueError in relative_to()."""
    survey = tmp_path / "surveys" / "my_survey"
    survey.mkdir(parents=True)
    _create_run(
        survey,
        "R20260401-0001",
        manifest={
            "run": {
                "id": "R20260401-0001",
                "display_name": "baseline",
                "status": "completed",
            },
            "origin": {"case": "cavity_base"},
            "simulator": {"name": "test_sim", "adapter": "test_adapter"},
            "params_snapshot": {"u": 400000.0},
        },
        summary={"energy": 10.0},
    )

    monkeypatch.chdir(tmp_path)
    # Use a relative path — previously raised ValueError in relative_to()
    result = collect_survey_summaries(Path("surveys/my_survey"))
    assert result.total_runs == 1
