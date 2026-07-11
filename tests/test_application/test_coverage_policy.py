"""Tests for critical-module coverage policy evaluation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runops.application.operator.coverage_policy import (
    CoverageViolation,
    evaluate_coverage_policy,
    load_coverage_policy,
    main,
)

ROOT = Path(__file__).resolve().parents[2]


def _write_report(path: Path, percentages: dict[str, float]) -> None:
    path.write_text(
        json.dumps(
            {
                "files": {
                    source_path: {"summary": {"percent_covered": percent}}
                    for source_path, percent in percentages.items()
                }
            }
        ),
        encoding="utf-8",
    )


def _write_policy(path: Path, threshold: str = "90") -> None:
    path.write_text(
        "[tool.runops.coverage-policy.modules]\n"
        f'"src/runops/core/state.py" = {threshold}\n',
        encoding="utf-8",
    )


def test_coverage_policy_passes_when_every_module_meets_floor(tmp_path: Path) -> None:
    report = tmp_path / "coverage.json"
    _write_report(report, {"src/runops/core/state.py": 92.5})

    assert (
        evaluate_coverage_policy(
            report,
            {"src/runops/core/state.py": 90.0},
        )
        == ()
    )


def test_coverage_policy_reports_below_floor(tmp_path: Path) -> None:
    report = tmp_path / "coverage.json"
    _write_report(report, {"src/runops/core/state.py": 89.25})

    assert evaluate_coverage_policy(
        report,
        {"src/runops/core/state.py": 90.0},
    ) == (
        CoverageViolation(
            path="src/runops/core/state.py",
            actual=89.25,
            required=90.0,
            reason="coverage is below the required floor",
        ),
    )


def test_coverage_policy_reports_missing_module(tmp_path: Path) -> None:
    report = tmp_path / "coverage.json"
    _write_report(report, {})

    assert evaluate_coverage_policy(
        report,
        {"src/runops/core/state.py": 90.0},
    ) == (
        CoverageViolation(
            path="src/runops/core/state.py",
            actual=None,
            required=90.0,
            reason="module is missing from the coverage report",
        ),
    )


@pytest.mark.parametrize("threshold", ["-1", "101", '"high"', "true"])
def test_load_coverage_policy_rejects_invalid_thresholds(
    tmp_path: Path,
    threshold: str,
) -> None:
    config = tmp_path / "pyproject.toml"
    _write_policy(config, threshold)

    with pytest.raises(ValueError, match=r"src/runops/core/state\.py"):
        load_coverage_policy(config)


def test_load_coverage_policy_requires_modules_table(tmp_path: Path) -> None:
    config = tmp_path / "pyproject.toml"
    config.write_text("[tool.runops]\n", encoding="utf-8")

    with pytest.raises(ValueError, match=r"coverage-policy\.modules"):
        load_coverage_policy(config)


def test_evaluate_coverage_policy_rejects_malformed_json(tmp_path: Path) -> None:
    report = tmp_path / "coverage.json"
    report.write_text("{not-json", encoding="utf-8")

    with pytest.raises(ValueError, match="coverage JSON"):
        evaluate_coverage_policy(report, {"src/runops/core/state.py": 90.0})


def test_coverage_policy_main_reports_success(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = tmp_path / "coverage.json"
    config = tmp_path / "pyproject.toml"
    _write_report(report, {"src/runops/core/state.py": 92.5})
    _write_policy(config)

    assert main([str(report), "--config", str(config)]) == 0
    captured = capsys.readouterr()
    assert "1 critical modules meet their coverage floors" in captured.out
    assert captured.err == ""


def test_coverage_policy_main_reports_violations(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = tmp_path / "coverage.json"
    config = tmp_path / "pyproject.toml"
    _write_report(report, {"src/runops/core/state.py": 89.25})
    _write_policy(config)

    assert main([str(report), "--config", str(config)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "src/runops/core/state.py: 89.25% < 90.00%" in captured.err


def test_coverage_policy_main_reports_invalid_input(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = tmp_path / "coverage.json"
    config = tmp_path / "pyproject.toml"
    report.write_text("{not-json", encoding="utf-8")
    _write_policy(config)

    assert main([str(report), "--config", str(config)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "coverage policy error:" in captured.err


def test_repository_policy_covers_typed_story_package() -> None:
    policy = load_coverage_policy(ROOT / "pyproject.toml")

    assert "src/runops/application/analysis/story.py" not in policy
    assert {
        path: policy[path]
        for path in policy
        if path.startswith("src/runops/application/analysis/story/")
    } == {
        "src/runops/application/analysis/story/models.py": 95.0,
        "src/runops/application/analysis/story/schema.py": 90.0,
        "src/runops/application/analysis/story/audit.py": 95.0,
        "src/runops/application/analysis/story/sources.py": 80.0,
        "src/runops/application/analysis/story/render.py": 90.0,
        "src/runops/application/analysis/story/workspace.py": 80.0,
    }
