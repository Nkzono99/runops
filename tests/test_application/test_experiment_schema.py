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
