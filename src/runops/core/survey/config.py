"""Survey expansion and parameter sweep.

Reads survey.toml and expands parameter axes into individual run configurations.
Supports both Cartesian product (axes) and co-varying (linked) parameters.
"""

from __future__ import annotations

import itertools
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from runops.core.case import (
    ClassificationData,
    JobData,
    _parse_classification,
    _parse_job,
)
from runops.core.exceptions import SurveyConfigError

_SURVEY_FILE = "survey.toml"


@dataclass(frozen=True)
class SurveyData:
    """Immutable representation of a survey.toml configuration.

    Matches SPEC section 11.2.

    Attributes:
        id: Survey identifier (e.g. "S20260327-cavity-u-a").
        name: Human-readable survey name.
        base_case: Name of the base case to derive runs from.
        simulator: Simulator name.
        launcher: Launcher profile name.
        classification: Classification metadata.
        axes: Parameter axes for cartesian product expansion.
        linked: List of co-varying parameter groups (zip expansion).
        naming_template: Template string for generating display_name.
        job: Slurm job configuration.
        survey_dir: Absolute path to the survey directory.
        raw: The raw parsed survey.toml dictionary.
    """

    id: str
    name: str
    base_case: str
    simulator: str
    launcher: str
    classification: ClassificationData = field(default_factory=ClassificationData)
    axes: dict[str, list[Any]] = field(default_factory=dict)
    linked: list[dict[str, list[Any]]] = field(default_factory=list)
    naming_template: str = ""
    job: JobData = field(default_factory=JobData)
    survey_dir: Path = field(default_factory=lambda: Path("."))
    raw: dict[str, Any] = field(default_factory=dict)


