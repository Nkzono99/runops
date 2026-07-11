"""Tests for atomic experiment workspace creation."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import Mock

import pytest

from runops.application.research.experiments import (
    ExperimentCreateApplyError,
    ExperimentCreateRequest,
    ExperimentStalePlanError,
    apply_create_experiment,
    plan_create_experiment,
    read_experiment_spec,
    workspace,
)
from runops.core.exceptions import SimctlError


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / "research").mkdir(parents=True)
    (root / "runops.toml").write_text('[project]\nname = "test"\n', encoding="utf-8")
    (root / "research" / "experiments.toml").write_text(
        "schema_version = 2\n", encoding="utf-8"
    )
    return root


def _spec(tmp_path: Path) -> Path:
    path = tmp_path / "experiment.json"
    path.write_text(
        json.dumps(
            {
                "title": "Ion depletion pilot",
                "question": "Does vti widen the depletion cone?",
                "selected_candidate": "C1",
                "cost_ceiling_core_hours": 128.0,
                "candidates": [
                    {
                        "id": "C1",
                        "information_gain": "thermal scaling",
                        "falsification": "no response",
                        "estimated_core_hours": 32.0,
                        "operational_risk": "low",
                    },
                    {
                        "id": "C2",
                        "information_gain": "resolution sensitivity",
                        "falsification": "trend changes",
                        "estimated_core_hours": 64.0,
                        "operational_risk": "medium",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _plan(tmp_path: Path):  # type: ignore[no-untyped-def]
    root = _project(tmp_path)
    spec = read_experiment_spec(_spec(tmp_path))
    return plan_create_experiment(ExperimentCreateRequest(root, "E1", spec))


def test_create_plan_is_non_mutating(tmp_path: Path) -> None:
    plan = _plan(tmp_path)

    assert plan.experiment_id == "E1"
    assert plan.ledger_after.schema_version == 2
    assert not plan.proposal_path.exists()
    assert plan.ledger_path.read_text(encoding="utf-8") == "schema_version = 2\n"


def test_apply_creates_ledger_record_and_proposal(tmp_path: Path) -> None:
    plan = _plan(tmp_path)

    result = apply_create_experiment(plan)

    assert result.experiment.id == "E1"
    assert result.proposal_path.is_file()
    assert "Ion depletion pilot" in result.proposal_path.read_text(encoding="utf-8")
    assert "[[experiments]]" in result.ledger_path.read_text(encoding="utf-8")


def test_apply_rejects_stale_ledger(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    with open(plan.ledger_path, "a", encoding="utf-8") as stream:
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())

    with pytest.raises(ExperimentStalePlanError):
        apply_create_experiment(plan)


def test_apply_rolls_back_proposal_when_ledger_publish_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _plan(tmp_path)
    monkeypatch.setattr(
        workspace, "_publish_ledger", Mock(side_effect=OSError("disk full"))
    )

    with pytest.raises(ExperimentCreateApplyError) as caught:
        apply_create_experiment(plan)

    assert not plan.proposal_path.exists()
    assert caught.value.recovery_path is None


@pytest.mark.parametrize("experiment_id", ["", "bad/id", "x" * 65])
def test_plan_rejects_invalid_experiment_ids(
    tmp_path: Path, experiment_id: str
) -> None:
    root = _project(tmp_path)
    spec = read_experiment_spec(_spec(tmp_path))

    with pytest.raises(SimctlError, match="experiment id"):
        plan_create_experiment(ExperimentCreateRequest(root, experiment_id, spec))


def test_plan_rejects_schema_v1_duplicate_and_existing_proposal(tmp_path: Path) -> None:
    root = _project(tmp_path)
    spec = read_experiment_spec(_spec(tmp_path))
    ledger = root / "research" / "experiments.toml"
    ledger.write_text("schema_version = 1\n", encoding="utf-8")
    with pytest.raises(SimctlError, match="schema_version 2"):
        plan_create_experiment(ExperimentCreateRequest(root, "E1", spec))

    ledger.write_text("schema_version = 2\n", encoding="utf-8")
    proposal = root / "research" / "proposals" / "E1.md"
    proposal.parent.mkdir()
    proposal.write_text("existing\n", encoding="utf-8")
    with pytest.raises(SimctlError, match="proposal already exists"):
        plan_create_experiment(ExperimentCreateRequest(root, "E1", spec))

    proposal.unlink()
    first = plan_create_experiment(ExperimentCreateRequest(root, "E1", spec))
    apply_create_experiment(first)
    with pytest.raises(SimctlError, match="experiment already exists"):
        plan_create_experiment(ExperimentCreateRequest(root, "E1", spec))


def test_apply_rejects_proposal_appearing_or_ledger_disappearing(
    tmp_path: Path,
) -> None:
    plan = _plan(tmp_path)
    plan.proposal_path.parent.mkdir()
    plan.proposal_path.write_text("race\n", encoding="utf-8")
    with pytest.raises(ExperimentStalePlanError, match="proposal appeared"):
        apply_create_experiment(plan)

    plan.proposal_path.unlink()
    plan.ledger_path.unlink()
    with pytest.raises(ExperimentStalePlanError, match="cannot be revalidated"):
        apply_create_experiment(plan)


def test_apply_restores_ledger_when_directory_sync_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _plan(tmp_path)
    original = plan.ledger_path.read_bytes()
    real_fsync = workspace._fsync_directory
    calls = 0

    def fail_once(path: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("sync failed")
        real_fsync(path)

    monkeypatch.setattr(workspace, "_fsync_directory", fail_once)

    with pytest.raises(ExperimentCreateApplyError) as caught:
        apply_create_experiment(plan)

    assert plan.ledger_path.read_bytes() == original
    assert not plan.proposal_path.exists()
    assert caught.value.completed_paths == (plan.proposal_path, plan.ledger_path)
    assert caught.value.recovery_path is None


def test_apply_wraps_proposal_publish_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _plan(tmp_path)
    monkeypatch.setattr(
        workspace, "_publish_proposal", Mock(side_effect=OSError("link failed"))
    )

    with pytest.raises(ExperimentCreateApplyError) as caught:
        apply_create_experiment(plan)

    assert caught.value.failed_path == plan.proposal_path
    assert caught.value.completed_paths == ()
    assert plan.ledger_path.read_bytes() == plan.original_ledger_bytes
