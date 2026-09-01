"""Tests for the project-wide durable Run identity allocator."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import tomli as tomllib

from runops.application import run_discovery as run_discovery_module
from runops.application.run_creation.identity import (
    RunIdentityAllocationError,
    create_reserved_run_directory,
    release_unused_run_id,
    reserve_run_id,
)

_DATE = date(2026, 9, 1)


def _sequence(run_id: str) -> int:
    return int(run_id.rsplit("-", 1)[1])


def test_reservations_are_unique_across_concurrent_creation_paths(
    tmp_path: Path,
) -> None:
    (tmp_path / "runs" / "survey-a").mkdir(parents=True)
    (tmp_path / "runs" / "clone-target").mkdir()

    def _create(index: int) -> str:
        parent = (
            tmp_path / "runs" / "survey-a"
            if index % 2 == 0
            else tmp_path / "runs" / "clone-target"
        )
        return create_reserved_run_directory(
            tmp_path,
            parent,
            set(),
            display_name=f"candidate-{index}",
        ).run_id

    # The public helper uses today's date.  The assertion intentionally checks
    # uniqueness/monotonicity without baking that date into the test.
    with ThreadPoolExecutor(max_workers=8) as executor:
        run_ids = list(executor.map(_create, range(24)))

    assert len(set(run_ids)) == 24
    assert sorted(_sequence(run_id) for run_id in run_ids) == list(range(1, 25))
    assert len(list((tmp_path / "runs").glob("**/R*"))) == 24


def test_failed_creation_reservation_is_burned_not_reused(tmp_path: Path) -> None:
    first = reserve_run_id(tmp_path, set(), target_date=_DATE)
    # Simulate a crash before the reserved directory or manifest is committed.
    second = reserve_run_id(tmp_path, set(), target_date=_DATE)

    assert first == "R20260901-0001"
    assert second == "R20260901-0002"
    ledger = tmp_path / ".runops" / "run-id-sequence.toml"
    with ledger.open("rb") as stream:
        raw = tomllib.load(stream)
    assert raw["dates"]["20260901"] == 2


def test_successful_no_create_reuse_releases_latest_reservation(tmp_path: Path) -> None:
    first = reserve_run_id(tmp_path, set(), target_date=_DATE)
    before = (tmp_path / ".runops" / "run-id-sequence.toml").read_bytes()
    provisional = reserve_run_id(tmp_path, {first}, target_date=_DATE)

    released = release_unused_run_id(tmp_path, provisional)

    assert released is True
    assert (tmp_path / ".runops" / "run-id-sequence.toml").read_bytes() == before
    assert reserve_run_id(tmp_path, {first}, target_date=_DATE) == provisional


def test_allocator_reconciles_ledger_with_all_existing_project_manifests(
    tmp_path: Path,
) -> None:
    existing = tmp_path / "runs" / "older-survey" / "arbitrary-name"
    existing.mkdir(parents=True)
    (existing / "manifest.toml").write_text(
        '[run]\nid = "R20260901-0042"\nstatus = "archived"\n',
        encoding="utf-8",
    )

    allocated = reserve_run_id(tmp_path, set(), target_date=_DATE)

    assert allocated == "R20260901-0043"


def test_allocator_prunes_payload_tree_below_a_formal_run(tmp_path: Path) -> None:
    existing = tmp_path / "runs" / "survey" / "R20260901-0042"
    existing.mkdir(parents=True)
    (existing / "manifest.toml").write_text(
        '[run]\nid = "R20260901-0042"\nstatus = "completed"\n',
        encoding="utf-8",
    )
    outside = tmp_path / "large-external-output"
    outside.mkdir()
    (existing / "work").symlink_to(outside, target_is_directory=True)

    allocated = reserve_run_id(tmp_path, set(), target_date=_DATE)

    assert allocated == "R20260901-0043"


def test_allocator_fails_closed_on_malformed_formal_manifest(tmp_path: Path) -> None:
    malformed = tmp_path / "runs" / "legacy" / "R20260901-0001"
    malformed.mkdir(parents=True)
    (malformed / "manifest.toml").write_text("[run\nnot-toml", encoding="utf-8")

    with pytest.raises(RunIdentityAllocationError, match="formal manifest"):
        reserve_run_id(tmp_path, set(), target_date=_DATE)

    assert not (tmp_path / ".runops" / "run-id-sequence.toml").exists()


def test_allocator_fails_closed_when_namespace_walk_reports_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    def fail_walk(
        _root: object,
        *,
        topdown: bool,
        onerror: Any,
        followlinks: bool,
    ) -> list[tuple[str, list[str], list[str]]]:
        assert topdown is True
        assert followlinks is False
        onerror(PermissionError("injected unreadable subtree"))
        return []

    monkeypatch.setattr(run_discovery_module.os, "walk", fail_walk)

    with pytest.raises(RunIdentityAllocationError, match=r"walk.*unreadable"):
        reserve_run_id(tmp_path, set(), target_date=_DATE)

    assert not (tmp_path / ".runops" / "run-id-sequence.toml").exists()


@pytest.mark.parametrize(
    "dirname",
    ["linked-survey", ".tmp-linked-survey", ".delete-linked-survey"],
)
def test_allocator_fails_closed_on_symlink_directory_in_run_namespace(
    tmp_path: Path,
    dirname: str,
) -> None:
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (runs_dir / dirname).symlink_to(outside, target_is_directory=True)

    with pytest.raises(RunIdentityAllocationError, match="symbolic link"):
        reserve_run_id(tmp_path, set(), target_date=_DATE)


def test_allocator_fails_closed_when_runs_root_is_symlink(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "runs").symlink_to(outside, target_is_directory=True)

    with pytest.raises(RunIdentityAllocationError, match=r"namespace root.*symbolic"):
        reserve_run_id(tmp_path, set(), target_date=_DATE)


def test_allocator_fails_closed_when_walk_escapes_run_namespace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    def escaping_walk(
        _root: object,
        *,
        topdown: bool,
        onerror: Any,
        followlinks: bool,
    ) -> list[tuple[str, list[str], list[str]]]:
        assert topdown is True
        assert onerror is not None
        assert followlinks is False
        return [(str(outside), [], [])]

    monkeypatch.setattr(run_discovery_module.os, "walk", escaping_walk)

    with pytest.raises(RunIdentityAllocationError, match=r"escapes.*namespace"):
        reserve_run_id(tmp_path, set(), target_date=_DATE)


def test_allocator_ignores_real_internal_transaction_directories(
    tmp_path: Path,
) -> None:
    runs_dir = tmp_path / "runs"
    for name, run_id in (
        (".tmp-R20260901-0998", "R20260901-0998"),
        (".delete-R20260901-0999", "R20260901-0999"),
    ):
        transaction_dir = runs_dir / "survey" / name
        transaction_dir.mkdir(parents=True)
        (transaction_dir / "manifest.toml").write_text(
            f'[run]\nid = "{run_id}"\nstatus = "created"\n',
            encoding="utf-8",
        )

    assert reserve_run_id(tmp_path, set(), target_date=_DATE) == "R20260901-0001"


def test_corrupt_or_unsafe_sequence_ledger_fails_closed(tmp_path: Path) -> None:
    state = tmp_path / ".runops"
    state.mkdir()
    ledger = state / "run-id-sequence.toml"
    ledger.write_text("not valid = [toml", encoding="utf-8")

    with pytest.raises(RunIdentityAllocationError, match="Failed to read"):
        reserve_run_id(tmp_path, set(), target_date=_DATE)

    ledger.unlink()
    target = tmp_path / "outside-ledger.toml"
    target.write_text('schema_version = 1\n[dates]\n"20260901" = 99\n')
    ledger.symlink_to(target)
    with pytest.raises(RunIdentityAllocationError, match="regular file"):
        reserve_run_id(tmp_path, set(), target_date=_DATE)


def test_dangling_sequence_ledger_symlink_fails_closed(tmp_path: Path) -> None:
    state = tmp_path / ".runops"
    state.mkdir()
    ledger = state / "run-id-sequence.toml"
    ledger.symlink_to(tmp_path / "missing-ledger.toml")

    with pytest.raises(RunIdentityAllocationError, match="single-link regular file"):
        reserve_run_id(tmp_path, set(), target_date=_DATE)

    assert ledger.is_symlink()


def test_hardlinked_sequence_ledger_fails_closed(tmp_path: Path) -> None:
    state = tmp_path / ".runops"
    state.mkdir()
    outside = tmp_path / "outside-ledger.toml"
    outside.write_text('schema_version = 1\n[dates]\n"20260901" = 99\n')
    ledger = state / "run-id-sequence.toml"
    ledger.hardlink_to(outside)

    with pytest.raises(RunIdentityAllocationError, match="single-link regular file"):
        reserve_run_id(tmp_path, set(), target_date=_DATE)

    assert outside.read_text(encoding="utf-8").endswith('"20260901" = 99\n')