def load_survey(survey_dir: Path) -> SurveyData:
    """Load and validate a survey.toml file.

    Args:
        survey_dir: Directory containing survey.toml.

    Returns:
        Validated SurveyData instance.

    Raises:
        SurveyConfigError: If survey.toml is missing, invalid, or lacks
            required fields.
    """
    survey_dir = survey_dir.resolve()
    survey_file = survey_dir / _SURVEY_FILE

    if not survey_file.exists():
        raise SurveyConfigError(f"{_SURVEY_FILE} not found in {survey_dir}")

    try:
        with open(survey_file, "rb") as f:
            raw = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise SurveyConfigError(f"Invalid TOML in {survey_file}: {e}") from e

    survey_section = raw.get("survey")
    if not isinstance(survey_section, dict):
        raise SurveyConfigError(f"Missing or invalid [survey] section in {survey_file}")

    survey_id = survey_section.get("id")
    if not isinstance(survey_id, str) or not survey_id:
        # Auto-generate survey id from date and directory name
        from datetime import datetime, timezone

        date_str = datetime.now(tz=timezone.utc).strftime("%Y%m%d")
        dir_slug = survey_dir.name.replace(" ", "-")
        survey_id = f"S{date_str}-{dir_slug}"

    name = str(survey_section.get("name", ""))

    # Validate required fields, collecting all errors at once
    errors: list[str] = []
    base_case = survey_section.get("base_case")
    if not isinstance(base_case, str) or not base_case:
        errors.append("survey.base_case")

    simulator = survey_section.get("simulator")
    if not isinstance(simulator, str) or not simulator:
        errors.append("survey.simulator")

    launcher = survey_section.get("launcher")
    if not isinstance(launcher, str) or not launcher:
        errors.append("survey.launcher")

    if errors:
        missing = ", ".join(errors)
        raise SurveyConfigError(
            f"Missing or empty required fields in {survey_file}: {missing}"
        )

    classification = _parse_classification(raw.get("classification", {}))

    # Parse axes
    axes_section = raw.get("axes", {})
    if not isinstance(axes_section, dict):
        raise SurveyConfigError(f"Invalid [axes] section in {survey_file}")
    axes: dict[str, list[Any]] = {}
    for key, values in axes_section.items():
        if not isinstance(values, list):
            raise SurveyConfigError(f"Axis '{key}' must be a list in {survey_file}")
        if len(values) == 0:
            raise SurveyConfigError(f"Axis '{key}' must not be empty in {survey_file}")
        axes[key] = values

    # Parse linked parameter groups
    linked_section = raw.get("linked", [])
    linked: list[dict[str, list[Any]]] = []
    if isinstance(linked_section, list):
        for i, group in enumerate(linked_section):
            if not isinstance(group, dict):
                raise SurveyConfigError(
                    f"[[linked]] entry {i} must be a table in {survey_file}"
                )
            parsed_group: dict[str, list[Any]] = {}
            lengths: set[int] = set()
            for key, values in group.items():
                if not isinstance(values, list):
                    raise SurveyConfigError(
                        f"Linked parameter '{key}' in group {i} must be a list"
                        f" in {survey_file}"
                    )
                if len(values) == 0:
                    raise SurveyConfigError(
                        f"Linked parameter '{key}' in group {i} must not be empty"
                        f" in {survey_file}"
                    )
                lengths.add(len(values))
                parsed_group[key] = values
            if len(lengths) > 1:
                raise SurveyConfigError(
                    f"All parameters in [[linked]] group {i} must have the same"
                    f" number of values (got {sorted(lengths)}) in {survey_file}"
                )
            if parsed_group:
                linked.append(parsed_group)
    elif isinstance(linked_section, dict):
        raise SurveyConfigError(
            f"[linked] must be an array of tables ([[linked]]), not a single"
            f" table in {survey_file}"
        )

    # Validate no overlap between axes and linked keys
    axes_keys = set(axes.keys())
    for i, group in enumerate(linked):
        linked_keys = set(group.keys())
        overlap = axes_keys & linked_keys
        if overlap:
            raise SurveyConfigError(
                f"Parameters {overlap} appear in both [axes] and [[linked]]"
                f" group {i} in {survey_file}"
            )

    # Parse naming template
    naming_section = raw.get("naming", {})
    naming_template = ""
    if isinstance(naming_section, dict):
        naming_template = str(naming_section.get("display_name", ""))

    job = _parse_job(raw.get("job", {}))

    return SurveyData(
        id=survey_id,
        name=name,
        base_case=str(base_case),
        simulator=str(simulator),
        launcher=str(launcher),
        classification=classification,
        axes=axes,
        linked=linked,
        naming_template=naming_template,
        job=job,
        survey_dir=survey_dir,
        raw=raw,
    )


def expand_axes(axes: dict[str, list[Any]]) -> list[dict[str, Any]]:
    """Compute the cartesian product of parameter axes.

    Args:
        axes: Mapping of parameter names to lists of values.

    Returns:
        List of parameter dictionaries, one per combination.
        Empty list if axes is empty.

    Example:
        >>> expand_axes({"a": [1, 2], "b": [10, 20]})
        [{"a": 1, "b": 10}, {"a": 1, "b": 20}, {"a": 2, "b": 10}, {"a": 2, "b": 20}]
    """
    if not axes:
        return []

    keys = list(axes.keys())
    value_lists = [axes[k] for k in keys]

    return [
        dict(zip(keys, combo, strict=True)) for combo in itertools.product(*value_lists)
    ]


def _expand_linked(linked: list[dict[str, list[Any]]]) -> list[dict[str, Any]]:
    """Expand linked parameter groups via zip, then Cartesian product across groups.

    Each group's parameters co-vary (zip). Multiple groups are combined via
    Cartesian product with each other.

    Args:
        linked: List of linked parameter groups.

    Returns:
        List of parameter dictionaries from linked expansion.
        Returns [{}] if linked is empty (identity for Cartesian product).
    """
    if not linked:
        return [{}]

    # Each group produces a list of dicts (zip within group)
    group_expansions: list[list[dict[str, Any]]] = []
    for group in linked:
        keys = list(group.keys())
        n = len(group[keys[0]])
        zipped = [{k: group[k][i] for k in keys} for i in range(n)]
        group_expansions.append(zipped)

    # Cartesian product across groups
    if len(group_expansions) == 1:
        return group_expansions[0]

    result: list[dict[str, Any]] = []
    for combo in itertools.product(*group_expansions):
        merged: dict[str, Any] = {}
        for d in combo:
            merged.update(d)
        result.append(merged)
    return result


