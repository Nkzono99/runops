"""Survey expansion and parameter sweep.

Reads survey.toml and expands parameter axes into individual run configurations.
Supports both Cartesian product (axes) and co-varying (linked) parameters.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import os
import re
import stat
import string
import sys
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Literal, cast

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
from runops.core.survey.naming import (
    DEFAULT_DIRECTORY_TEMPLATE,
    NamingConfig,
    NamingGroup,
)

_SURVEY_FILE = "survey.toml"
_EXPERIMENT_ID_RE = re.compile(r"^E\d{8}-\d{4}$")
_RUN_ID_RE = re.compile(r"^R\d{8}-\d{4}$")
_SURVEY_PHASES = frozenset({"pilot", "main", "followup"})
_SURVEY_PURPOSES = frozenset({"explore", "confirm", "validate", "reproduce"})

SurveyPhase = Literal["pilot", "main", "followup"]
SurveyPurpose = Literal["explore", "confirm", "validate", "reproduce"]


@dataclass(frozen=True)
class SurveyIntent:
    """Scientific intent inherited by materialized runs."""

    purpose: SurveyPurpose | None = None
    information_gap: str = ""
    baseline_run: str = ""
    created_by: str = ""
    goal_id: str = ""


@dataclass(frozen=True)
class SurveyBudget:
    """Optional materialization envelope narrower than its Experiment budget."""

    max_materialized_runs: int | None = None
    max_core_hours: float | None = None


@dataclass(frozen=True)
class SurveyRetention:
    """Review metadata; dates never grant automatic deletion authority."""

    classification: str = ""
    review_after: str = ""
    expire_after: str = ""


@dataclass(frozen=True)
class SurveyPoint:
    """One deterministic candidate with a hash of its full effective params."""

    point_id: str
    ordinal: int
    params: dict[str, Any]


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
        naming: Deterministic display and directory naming rules.
        job: Slurm job configuration.
        survey_dir: Absolute path to the survey directory.
        raw: The raw parsed survey.toml dictionary.
    """

    id: str
    name: str
    base_case: str
    simulator: str
    launcher: str
    experiment_id: str = ""
    phase: SurveyPhase | None = None
    intent: SurveyIntent = field(default_factory=SurveyIntent)
    budget: SurveyBudget = field(default_factory=SurveyBudget)
    retention: SurveyRetention = field(default_factory=SurveyRetention)
    classification: ClassificationData = field(default_factory=ClassificationData)
    axes: dict[str, list[Any]] = field(default_factory=dict)
    linked: list[dict[str, list[Any]]] = field(default_factory=list)
    naming: NamingConfig = field(default_factory=NamingConfig)
    job: JobData = field(default_factory=JobData)
    survey_dir: Path = field(default_factory=lambda: Path("."))
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def naming_template(self) -> str:
        """Compatibility accessor for the configured display-name template."""
        return self.naming.display_name


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
    survey_dir = Path(os.path.abspath(survey_dir.expanduser()))
    try:
        directory_metadata = survey_dir.lstat()
    except OSError as exc:
        raise SurveyConfigError(
            f"Cannot inspect survey directory {survey_dir}: {exc}"
        ) from exc
    if stat.S_ISLNK(directory_metadata.st_mode) or not stat.S_ISDIR(
        directory_metadata.st_mode
    ):
        raise SurveyConfigError(
            f"Survey directory must be a real directory: {survey_dir}"
        )
    survey_dir = survey_dir.resolve(strict=True)
    survey_file = survey_dir / _SURVEY_FILE

    try:
        file_metadata = survey_file.lstat()
    except FileNotFoundError as exc:
        raise SurveyConfigError(f"{_SURVEY_FILE} not found in {survey_dir}") from exc
    except OSError as exc:
        raise SurveyConfigError(f"Cannot inspect {survey_file}: {exc}") from exc
    if not stat.S_ISREG(file_metadata.st_mode) or file_metadata.st_nlink != 1:
        raise SurveyConfigError(
            f"{_SURVEY_FILE} must be a single-link regular file: {survey_file}"
        )

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

    experiment_id = _parse_optional_string(
        survey_section,
        "experiment_id",
        "survey.experiment_id",
        survey_file,
    )
    if experiment_id and _EXPERIMENT_ID_RE.fullmatch(experiment_id) is None:
        raise SurveyConfigError(
            f"survey.experiment_id must match EYYYYMMDD-NNNN in {survey_file}"
        )

    phase_value = survey_section.get("phase")
    phase: SurveyPhase | None = None
    if phase_value is not None:
        if not isinstance(phase_value, str) or phase_value not in _SURVEY_PHASES:
            raise SurveyConfigError(
                f"survey.phase must be one of {sorted(_SURVEY_PHASES)} in {survey_file}"
            )
        phase = cast("SurveyPhase", phase_value)

    intent = _parse_intent(raw.get("intent"), survey_file)
    budget = _parse_budget(raw.get("budget"), survey_file)
    retention = _parse_retention(raw.get("retention"), survey_file)

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
    seen_linked_keys: set[str] = set()
    if isinstance(linked_section, list):
        for i, group in enumerate(linked_section):
            if not isinstance(group, dict):
                raise SurveyConfigError(
                    f"[[linked]] entry {i} must be a table in {survey_file}"
                )
            parsed_group: dict[str, list[Any]] = {}
            lengths: set[int] = set()
            for key, values in group.items():
                if key in seen_linked_keys:
                    raise SurveyConfigError(
                        f"Linked parameter '{key}' appears in multiple [[linked]]"
                        f" groups in {survey_file}"
                    )
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
                seen_linked_keys.update(parsed_group)
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

    naming = _parse_naming(raw.get("naming", {}), survey_file)

    job = _parse_job(raw.get("job", {}))

    return SurveyData(
        id=survey_id,
        name=name,
        base_case=str(base_case),
        simulator=str(simulator),
        launcher=str(launcher),
        experiment_id=experiment_id,
        phase=phase,
        intent=intent,
        budget=budget,
        retention=retention,
        classification=classification,
        axes=axes,
        linked=linked,
        naming=naming,
        job=job,
        survey_dir=survey_dir,
        raw=raw,
    )


