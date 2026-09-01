"""Fail-closed tests for project-local coordination state."""

from __future__ import annotations

from pathlib import Path

import pytest

from runops.application.experiments import experiment_lock
from runops.application.run_creation.identity import reserve_run_id
from runops.application.survey_materialization import _survey_materialization_lock
from runops.core.exceptions import SimctlError


@pytest.mark.parametrize("operation", ["experiment", "run-id", "survey"])
def test_formal_admission_rejects_symlinked_project_state_root(
    tmp_path: Path,
    operation: str,
) -> None:
    outside = tmp_path / "outside-state"
    outside.mkdir()
    (tmp_path / ".runops").symlink_to(outside, target_is_directory=True)

    with pytest.raises(SimctlError, match="state root must be a real directory"):
        if operation == "experiment":
            with experiment_lock(tmp_path):
                pass
        elif operation == "run-id":
            reserve_run_id(tmp_path, set())
        else:
            survey = tmp_path / "runs" / "survey"
            with _survey_materialization_lock(tmp_path, survey):
                pass

    assert list(outside.iterdir()) == []
