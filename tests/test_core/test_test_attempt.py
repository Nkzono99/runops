"""Core contract tests for isolated smoke/debug TestAttempts."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from runops.core import test_attempt as test_attempt_module
from runops.core.test_attempt import TestAttemptError as AttemptError
from runops.core.test_attempt import (
    build_test_attempt_cache_key,
    load_test_attempt,
    write_test_attempt,
)


def _receipt() -> dict[str, object]:
    receipt: dict[str, object] = {
        "schema_version": 1,
        "test": {
            "id": "T20260901-0001",
            "kind": "smoke",
            "state": "prepared",
            "case": "generic/base",
            "profile": "smoke",
            "source_commit": "abc123",
            "executable_hash": "sha256:" + "1" * 64,
            "input_hash": "sha256:" + "2" * 64,
            "adapter": "generic",
            "adapter_version": "1.2.3",
            "cache_key": "",
            "created_at": "2026-09-01T12:00:00+00:00",
            "updated_at": "2026-09-01T12:00:00+00:00",
            "started_at": "",
            "finished_at": "",
            "observation": "",
            "cached_from": "",
        },
        "extension": {"owner": "lab"},
    }
    section = receipt["test"]
    assert isinstance(section, dict)
    section["cache_key"] = build_test_attempt_cache_key(
        kind=str(section["kind"]),
        case=str(section["case"]),
        profile=str(section["profile"]),
        source_commit=str(section["source_commit"]),
        executable_hash=str(section["executable_hash"]),
        input_hash=str(section["input_hash"]),
        adapter=str(section["adapter"]),
        adapter_version=str(section["adapter_version"]),
    )
    return receipt


def test_receipt_round_trip_validates_typed_fields_and_preserves_unknowns(
    tmp_path: Path,
) -> None:
    attempt_dir = tmp_path / "T20260901-0001"

    write_test_attempt(attempt_dir, _receipt())
    attempt = load_test_attempt(attempt_dir)

    assert attempt.id == "T20260901-0001"
    assert attempt.kind == "smoke"
    assert attempt.state == "prepared"
    assert attempt.input_hash == "sha256:" + "2" * 64
    assert attempt.adapter_version == "1.2.3"
    assert attempt.raw["extension"] == {"owner": "lab"}


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("id", "R20260901-0001", "test.id"),
        ("kind", "production", "test.kind"),
        ("state", "completed", "test.state"),
        ("case", 7, "test.case"),
        ("input_hash", "not-a-hash", "test.input_hash"),
        ("adapter_version", 2, "test.adapter_version"),
        ("created_at", "yesterday", "test.created_at"),
        ("observation", [], "test.observation"),
    ],
)
def test_receipt_rejects_invalid_fields(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    receipt = _receipt()
    section = receipt["test"]
    assert isinstance(section, dict)
    section[field] = value
    attempt_dir = tmp_path / "T20260901-0001"

    with pytest.raises(AttemptError, match=message):
        write_test_attempt(attempt_dir, receipt)


@pytest.mark.parametrize("schema_version", [True, 1.0, "1", 2])
def test_receipt_rejects_non_integer_one_schema_version(
    tmp_path: Path,
    schema_version: object,
) -> None:
    receipt = _receipt()
    receipt["schema_version"] = schema_version

    with pytest.raises(AttemptError, match="schema_version"):
        write_test_attempt(tmp_path / "T20260901-0001", receipt)


def test_receipt_rejects_cache_key_that_does_not_match_identity(
    tmp_path: Path,
) -> None:
    receipt = _receipt()
    section = receipt["test"]
    assert isinstance(section, dict)
    section["input_hash"] = "sha256:" + "9" * 64

    with pytest.raises(AttemptError, match="canonical TestAttempt identity"):
        write_test_attempt(tmp_path / "T20260901-0001", receipt)


def test_receipt_rejects_symlink_attempt_directory(tmp_path: Path) -> None:
    target = tmp_path / "outside"
    target.mkdir()
    link = tmp_path / "T20260901-0001"
    link.symlink_to(target, target_is_directory=True)

    with pytest.raises(AttemptError, match="symbolic link"):
        write_test_attempt(link, _receipt())


def test_load_rejects_hardlinked_receipt(tmp_path: Path) -> None:
    attempt_dir = tmp_path / "T20260901-0001"
    write_test_attempt(attempt_dir, _receipt())
    receipt = attempt_dir / "test-receipt.toml"
    external = tmp_path / "external-receipt.toml"
    os.link(receipt, external)

    with pytest.raises(AttemptError, match="single-link regular file"):
        load_test_attempt(attempt_dir)

    assert external.is_file()
    assert external.stat().st_nlink == 2


def test_load_rejects_receipt_swapped_between_lstat_and_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempt_dir = tmp_path / "T20260901-0001"
    write_test_attempt(attempt_dir, _receipt())
    receipt = attempt_dir / "test-receipt.toml"
    replacement = tmp_path / "replacement.toml"
    replacement.write_bytes(receipt.read_bytes())
    real_open = test_attempt_module.os.open
    swapped = False

    def swap_then_open(path: object, flags: int, *args: object) -> int:
        nonlocal swapped
        if Path(path) == receipt and not swapped:
            swapped = True
            os.replace(replacement, receipt)
        return real_open(path, flags, *args)

    monkeypatch.setattr(test_attempt_module.os, "open", swap_then_open)

    with pytest.raises(AttemptError, match="changed while opening"):
        load_test_attempt(attempt_dir)