def _parse_intent(raw: Any, survey_file: Path) -> SurveyIntent:
    if raw is None:
        return SurveyIntent()
    if not isinstance(raw, dict):
        raise SurveyConfigError(f"Invalid [intent] section in {survey_file}")
    purpose_value = raw.get("purpose")
    purpose: SurveyPurpose | None = None
    if purpose_value is not None:
        if not isinstance(purpose_value, str) or purpose_value not in _SURVEY_PURPOSES:
            raise SurveyConfigError(
                f"intent.purpose must be one of {sorted(_SURVEY_PURPOSES)}"
                f" in {survey_file}"
            )
        purpose = cast("SurveyPurpose", purpose_value)

    baseline_run = _parse_optional_string(
        raw,
        "baseline_run",
        "intent.baseline_run",
        survey_file,
    )
    if baseline_run and _RUN_ID_RE.fullmatch(baseline_run) is None:
        raise SurveyConfigError(
            f"intent.baseline_run must match RYYYYMMDD-NNNN in {survey_file}"
        )
    return SurveyIntent(
        purpose=purpose,
        information_gap=_parse_optional_string(
            raw,
            "information_gap",
            "intent.information_gap",
            survey_file,
        ),
        baseline_run=baseline_run,
        created_by=_parse_optional_string(
            raw,
            "created_by",
            "intent.created_by",
            survey_file,
        ),
        goal_id=_parse_optional_string(
            raw,
            "goal_id",
            "intent.goal_id",
            survey_file,
        ),
    )


def _parse_budget(raw: Any, survey_file: Path) -> SurveyBudget:
    if raw is None:
        return SurveyBudget()
    if not isinstance(raw, dict):
        raise SurveyConfigError(f"Invalid [budget] section in {survey_file}")

    max_materialized_runs = _parse_optional_positive_int(
        raw,
        "max_materialized_runs",
        "budget.max_materialized_runs",
        survey_file,
    )
    max_core_hours = _parse_optional_positive_number(
        raw,
        "max_core_hours",
        "budget.max_core_hours",
        survey_file,
    )
    return SurveyBudget(
        max_materialized_runs=max_materialized_runs,
        max_core_hours=max_core_hours,
    )


