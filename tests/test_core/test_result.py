"""Domain tests for durable research result manifests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runops.core.research.result import (
    ResultManifestError,
    ResultManifestLayout,
    parse_result_manifest,
    read_result_manifest,
)


def test_parse_canonical_result_keeps_selection_local_to_result() -> None:
    manifest = parse_result_manifest(
        {
            "result": {
                "schema_version": 1,
                "id": "R0007-dust-release",
                "status": "sealed",
                "title": "Dust release",
                "claim": "Release is enhanced.",
                "outcome": "supported",
            },
            "evidence": [
                {
                    "kind": "run",
                    "run_id": "R20260801-0003",
                    "disposition": "include",
                    "role": "baseline",
                    "reason": "selected completed baseline",
                    "source_path": "runs/pilot/R20260801-0003/manifest.toml",
                    "sha256": "a" * 64,
                    "bytes": 123,
                },
                {
                    "kind": "run",
                    "run_id": "R20260801-0004",
                    "disposition": "exclude",
                    "role": "sensitivity",
                    "reason": "solver did not converge",
                    "source_path": "runs/pilot/R20260801-0004/manifest.toml",
                    "sha256": "b" * 64,
                    "bytes": 456,
                },
            ],
        }
    )

    assert manifest.layout is ResultManifestLayout.CANONICAL
    assert manifest.result_id == "R0007-dust-release"
    assert manifest.outcome == "supported"
    assert manifest.evidence[0].disposition == "include"
    assert manifest.evidence[1].reason == "solver did not converge"


@pytest.mark.parametrize(
    ("payload", "layout"),
    [
        (
            {
                "schema_version": 1,
                "id": "R0001-old",
                "title": "Old result",
                "status": "active",
            },
            ResultManifestLayout.LEGACY_FLAT,
        ),
        (
            {
                "comparison": {
                    "schema_version": 1,
                    "id": "comparison-a",
                    "name": "Comparison A",
                    "status": "draft",
                },
                "sources": [],
            },
            ResultManifestLayout.LEGACY_COMPARISON,
        ),
    ],
)
def test_parse_legacy_result_layouts_without_rewriting(
    payload: dict[str, object],
    layout: ResultManifestLayout,
) -> None:
    manifest = parse_result_manifest(payload, default_id="R0042-folder-name")

    assert manifest.layout is layout
    assert manifest.raw == payload


def test_read_result_manifest_rejects_invalid_canonical_outcome(
    tmp_path: Path,
) -> None:
    result_dir = tmp_path / "R0001-invalid"
    result_dir.mkdir()
    (result_dir / "manifest.toml").write_text(
        """
[result]
schema_version = 1
id = "R0001-invalid"
status = "draft"
title = "Invalid"
claim = ""
outcome = "maybe"
""".lstrip(),
        encoding="utf-8",
    )

    with pytest.raises(ResultManifestError, match="outcome"):
        read_result_manifest(result_dir)


def test_parse_canonical_evidence_requires_explicit_role_and_reason() -> None:
    payload = {
        "result": {
            "schema_version": 1,
            "id": "R0001-explicit-edge",
            "status": "draft",
            "title": "Explicit edge",
            "claim": "",
            "outcome": "",
        },
        "evidence": [
            {
                "kind": "run",
                "run_id": "R20260801-0001",
                "disposition": "include",
            }
        ],
    }

    with pytest.raises(ResultManifestError, match="role"):
        parse_result_manifest(payload)


@pytest.mark.parametrize("schema_version", [True, 1.0, "1", 2])
def test_canonical_result_requires_integer_schema_version_one(
    schema_version: object,
) -> None:
    payload = {
        "result": {
            "schema_version": schema_version,
            "id": "R0001-version",
            "status": "draft",
            "title": "Version check",
            "claim": "",
            "outcome": "",
        }
    }

    with pytest.raises(ResultManifestError, match="schema_version"):
        parse_result_manifest(payload)


def test_result_json_schema_keeps_evidence_selection_on_result() -> None:
    schema_path = Path(__file__).resolve().parents[2] / "schemas" / "result.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    assert schema["required"] == ["result"]
    assert schema["properties"]["result"]["properties"]["status"]["enum"] == [
        "draft",
        "sealed",
    ]
    evidence = schema["properties"]["evidence"]["items"]["properties"]
    assert evidence["disposition"]["enum"] == ["include", "exclude"]
    assert evidence["kind"]["enum"] == ["run", "path"]
