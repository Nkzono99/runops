"""Tests for typed experiment ledger and creation-spec parsing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import tomli_w

from runops.application.research.experiments import (
    load_experiment_ledger,
    read_experiment_spec,
)
from runops.core.exceptions import SimctlError


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    (root / "runops.toml").write_text(
        '[project]\nname = "test"\n',
        encoding="utf-8",
    )
    (root / "research" / "proposals").mkdir(parents=True)
    (root / "research" / "reviews").mkdir()
    (root / "research" / "proposals" / "e1.md").write_text(
        "# E1\n",
        encoding="utf-8",
    )
    return root


def _candidate(candidate_id: str, core_hours: float) -> dict[str, object]:
    return {
        "id": candidate_id,
        "information_gain": f"information {candidate_id}",
        "falsification": f"falsification {candidate_id}",
        "estimated_core_hours": core_hours,
        "operational_risk": "low",
    }


def _write_ledger(root: Path, experiment: dict[str, object]) -> None:
    with open(root / "research" / "experiments.toml", "wb") as stream:
        tomli_w.dump({"schema_version": 2, "experiments": [experiment]}, stream)


def _complete_experiment() -> dict[str, object]:
    return {
        "id": "E1",
        "title": "Ion depletion pilot",
        "question": "Does vti widen the depletion cone?",
        "decision": "WAIT",
        "proposal": "research/proposals/e1.md",
        "review": "",
        "selected_candidate": "C1",
        "cost_ceiling_core_hours": 128.0,
        "candidates": [_candidate("C1", 32.0), _candidate("C2", 64.0)],
    }


def test_schema_v2_loads_complete_typed_record(tmp_path: Path) -> None:
    root = _project(tmp_path)
    _write_ledger(root, _complete_experiment())

    ledger = load_experiment_ledger(root)

    record = ledger.experiments[0]
    assert ledger.schema_version == 2
    assert record.id == "E1"
    assert record.title == "Ion depletion pilot"
    assert record.selected_candidate == "C1"
    assert record.cost_ceiling_core_hours == 128.0
    assert record.migration_blockers == ()
    assert ledger.identity[0] > 0


def test_schema_v2_rejects_persisted_phase(tmp_path: Path) -> None:
    root = _project(tmp_path)
    experiment = _complete_experiment()
    experiment["phase"] = "pilot-ready"
    _write_ledger(root, experiment)

    with pytest.raises(
        SimctlError,
        match="phase is derived and must not be stored",
    ):
        load_experiment_ledger(root)


def test_schema_v2_rejects_boolean_candidate_cost(tmp_path: Path) -> None:
    root = _project(tmp_path)
    experiment = _complete_experiment()
    candidates = experiment["candidates"]
    assert isinstance(candidates, list)
    candidate = candidates[0]
    assert isinstance(candidate, dict)
    candidate["estimated_core_hours"] = True
    _write_ledger(root, experiment)

    with pytest.raises(SimctlError, match="estimated_core_hours"):
        load_experiment_ledger(root)


@pytest.mark.parametrize("suffix", [".toml", ".json"])
def test_read_experiment_spec_supports_toml_and_json(
    tmp_path: Path,
    suffix: str,
) -> None:
    payload = {
        "title": "Ion depletion pilot",
        "question": "Does vti widen the depletion cone?",
        "selected_candidate": "C1",
        "cost_ceiling_core_hours": 128.0,
        "candidates": [_candidate("C1", 32.0), _candidate("C2", 64.0)],
    }
    path = tmp_path / f"experiment{suffix}"
    if suffix == ".toml":
        with open(path, "wb") as stream:
            tomli_w.dump(payload, stream)
    else:
        path.write_text(json.dumps(payload), encoding="utf-8")

    spec = read_experiment_spec(path)

    assert spec.title == payload["title"]
    assert spec.selected_candidate == "C1"
    assert [candidate.id for candidate in spec.candidates] == ["C1", "C2"]


def test_read_experiment_spec_rejects_unknown_suffix(tmp_path: Path) -> None:
    path = tmp_path / "experiment.yaml"
    path.write_text("title: unsupported\n", encoding="utf-8")

    with pytest.raises(SimctlError, match="must be TOML or JSON"):
        read_experiment_spec(path)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("decision", "GO", "decision must be"),
        ("proposal", "/tmp/outside.md", "project-relative"),
        ("proposal", "../outside.md", "project-relative"),
        ("cost_ceiling_core_hours", True, "cost_ceiling_core_hours"),
    ],
)
def test_schema_v2_rejects_invalid_record_fields(
    tmp_path: Path, field: str, value: object, message: str
) -> None:
    root = _project(tmp_path)
    experiment = _complete_experiment()
    experiment[field] = value
    _write_ledger(root, experiment)

    with pytest.raises(SimctlError, match=message):
        load_experiment_ledger(root)


def test_schema_v2_rejects_duplicate_experiment_and_candidate_ids(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path)
    experiment = _complete_experiment()
    with open(root / "research" / "experiments.toml", "wb") as stream:
        tomli_w.dump(
            {"schema_version": 2, "experiments": [experiment, experiment]}, stream
        )
    with pytest.raises(SimctlError, match="experiment ids must be unique"):
        load_experiment_ledger(root)

    candidates = experiment["candidates"]
    assert isinstance(candidates, list)
    second = candidates[1]
    assert isinstance(second, dict)
    second["id"] = "C1"
    _write_ledger(root, experiment)
    with pytest.raises(SimctlError, match="candidate ids must be unique"):
        load_experiment_ledger(root)


def test_schema_v1_loads_with_synthetic_migration_blockers(tmp_path: Path) -> None:
    root = _project(tmp_path)
    experiment = _complete_experiment()
    experiment.pop("title")
    experiment.pop("question")
    experiment.pop("cost_ceiling_core_hours")
    with open(root / "research" / "experiments.toml", "wb") as stream:
        tomli_w.dump({"schema_version": 1, "experiments": [experiment]}, stream)

    record = load_experiment_ledger(root).experiments[0]

    assert record.title is None
    assert record.migration_blockers == (
        "title",
        "question",
        "cost_ceiling_core_hours",
    )


def test_schema_v2_allows_explicit_blockers_but_validates_authorization(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path)
    experiment = _complete_experiment()
    experiment.pop("title")
    experiment["migration_blockers"] = ["title"]
    experiment["authorization"] = {
        "stage": "production",
        "survey": "runs/scan",
        "review": "research/reviews/e1.md",
        "max_core_hours": 10.0,
    }
    _write_ledger(root, experiment)

    with pytest.raises(SimctlError, match="authorization stage"):
        load_experiment_ledger(root)

    authorization = experiment["authorization"]
    assert isinstance(authorization, dict)
    authorization["stage"] = "full"
    authorization["max_core_hours"] = False
    _write_ledger(root, experiment)
    with pytest.raises(SimctlError, match="max_core_hours"):
        load_experiment_ledger(root)


def test_read_experiment_spec_rejects_non_object_json(tmp_path: Path) -> None:
    path = tmp_path / "experiment.json"
    path.write_text("[]", encoding="utf-8")

    with pytest.raises(SimctlError, match="must be an object"):
        read_experiment_spec(path)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"migration_blockers": []}, "must be omitted when empty"),
        ({"migration_blockers": [""]}, "migration_blockers"),
        ({"authorization": "full"}, "authorization must be a table"),
        ({"review": "../review.md"}, "project-relative"),
        ({"selected_candidate": "missing"}, "selected_candidate"),
        ({"candidates": []}, "at least two candidates"),
    ],
)
def test_schema_v2_rejects_invalid_structural_values(
    tmp_path: Path, mutation: dict[str, object], message: str
) -> None:
    root = _project(tmp_path)
    experiment = _complete_experiment()
    experiment.update(mutation)
    _write_ledger(root, experiment)

    with pytest.raises(SimctlError, match=message):
        load_experiment_ledger(root)


def test_ledger_rejects_invalid_top_level_and_table_shapes(tmp_path: Path) -> None:
    root = _project(tmp_path)
    ledger = root / "research" / "experiments.toml"
    with open(ledger, "wb") as stream:
        tomli_w.dump({"schema_version": 3}, stream)
    with pytest.raises(SimctlError, match="schema_version"):
        load_experiment_ledger(root)

    with open(ledger, "wb") as stream:
        tomli_w.dump({"schema_version": 2, "experiments": {}}, stream)
    with pytest.raises(SimctlError, match=r"\[\[experiments\]\]"):
        load_experiment_ledger(root)

    with open(ledger, "wb") as stream:
        tomli_w.dump({"schema_version": 2, "experiments": ["bad"]}, stream)
    with pytest.raises(SimctlError, match="must be a table"):
        load_experiment_ledger(root)


def test_ledger_reports_missing_and_invalid_toml(tmp_path: Path) -> None:
    root = _project(tmp_path)
    ledger = root / "research" / "experiments.toml"
    ledger.unlink(missing_ok=True)
    with pytest.raises(SimctlError, match="Failed to read"):
        load_experiment_ledger(root)

    ledger.write_text("broken = [", encoding="utf-8")
    with pytest.raises(SimctlError, match="Invalid experiment TOML"):
        load_experiment_ledger(root)