def _parse_retention(raw: Any, survey_file: Path) -> SurveyRetention:
    if raw is None:
        return SurveyRetention()
    if not isinstance(raw, dict):
        raise SurveyConfigError(f"Invalid [retention] section in {survey_file}")
    return SurveyRetention(
        classification=_parse_optional_string(
            raw,
            "class",
            "retention.class",
            survey_file,
        ),
        review_after=_parse_optional_string(
            raw,
            "review_after",
            "retention.review_after",
            survey_file,
        ),
        expire_after=_parse_optional_string(
            raw,
            "expire_after",
            "retention.expire_after",
            survey_file,
        ),
    )


def _parse_optional_string(
    section: dict[str, Any],
    key: str,
    label: str,
    path: Path,
) -> str:
    value = section.get(key)
    if value is None:
        return ""
    if not isinstance(value, str) or not value.strip():
        raise SurveyConfigError(f"{label} must be a non-empty string in {path}")
    return value.strip()


def _parse_optional_positive_int(
    section: dict[str, Any],
    key: str,
    label: str,
    path: Path,
) -> int | None:
    value = section.get(key)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise SurveyConfigError(f"{label} must be a positive integer in {path}")
    return value


def _parse_optional_positive_number(
    section: dict[str, Any],
    key: str,
    label: str,
    path: Path,
) -> float | None:
    value = section.get(key)
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise SurveyConfigError(f"{label} must be a positive number in {path}")
    try:
        parsed = float(value)
    except OverflowError as exc:
        raise SurveyConfigError(
            f"{label} must be a finite positive number in {path}"
        ) from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise SurveyConfigError(f"{label} must be a finite positive number in {path}")
    return parsed


def _parse_naming(raw: Any, survey_file: Path) -> NamingConfig:
    """Parse and validate deterministic run naming rules."""
    if not isinstance(raw, dict):
        raise SurveyConfigError(f"Invalid [naming] section in {survey_file}")

    display_name = str(raw.get("display_name", ""))
    directory_template = str(raw.get("directory", DEFAULT_DIRECTORY_TEMPLATE)).strip()
    _validate_directory_template(directory_template, survey_file)

    max_length = raw.get("max_length", 48)
    if (
        not isinstance(max_length, int)
        or isinstance(max_length, bool)
        or max_length < 1
        or max_length > 120
    ):
        raise SurveyConfigError(
            f"naming.max_length must be an integer from 1 to 120 in {survey_file}"
        )

    raw_aliases = raw.get("aliases", {})
    if not isinstance(raw_aliases, dict):
        raise SurveyConfigError(f"naming.aliases must be a table in {survey_file}")
    aliases: dict[str, str] = {}
    for key, value in raw_aliases.items():
        if not isinstance(value, str) or not value.strip():
            raise SurveyConfigError(
                f"Naming alias for {key!r} must be a non-empty string in {survey_file}"
            )
        aliases[str(key)] = value.strip()

    raw_groups = raw.get("groups", [])
    if not isinstance(raw_groups, list):
        raise SurveyConfigError(
            f"naming.groups must be an array of tables in {survey_file}"
        )
    groups: list[NamingGroup] = []
    grouped_keys: set[str] = set()
    for index, raw_group in enumerate(raw_groups):
        if not isinstance(raw_group, dict):
            raise SurveyConfigError(
                f"naming.groups entry {index} must be a table in {survey_file}"
            )
        label = raw_group.get("label")
        keys = raw_group.get("keys")
        strategy = str(raw_group.get("strategy", "uniform_ratio"))
        if not isinstance(label, str) or not label.strip():
            raise SurveyConfigError(
                f"naming.groups entry {index} requires a non-empty label"
                f" in {survey_file}"
            )
        if (
            not isinstance(keys, list)
            or not keys
            or not all(isinstance(key, str) and key for key in keys)
            or len(set(keys)) != len(keys)
        ):
            raise SurveyConfigError(
                f"naming.groups entry {index} keys must contain unique names"
                f" in {survey_file}"
            )
        if strategy != "uniform_ratio":
            raise SurveyConfigError(
                f"Unsupported naming.groups strategy {strategy!r} in {survey_file}"
            )
        key_tuple = tuple(keys)
        overlap = grouped_keys.intersection(key_tuple)
        if overlap:
            raise SurveyConfigError(
                f"Naming group keys {sorted(overlap)} appear in multiple groups"
                f" in {survey_file}"
            )
        grouped_keys.update(key_tuple)
        groups.append(
            NamingGroup(
                label=label.strip(),
                keys=key_tuple,
                strategy=strategy,
            )
        )

    return NamingConfig(
        display_name=display_name,
        directory_template=directory_template,
        max_length=max_length,
        aliases=aliases,
        groups=tuple(groups),
    )


