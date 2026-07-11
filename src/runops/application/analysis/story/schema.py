"""Story TOML parsing, validation, and serialization."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, cast

from runops.core.exceptions import SimctlError

from .models import SourceKind, StorySource, StorySpec, StoryStep

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
_SOURCE_KINDS = frozenset({"run", "survey", "comparison", "path"})


def validate_story_id(value: str) -> str:
    """Validate and return a stable Story identifier."""
    if not value:
        raise SimctlError("story id must be non-empty")
    if value != value.strip():
        raise SimctlError("story id must not contain leading or trailing whitespace")
    if not _ID_PATTERN.match(value):
        raise SimctlError(
            "story id must start with a lowercase letter or digit and contain "
            "only lowercase letters, digits, '.', '_' or '-'"
        )
    return value


def read_story_spec(story_path: Path, *, default_id: str) -> StorySpec:
    """Read and validate a Story schema version 1 TOML document."""
    try:
        with open(story_path, "rb") as stream:
            raw = tomllib.load(stream)
    except OSError as exc:
        raise SimctlError(f"Failed to read {story_path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise SimctlError(f"Invalid TOML in {story_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise SimctlError(f"Invalid story spec in {story_path}")
    return parse_story_spec(raw, default_id=default_id)


def parse_story_spec(story: dict[str, Any], *, default_id: str) -> StorySpec:
    """Validate a decoded Story mapping."""
    schema_version = story.get("schema_version")
    if type(schema_version) is not int or schema_version != 1:
        raise SimctlError("story schema_version must be 1")
    story_id = validate_story_id(_required_string(story, "id", default=default_id))
    title = _required_string(story, "title", default=story_id)
    return StorySpec(
        schema_version=1,
        id=story_id,
        title=title,
        status=str(story.get("status", "draft") or "draft"),
        sources=_read_sources(story),
        steps=_read_steps(story),
    )


def story_spec_payload(spec: StorySpec) -> dict[str, object]:
    """Return a TOML-serializable mapping for a typed Story spec."""
    return {
        "schema_version": spec.schema_version,
        "id": spec.id,
        "title": spec.title,
        "status": spec.status,
        "sources": [
            {"kind": source.kind, "path": source.path} for source in spec.sources
        ],
        "steps": [
            {
                "id": step.id,
                "title": step.title,
                "required_artifacts": list(step.required_artifacts),
                "acceptable_status": list(step.acceptable_status),
                "claim_ceiling": step.claim_ceiling,
                "notes": step.notes,
            }
            for step in spec.steps
        ],
    }


def _read_sources(story: dict[str, Any]) -> tuple[StorySource, ...]:
    raw_sources = story.get("sources", [])
    if raw_sources is None:
        return ()
    if not isinstance(raw_sources, list):
        raise SimctlError("story sources must be a list")

    sources: list[StorySource] = []
    for index, item in enumerate(raw_sources, start=1):
        if not isinstance(item, dict):
            raise SimctlError(f"story source #{index} must be a table")
        raw_path = item.get("path", "")
        if not isinstance(raw_path, str):
            raise SimctlError(f"story source #{index} path must be a string")
        path = raw_path.strip()
        if not path:
            raise SimctlError(f"story source #{index} is missing path")
        raw_kind = item.get("kind", "path")
        if not isinstance(raw_kind, str) or raw_kind not in _SOURCE_KINDS:
            valid = ", ".join(sorted(_SOURCE_KINDS))
            raise SimctlError(f"story source #{index} kind must be one of: {valid}")
        sources.append(
            StorySource(kind=cast(SourceKind, raw_kind), path=path)
        )
    return tuple(sources)


def _read_steps(story: dict[str, Any]) -> tuple[StoryStep, ...]:
    raw_steps = story.get("steps", [])
    if not isinstance(raw_steps, list) or not raw_steps:
        raise SimctlError("story must define at least one [[steps]] table")

    steps: list[StoryStep] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_steps, start=1):
        if not isinstance(item, dict):
            raise SimctlError(f"story step #{index} must be a table")
        step_id = str(item.get("id", "")).strip()
        if not step_id:
            raise SimctlError(f"story step #{index} is missing id")
        if step_id in seen:
            raise SimctlError(f"Duplicate story step id: {step_id}")
        seen.add(step_id)
        steps.append(
            StoryStep(
                id=step_id,
                title=str(item.get("title", step_id) or step_id),
                required_artifacts=_required_string_array(
                    item.get("required_artifacts"),
                    field=f"story step #{index} required_artifacts",
                ),
                acceptable_status=_required_string_array(
                    item.get("acceptable_status"),
                    field=f"story step #{index} acceptable_status",
                ),
                claim_ceiling=str(item.get("claim_ceiling", "") or ""),
                notes=str(item.get("notes", "") or ""),
            )
        )
    return tuple(steps)


def _required_string(
    payload: dict[str, Any],
    key: str,
    *,
    default: str = "",
) -> str:
    value = str(payload.get(key, default) or default).strip()
    if not value:
        raise SimctlError(f"story {key} must be non-empty")
    return value


def _required_string_array(value: Any, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise SimctlError(f"{field} must be a non-empty string array")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise SimctlError(f"{field} must contain only non-empty strings")
        result.append(item.strip())
    return tuple(result)