def expand_survey(
    axes: dict[str, list[Any]],
    linked: list[dict[str, list[Any]]],
) -> list[dict[str, Any]]:
    """Expand both axes (Cartesian product) and linked (co-varying) parameters.

    The final result is the Cartesian product of:
    - The axes expansion (Cartesian product of independent axes)
    - The linked expansion (zip within each group, Cartesian across groups)

    Args:
        axes: Parameter axes for Cartesian product.
        linked: List of co-varying parameter groups.

    Returns:
        List of parameter dictionaries, one per combination.

    Example:
        >>> expand_survey({"seed": [1, 2]}, [{"nx": [32, 64], "ny": [32, 64]}])
        [
            {"seed": 1, "nx": 32, "ny": 32},
            {"seed": 1, "nx": 64, "ny": 64},
            {"seed": 2, "nx": 32, "ny": 32},
            {"seed": 2, "nx": 64, "ny": 64},
        ]
    """
    axes_combos = expand_axes(axes)
    linked_combos = _expand_linked(linked)

    if not axes_combos and not linked:
        return []
    if not axes_combos:
        return linked_combos
    if not linked:
        return axes_combos

    result: list[dict[str, Any]] = []
    for axes_dict, linked_dict in itertools.product(axes_combos, linked_combos):
        result.append({**axes_dict, **linked_dict})
    return result


def generate_display_name(template: str, params: dict[str, Any]) -> str:
    """Generate a display_name from a naming template and parameters.

    Uses Python str.format_map with parameter values. Non-string
    values are formatted directly (floats use default repr).

    Args:
        template: Naming template string (e.g. "u{u}_a{aspect}_s{seed}").
        params: Parameter dictionary to substitute into the template.

    Returns:
        Rendered display name string. Returns empty string if template
        is empty.
    """
    if not template:
        return ""

    # Build a string-safe mapping, including short aliases for dotted keys
    fmt_params: dict[str, str] = {}
    for key, value in params.items():
        formatted = f"{value:g}" if isinstance(value, float) else str(value)
        fmt_params[key] = formatted

        # Normalize brackets: "species[2].ray_zenith_angle_deg"
        # → "species_2_ray_zenith_angle_deg" (underscore form)
        # → "ray_zenith_angle_deg" (leaf)
        normalized = key.replace("[", "_").replace("]", "")
        if normalized != key:
            fmt_params[normalized] = formatted

        # For dotted keys like "plasma.wc", also register the leaf name "wc"
        # and the underscore form "plasma_wc" for use in templates.
        effective = normalized if normalized != key else key
        if "." in effective:
            leaf = effective.rsplit(".", 1)[1]
            if leaf not in fmt_params:
                fmt_params[leaf] = formatted
            fmt_params[effective.replace(".", "_")] = formatted

    try:
        return template.format_map(fmt_params)
    except KeyError:
        # Missing key in params - return template with available substitutions
        return template.format_map(
            {**{k: f"{{{k}}}" for k in _extract_keys(template)}, **fmt_params}
        )


def _extract_keys(template: str) -> list[str]:
    """Extract format keys from a template string.

    Args:
        template: A Python format string.

    Returns:
        List of key names found in the template.
    """
    import string

    formatter = string.Formatter()
    keys: list[str] = []
    for _, field_name, _, _ in formatter.parse(template):
        if field_name is not None:
            keys.append(field_name)
    return keys
