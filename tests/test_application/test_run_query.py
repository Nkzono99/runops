"""Tests for strict operator-facing Run namespace queries."""

from __future__ import annotations

from pathlib import Path

import pytest

from runops.application.run_query import query_runs
from runops.core.exceptions import SimctlError
from runops.core.manifest import ManifestData, write_manifest


def test_strict_active_query_rejects_duplicate_id_in_cold_namespace(
    tmp_path: Path,
) -> None:
    run_id = "R20260901-0001"
    write_manifest(
        tmp_path / "runs" / "active" / run_id,
        ManifestData(run={"id": run_id, "status": "running"}),
    )
    write_manifest(
        tmp_path / "runs" / "_archive" / "old" / run_id,
        ManifestData(run={"id": run_id, "status": "archived"}),
    )

    with pytest.raises(SimctlError, match=rf"{run_id}.*duplicated"):
        query_runs(tmp_path, view="active", strict_manifests=True)
