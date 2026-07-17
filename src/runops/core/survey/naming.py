"""Deterministic human-readable naming for generated runs."""

from __future__ import annotations

import math
import unicodedata
from dataclasses import dataclass, field
from typing import Any

DEFAULT_DIRECTORY_TEMPLATE = "{run_id}--{label}"
DEFAULT_LABEL_MAX_LENGTH = 48
_NUMBER_TYPES = (int, float)


@dataclass(frozen=True)
class NamingGroup:
    """A set of parameters that can collapse into one semantic change."""

    label: str
    keys: tuple[str, ...]
    strategy: str = "uniform_ratio"


@dataclass(frozen=True)
class NamingConfig:
    """Naming rules parsed from a survey ``[naming]`` section."""

    display_name: str = ""
    directory_template: str = DEFAULT_DIRECTORY_TEMPLATE
    max_length: int = DEFAULT_LABEL_MAX_LENGTH
    aliases: dict[str, str] = field(default_factory=dict)
    groups: tuple[NamingGroup, ...] = ()


def generate_semantic_label(
    base_params: dict[str, Any],
    params: dict[str, Any],
    variation_keys: tuple[str, ...] | list[str],
    naming: NamingConfig,
) -> str:
    """Describe parameter changes relative to a base case.

    Configured groups collapse only when every member changes by the same
    numeric ratio. Other changes remain explicit so a friendly label never
    hides a non-uniform variation.
    """
    changed_keys = [
        key
        for key in variation_keys
        if key in params and params.get(key) != base_params.get(key)
    ]
    if not changed_keys:
        return "baseline"

    parts: list[str] = []
    consumed: set[str] = set()
    changed_set = set(changed_keys)
    ratio_keys = {key for group in naming.groups for key in group.keys}

    for group in naming.groups:
        if group.strategy != "uniform_ratio":
            continue
        if not set(group.keys).issubset(changed_set):
            continue
        ratios = [
            _numeric_ratio(base_params.get(key), params.get(key)) for key in group.keys
        ]
        if any(ratio is None for ratio in ratios):
            continue
        numeric_ratios = [ratio for ratio in ratios if ratio is not None]
        first = numeric_ratios[0]
        if not all(math.isclose(ratio, first) for ratio in numeric_ratios[1:]):
            continue
        parts.append(f"{_slugify(group.label)}-x{_format_number(first)}")
        consumed.update(group.keys)

    for key in changed_keys:
        if key in consumed:
            continue
        key_label = naming.aliases.get(key, _default_alias(key))
        base_value = base_params.get(key)
        value = params[key]
        ratio = _numeric_ratio(base_value, value) if key in ratio_keys else None
        if ratio is not None:
            value_label = f"x{_format_number(ratio)}"
        else:
            value_label = _format_value(value)
        parts.append(f"{_slugify(key_label)}-{_slugify(value_label)}")

    label = "-".join(part for part in parts if part.strip("-"))
    return _truncate_slug(label or "run", naming.max_length)


def render_run_directory_name(
    run_id: str,
    display_name: str,
    naming: NamingConfig | None = None,
) -> str:
    """Render a safe run directory basename containing the immutable run ID."""
    config = naming or NamingConfig()
    label = _truncate_slug(_slugify(display_name), config.max_length)
    if not label:
        return run_id
    return config.directory_template.format(run_id=run_id, label=label)


def preview_run_directory_name(display_name: str, naming: NamingConfig) -> str:
    """Render the directory pattern shown by non-mutating survey dry-runs."""
    return render_run_directory_name("{run_id}", display_name, naming)


def _numeric_ratio(base_value: Any, value: Any) -> float | None:
    if isinstance(base_value, bool) or isinstance(value, bool):
        return None
    if not isinstance(base_value, _NUMBER_TYPES) or not isinstance(
        value, _NUMBER_TYPES
    ):
        return None
    numeric_base = float(base_value)
    numeric_value = float(value)
    if (
        not math.isfinite(numeric_base)
        or not math.isfinite(numeric_value)
        or math.isclose(numeric_base, 0.0)
    ):
        return None
    ratio = numeric_value / numeric_base
    return ratio if math.isfinite(ratio) else None


def _format_number(value: float) -> str:
    if math.isclose(value, round(value)):
        return str(round(value))
    return f"{value:.6g}"


def _format_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def _default_alias(key: str) -> str:
    normalized = key.replace("[", "-").replace("]", "")
    return normalized.rsplit(".", 1)[-1]


def _slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).lower()
    characters = [character if character.isalnum() else "-" for character in normalized]
    return "-".join(part for part in "".join(characters).split("-") if part)


def _truncate_slug(value: str, max_length: int) -> str:
    return value[:max_length].rstrip("-")
