"""Tests for typed Story schema parsing."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import tomli_w

from runops.application.analysis.story.models import StorySource, StoryStep
from runops.application.analysis.story.schema import (
    parse_story_spec,
    read_story_spec,
    story_spec_payload,
    validate_story_id,
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


@pytest.mark.parametrize(
    ("story_id", "message"),
    [
        ("", "story id must be non-empty"),
        ("Bad ID", "story id must start with"),
    ],
)
def test_validate_story_id_rejects_invalid_values(
    story_id: str,
    message: str,
) -> None:
    with pytest.raises(SimctlError, match=message):
        validate_story_id(story_id)


def test_read_story_spec_translates_file_and_toml_errors(tmp_path: Path) -> None:
    missing = tmp_path / "missing.toml"
    with pytest.raises(SimctlError, match="Failed to read"):
        read_story_spec(missing, default_id="fallback")

    malformed = tmp_path / "story.toml"
    malformed.write_text("[broken", encoding="utf-8")
    with pytest.raises(SimctlError, match="Invalid TOML"):
        read_story_spec(malformed, default_id="fallback")


@pytest.mark.parametrize(
    ("sources", "message"),
    [
        (None, ""),
        ({}, "story sources must be a list"),
        (["runs/scan"], "story source #1 must be a table"),
        ([{"path": 1}], "story source #1 path must be a string"),
        ([{"path": "  "}], "story source #1 is missing path"),
    ],
)
def test_parse_story_spec_validates_source_container_shapes(
    sources: object,
    message: str,
) -> None:
    payload: dict[str, Any] = {
        "schema_version": 1,
        "id": "story",
        "sources": sources,
        "steps": [
            {
                "id": "step",
                "required_artifacts": ["figure:x"],
                "acceptable_status": ["main"],
            }
        ],
    }
    if not message:
        assert parse_story_spec(payload, default_id="fallback").sources == ()
        return
    with pytest.raises(SimctlError, match=message):
        parse_story_spec(payload, default_id="fallback")


@pytest.mark.parametrize(
    ("step", "message"),
    [
        ("step", "story step #1 must be a table"),
        (
            {
                "required_artifacts": ["figure:x"],
                "acceptable_status": ["main"],
            },
            "story step #1 is missing id",
        ),
        (
            {
                "id": "step",
                "required_artifacts": ["  "],
                "acceptable_status": ["main"],
            },
            "must contain only non-empty strings",
        ),
    ],
)
def test_parse_story_spec_validates_step_container_shapes(
    step: object,
    message: str,
) -> None:
    with pytest.raises(SimctlError, match=message):
        parse_story_spec(
            {"schema_version": 1, "id": "story", "steps": [step]},
            default_id="fallback",
        )


def test_parse_story_spec_requires_an_id_when_default_is_empty() -> None:
    with pytest.raises(SimctlError, match="story id must be non-empty"):
        parse_story_spec(
            {
                "schema_version": 1,
                "steps": [
                    {
                        "id": "step",
                        "required_artifacts": ["figure:x"],
                        "acceptable_status": ["main"],
                    }
                ],
            },
            default_id="",
        )
