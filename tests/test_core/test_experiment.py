"""Tests for the bounded Experiment execution-kernel contract."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from runops.core.exceptions import ExperimentConfigError
from runops.core.experiment import (
    discover_experiments,
    experiment_is_expired,
    load_experiment,
)


def _write_experiment(
    path: Path,
    *,
    experiment_id: str = "E20260901-0001",
    extra: str = "",
) -> Path:
    path.write_text(
        f"""
schema_version = 1

[experiment]
id = "{experiment_id}"
title = "Grid convergence"
lifecycle = "active"
intent = "validate"
decision = "pending"
outcome = "unknown"
question = "Does the observable converge with grid refinement?"

[baseline]
run_ids = ["R20260820-0012"]
reason = ""

[budget]
max_planned_points = 12
max_materialized_runs = 6
max_active_runs = 3
max_core_hours = 500.0
max_unreviewed_runs = 4
expires_at = "2099-10-01T00:00:00+09:00"

[exit]
criteria = ["Three successive resolutions agree within one percent"]
review_due = "2026-10-01T00:00:00+09:00"

{extra}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return path


def test_load_experiment_parses_bounded_contract_and_keeps_raw(tmp_path: Path) -> None:
    path = _write_experiment(
        tmp_path / "E20260901-0001--grid.toml",
        extra='[extensions.local]\nowner = "group-a"',
    )

    experiment = load_experiment(path)

    assert experiment.id == "E20260901-0001"
    assert experiment.lifecycle == "active"
    assert experiment.intent == "validate"
    assert experiment.decision == "pending"
    assert experiment.outcome == "unknown"
    assert experiment.question.startswith("Does the observable")
    assert experiment.baseline.run_ids == ("R20260820-0012",)
    assert experiment.baseline.reason == ""
    assert experiment.budget.max_materialized_runs == 6
    assert experiment.budget.expires_at == "2099-10-01T00:00:00+09:00"
    assert experiment.exit_criteria == (
        "Three successive resolutions agree within one percent",
    )
    assert experiment.review_due == "2026-10-01T00:00:00+09:00"
    assert experiment.experiment_file == path.resolve()
    assert experiment.raw["extensions"]["local"]["owner"] == "group-a"


def test_load_experiment_accepts_baseline_reason_instead_of_runs(
    tmp_path: Path,
) -> None:
    path = _write_experiment(
        tmp_path / "E20260901-0001--new-model.toml",
    )
    text = path.read_text(encoding="utf-8").replace(
        'run_ids = ["R20260820-0012"]\nreason = ""',
        'run_ids = []\nreason = "No compatible historical run exists"',
    )
    path.write_text(text, encoding="utf-8")

    experiment = load_experiment(path)

    assert experiment.baseline.run_ids == ()
    assert experiment.baseline.reason == "No compatible historical run exists"


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('lifecycle = "active"', 'lifecycle = "running"', "lifecycle"),
        ('intent = "validate"', 'intent = "smoke"', "intent"),
        ('decision = "pending"', 'decision = "supported"', "decision"),
        ('outcome = "unknown"', 'outcome = "accept"', "outcome"),
        (
            "max_materialized_runs = 6",
            "max_materialized_runs = 13",
            "max_materialized_runs",
        ),
        (
            'criteria = ["Three successive resolutions agree within one percent"]',
            "criteria = []",
            "criteria",
        ),
        (
            'expires_at = "2099-10-01T00:00:00+09:00"',
            'expires_at = "2099-10-01T00:00:00"',
            "expires_at",
        ),
        (
            'expires_at = "2099-10-01T00:00:00+09:00"',
            "",
            "expires_at",
        ),
    ],
)
def test_load_experiment_rejects_invalid_contract(
    tmp_path: Path,
    old: str,
    new: str,
    message: str,
) -> None:
    path = _write_experiment(tmp_path / "E20260901-0001--grid.toml")
    path.write_text(
        path.read_text(encoding="utf-8").replace(old, new), encoding="utf-8"
    )

    with pytest.raises(ExperimentConfigError, match=message):
        load_experiment(path)


def test_load_experiment_requires_exactly_one_baseline_form(tmp_path: Path) -> None:
    path = _write_experiment(tmp_path / "E20260901-0001--grid.toml")
    text = path.read_text(encoding="utf-8").replace(
        'reason = ""',
        'reason = "also supplied"',
    )
    path.write_text(text, encoding="utf-8")

    with pytest.raises(ExperimentConfigError, match="exactly one"):
        load_experiment(path)


