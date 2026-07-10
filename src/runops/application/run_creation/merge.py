"""Survey override merge helpers for run creation."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from runops.core.case import ClassificationData, JobData

_CLASSIFICATION_OVERRIDE_FIELDS = frozenset({"model", "submodel", "tags"})
_JOB_OVERRIDE_FIELDS = frozenset(
    {
        "partition",
        "nodes",
        "ntasks",
        "walltime",
        "processes",
        "threads",
        "cores",
        "memory",
        "gpus",
        "qos",
        "modules",
        "pre_commands",
        "post_commands",
    }
)
_JOB_LIST_OVERRIDE_FIELDS = frozenset({"modules", "pre_commands", "post_commands"})


def _is_empty_scalar_override(value: Any) -> bool:
    return isinstance(value, str) and value == ""


def _present_override_fields(
    raw_section: object,
    allowed_fields: frozenset[str],
) -> set[str]:
    if not isinstance(raw_section, dict):
        return set()
    return {
        str(key)
        for key in raw_section
        if isinstance(key, str) and key in allowed_fields
    }


def merge_classification(
    base: ClassificationData,
    override: ClassificationData,
    raw_override: object,
) -> ClassificationData:
    """Apply survey classification keys as a partial overlay."""
    fields = _present_override_fields(raw_override, _CLASSIFICATION_OVERRIDE_FIELDS)
    updates: dict[str, Any] = {}
    if "model" in fields and not _is_empty_scalar_override(override.model):
        updates["model"] = override.model
    if "submodel" in fields and not _is_empty_scalar_override(override.submodel):
        updates["submodel"] = override.submodel
    if "tags" in fields:
        updates["tags"] = list(override.tags)
    if not updates:
        return base
    return replace(base, **updates)


def merge_job(
    base: JobData,
    override: JobData,
    raw_override: object,
) -> JobData:
    """Apply survey job keys as a partial overlay."""
    fields = _present_override_fields(raw_override, _JOB_OVERRIDE_FIELDS)
    updates: dict[str, Any] = {}
    for field in fields:
        value = getattr(override, field)
        if field in _JOB_LIST_OVERRIDE_FIELDS and isinstance(value, list):
            value = list(value)
        elif _is_empty_scalar_override(value):
            continue
        updates[field] = value
    if not updates:
        return base
    return replace(base, **updates)
