"""Tests for typed Story schema parsing."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import tomli_w

from runops.application.analysis.story.models import StorySource, StoryStep
from runops.application.analysis.story.schema import (
    read_story_spec,
    story_spec_payload,
)
from runops.core.exceptions import SimctlError


def _write_story(path: Path, payload: dict[str, Any]) -> None:
    with open(path, "wb") as stream:
        tomli_w.dump(payload, stream)


def test_read_story_spec_returns_immutable_typed_records(tmp_path: Path) -> None:
    path = tmp_path / "story.toml"
    _write_story(
        path,
        {
            "schema_version": 1,
            "id": "surface",
            "title": "Surface story",
            "status": "draft",
            "sources": [{"kind": "survey", "path": "runs/scan"}],
            "steps": [
                {
                    "id": "field",
                    "title": "Surface field",
                    "required_artifacts": ["figure:surface"],
                    "acceptable_status": ["main", "accepted"],
                    "claim_ceiling": "static evidence",
                }
            ],
        },
    )

    spec = read_story_spec(path, default_id="fallback")

    assert spec.id == "surface"
    assert spec.sources == (StorySource(kind="survey", path="runs/scan"),)
    assert spec.steps == (
        StoryStep(
            id="field",
            title="Surface field",
            required_artifacts=("figure:surface",),
            acceptable_status=("main", "accepted"),
            claim_ceiling="static evidence",
        ),
    )


def test_story_spec_payload_uses_toml_containers(tmp_path: Path) -> None:
    path = tmp_path / "story.toml"
    _write_story(
        path,
        {
            "schema_version": 1,
            "id": "surface",
            "title": "Surface story",
            "sources": [{"kind": "survey", "path": "runs/scan"}],
            "steps": [
                {
                    "id": "field",
                    "required_artifacts": ["figure:surface"],
                    "acceptable_status": ["main"],
                }
            ],
        },
    )

    payload = story_spec_payload(read_story_spec(path, default_id="fallback"))

    assert payload == {
        "schema_version": 1,
        "id": "surface",
        "title": "Surface story",
        "status": "draft",
        "sources": [{"kind": "survey", "path": "runs/scan"}],
        "steps": [
            {
                "id": "field",
                "title": "field",
                "required_artifacts": ["figure:surface"],
                "acceptable_status": ["main"],
                "claim_ceiling": "",
                "notes": "",
            }
        ],
    }


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (
            {"schema_version": True, "steps": []},
            "story schema_version must be 1",
        ),
        (
            {
                "schema_version": 1,
                "sources": [{"kind": "RUN", "path": "runs/scan"}],
                "steps": [
                    {
                        "id": "field",
                        "required_artifacts": ["figure:surface"],
                        "acceptable_status": ["main"],
                    }
                ],
            },
            "story source #1 kind must be one of",
        ),
        (
            {
                "schema_version": 1,
                "steps": [
                    {
                        "id": "same",
                        "required_artifacts": ["figure:one"],
                        "acceptable_status": ["main"],
                    },
                    {
                        "id": "same",
                        "required_artifacts": ["figure:two"],
                        "acceptable_status": ["main"],
                    },
                ],
            },
            "Duplicate story step id: same",
        ),
        (
            {"schema_version": 1, "steps": []},
            "story must define at least one [[steps]] table",
        ),
        (
            {
                "schema_version": 1,
                "steps": [
                    {
                        "id": "field",
                        "required_artifacts": [],
                        "acceptable_status": ["main"],
                    }
                ],
            },
            "story step #1 required_artifacts must be a non-empty string array",
        ),
    ],
)
def test_read_story_spec_preserves_validation_errors(
    tmp_path: Path,
    payload: dict[str, Any],
    message: str,
) -> None:
    path = tmp_path / "story.toml"
    _write_story(path, payload)

    with pytest.raises(SimctlError, match=re.escape(message)):
        read_story_spec(path, default_id="fallback")