def test_experiment_expiry_uses_the_declared_offset_and_inclusive_deadline(
    tmp_path: Path,
) -> None:
    experiment = load_experiment(
        _write_experiment(tmp_path / "E20260901-0001--grid.toml")
    )
    deadline_utc = datetime(2099, 9, 30, 15, tzinfo=timezone.utc)

    assert not experiment_is_expired(
        experiment,
        now=deadline_utc - timedelta(microseconds=1),
    )
    assert experiment_is_expired(experiment, now=deadline_utc)

    with pytest.raises(ValueError, match="timezone-aware"):
        experiment_is_expired(experiment, now=datetime(2099, 9, 30, 15))


def test_load_and_expiry_accept_rfc3339_utc_designator(tmp_path: Path) -> None:
    path = _write_experiment(tmp_path / "E20260901-0001--grid.toml")
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            'expires_at = "2099-10-01T00:00:00+09:00"',
            'expires_at = "2099-09-30T15:00:00Z"',
        ),
        encoding="utf-8",
    )

    experiment = load_experiment(path)

    assert experiment.budget.expires_at == "2099-09-30T15:00:00Z"
    assert experiment_is_expired(
        experiment,
        now=datetime(2099, 9, 30, 15, tzinfo=timezone.utc),
    )


def test_load_experiment_rejects_filename_id_mismatch(tmp_path: Path) -> None:
    path = _write_experiment(tmp_path / "E20260901-0002--grid.toml")

    with pytest.raises(ExperimentConfigError, match="filename"):
        load_experiment(path)


@pytest.mark.parametrize("value", ["missing", "2", "true", "1.0"])
def test_load_experiment_requires_schema_version_one(
    tmp_path: Path,
    value: str,
) -> None:
    path = _write_experiment(tmp_path / "E20260901-0001--grid.toml")
    text = path.read_text(encoding="utf-8")
    if value == "missing":
        text = text.replace("schema_version = 1\n\n", "")
    else:
        text = text.replace("schema_version = 1", f"schema_version = {value}")
    path.write_text(text, encoding="utf-8")

    with pytest.raises(ExperimentConfigError, match="schema_version"):
        load_experiment(path)


@pytest.mark.parametrize("value", ["nan", "inf"])
def test_load_experiment_rejects_non_finite_core_hour_budget(
    tmp_path: Path,
    value: str,
) -> None:
    path = _write_experiment(tmp_path / "E20260901-0001--grid.toml")
    text = path.read_text(encoding="utf-8").replace(
        "max_core_hours = 500.0",
        f"max_core_hours = {value}",
    )
    path.write_text(text, encoding="utf-8")

    with pytest.raises(ExperimentConfigError, match="max_core_hours"):
        load_experiment(path)


def test_discover_experiments_is_recursive_and_detects_duplicate_ids(
    tmp_path: Path,
) -> None:
    first = tmp_path / "experiments" / "active" / "E20260901-0001--grid.toml"
    first.parent.mkdir(parents=True)
    _write_experiment(first)

    discovered = discover_experiments(tmp_path)
    assert [item.id for item in discovered] == ["E20260901-0001"]

    duplicate = tmp_path / "experiments" / "other" / "E20260901-0001--copy.toml"
    duplicate.parent.mkdir(parents=True)
    _write_experiment(duplicate)

    with pytest.raises(ExperimentConfigError, match="Duplicate experiment id"):
        discover_experiments(tmp_path)


def test_discover_experiments_fails_closed_on_symlink_definition(
    tmp_path: Path,
) -> None:
    experiments = tmp_path / "experiments"
    experiments.mkdir()
    external = tmp_path / "external-experiment.toml"
    _write_experiment(external)
    linked = experiments / "E20260901-0001--grid.toml"
    linked.symlink_to(external)

    with pytest.raises(ExperimentConfigError, match="single-link regular file"):
        discover_experiments(tmp_path)


def test_discover_experiments_fails_closed_on_symlink_root(tmp_path: Path) -> None:
    external = tmp_path / "external-experiments"
    external.mkdir()
    _write_experiment(external / "E20260901-0001--grid.toml")
    (tmp_path / "experiments").symlink_to(external, target_is_directory=True)

    with pytest.raises(ExperimentConfigError, match="root must be a real directory"):
        discover_experiments(tmp_path)