def _validate_directory_template(template: str, survey_file: Path) -> None:
    if not template or "/" in template or "\\" in template:
        raise SurveyConfigError(
            f"naming.directory must be a directory basename in {survey_file}"
        )
    try:
        parsed_fields = list(string.Formatter().parse(template))
    except ValueError as exc:
        raise SurveyConfigError(
            f"Invalid naming.directory template in {survey_file}: {exc}"
        ) from exc
    fields = [field_name for _, field_name, _, _ in parsed_fields if field_name]
    has_advanced_formatting = any(
        format_spec or conversion
        for _, field_name, format_spec, conversion in parsed_fields
        if field_name is not None
    )
    if (
        fields.count("run_id") != 1
        or fields.count("label") > 1
        or not set(fields).issubset({"run_id", "label"})
        or has_advanced_formatting
    ):
        raise SurveyConfigError(
            "naming.directory must contain one plain {run_id} and at most one "
            f"plain {{label}} in {survey_file}"
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


def count_survey_points(
    axes: Mapping[str, list[Any]],
    linked: list[dict[str, list[Any]]],
) -> int:
    """Count a sweep without constructing its Cartesian product."""
    if not axes and not linked:
        return 0

    count = 1
    for values in axes.values():
        count *= len(values)
    for group in linked:
        if not group:
            continue
        first_values = next(iter(group.values()))
        count *= len(first_values)
    return count


def iter_survey_points(
    axes: Mapping[str, list[Any]],
    linked: list[dict[str, list[Any]]],
    *,
    base_params: Mapping[str, Any] | None = None,
) -> Iterator[SurveyPoint]:
    """Yield deterministic candidate points without materializing the sweep.

    ``point_id`` hashes the full effective parameter mapping, including
    ``base_params``.  Duplicate effective conditions intentionally receive the
    same ID so an application-level materialization gate can reject or reuse
    them; ``ordinal`` still identifies their positions in the declared plan.
    """
    if not axes and not linked:
        return

    axis_items = list(axes.items())
    linked_groups = [group for group in linked if group]
    dimensions: list[Iterable[Any]] = [values for _, values in axis_items]
    dimensions.extend(range(len(next(iter(group.values())))) for group in linked_groups)

    for ordinal, choices in enumerate(itertools.product(*dimensions), start=1):
        params = dict(base_params or {})
        cursor = 0
        for key, _ in axis_items:
            params[key] = choices[cursor]
            cursor += 1
        for group in linked_groups:
            linked_index = cast("int", choices[cursor])
            cursor += 1
            for key, values in group.items():
                params[key] = values[linked_index]
        yield SurveyPoint(
            point_id=canonical_data_hash(params),
            ordinal=ordinal,
            params=params,
        )


def canonical_data_hash(value: Any) -> str:
    """Return a stable SHA-256 identity for TOML-compatible structured data."""
    normalized = _normalize_for_hash(value)
    encoded = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _normalize_for_hash(value: Any) -> Any:
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        keys = list(value.keys())
        if not all(isinstance(key, str) for key in keys):
            raise SurveyConfigError(
                "Canonical survey hashes require string mapping keys"
            )
        for key in sorted(cast("list[str]", keys)):
            normalized[key] = _normalize_for_hash(value[key])
        return normalized
    if isinstance(value, (list, tuple)):
        return [_normalize_for_hash(item) for item in value]
    if isinstance(value, datetime):
        return {"$runops_type": "datetime", "value": value.isoformat()}
    if isinstance(value, date):
        return {"$runops_type": "date", "value": value.isoformat()}
    if isinstance(value, time):
        return {"$runops_type": "time", "value": value.isoformat()}
    if isinstance(value, float) and not math.isfinite(value):
        return {"$runops_type": "float", "value": repr(value)}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise SurveyConfigError(
        f"Unsupported value type in canonical survey hash: {type(value).__name__}"
    )


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
