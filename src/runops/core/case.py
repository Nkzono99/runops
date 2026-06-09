"""Case loading and expansion.

Reads case.toml files and prepares case data for run generation.
A Case is a reusable base definition from which runs or surveys are generated.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from runops.core.exceptions import CaseConfigError, CaseNotFoundError

_CASE_FILE = "case.toml"


@dataclass(frozen=True)
class ClassificationData:
    """Classification metadata for a case or run.

    Attributes:
        model: Model category (e.g. "cavity").
        submodel: Sub-model category (e.g. "rectangular").
        tags: List of tags for filtering and organization.
    """

    model: str = ""
    submodel: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class JobData:
    """Scheduler job configuration.

    Supports both standard Slurm (nodes/ntasks) and the camphor-style
    ``--rsc p=N:t=T:c=C`` directive.  Which directive is emitted is decided
    by the active site profile (``site.toml`` ``resource_style``), not by
    fields stored on this dataclass.  Both groups of fields can be set in
    ``case.toml``; the ones unused by the active site are ignored.
    PBS sites use ``nodes`` with ``sockets``/``mpiprocs``/``ompthreads`` to
    render ``#PBS -l select=...``.

    Attributes:
        partition: Slurm partition name or PBS queue name.
        nodes: Number of nodes (standard Slurm / PBS mode).
        ntasks: Number of MPI tasks (standard Slurm mode, or total PBS ranks).
        sockets: PBS CPU sockets per node (``nsockets``).
        mpiprocs: PBS MPI processes per node. 0 means derive from ntasks/nodes.
        ompthreads: PBS OpenMP threads per MPI process. 0 means not specified.
        group: PBS group name emitted as ``group_list``.
        walltime: Wall-clock time limit string (HH:MM:SS or H:MM:SS).
        processes: Number of MPI processes (rsc mode, ``p``).
        threads: Threads per process (rsc mode, ``t``). Must be <= cores.
        cores: Cores per process (rsc mode, ``c``). Must be >= threads.
        memory: Memory per process (rsc mode, ``m``), e.g. ``"8G"``.
            Empty string means not specified.
        gpus: Number of GPUs per node (rsc mode, ``g``). 0 means not specified.
        qos: Slurm QOS name.  Empty string means not specified.
        modules: Module names to load before execution.
        pre_commands: Shell commands to run before the main execution.
        post_commands: Shell commands to run after the main execution.
    """

    partition: str = ""
    nodes: int = 1
    ntasks: int = 1
    sockets: int = 1
    mpiprocs: int = 0
    ompthreads: int = 0
    group: str = ""
    walltime: str = "01:00:00"
    processes: int = 1
    threads: int = 1
    cores: int = 1
    memory: str = ""
    gpus: int = 0
    qos: str = ""
    modules: list[str] = field(default_factory=list)
    pre_commands: list[str] = field(default_factory=list)
    post_commands: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CaseData:
    """Immutable representation of a case.toml configuration.

    Matches SPEC section 10.2.

    Attributes:
        name: Case name (required).
        simulator: Simulator name (required).
        launcher: Launcher profile name (required).
        description: Human-readable description.
        classification: Classification metadata.
        job: Slurm job configuration.
        params: Simulator-specific parameters.
        case_dir: Absolute path to the case directory.
        raw: The raw parsed case.toml dictionary.
    """

    name: str
    simulator: str
    launcher: str
    description: str = ""
    classification: ClassificationData = field(default_factory=ClassificationData)
    job: JobData = field(default_factory=JobData)
    params: dict[str, Any] = field(default_factory=dict)
    case_dir: Path = field(default_factory=lambda: Path("."))
    raw: dict[str, Any] = field(default_factory=dict)


def _parse_classification(data: dict[str, Any]) -> ClassificationData:
    """Parse a [classification] section from TOML data.

    Args:
        data: Raw classification dictionary.

    Returns:
        ClassificationData instance.
    """
    tags = data.get("tags", [])
    if not isinstance(tags, list):
        tags = [str(tags)]
    return ClassificationData(
        model=str(data.get("model", "")),
        submodel=str(data.get("submodel", "")),
        tags=[str(t) for t in tags],
    )


def _parse_job(data: dict[str, Any]) -> JobData:
    """Parse a [job] section from TOML data.

    Supports both standard mode (nodes/ntasks) and rsc mode
    (processes/threads/cores).

    Args:
        data: Raw job dictionary.

    Returns:
        JobData instance.
    """
    modules_raw = data.get("modules", [])
    modules = list(modules_raw) if isinstance(modules_raw, list) else []
    pre_raw = data.get("pre_commands", [])
    pre_commands = list(pre_raw) if isinstance(pre_raw, list) else []
    post_raw = data.get("post_commands", [])
    post_commands = list(post_raw) if isinstance(post_raw, list) else []

    return JobData(
        partition=str(data.get("partition", "")),
        nodes=int(data.get("nodes", 1)),
        ntasks=int(data.get("ntasks", 1)),
        sockets=int(data.get("sockets", 1)),
        mpiprocs=int(data.get("mpiprocs", 0)),
        ompthreads=int(data.get("ompthreads", 0)),
        group=str(data.get("group", data.get("group_list", ""))),
        walltime=str(data.get("walltime", "01:00:00")),
        processes=int(data.get("processes", 1)),
        threads=int(data.get("threads", 1)),
        cores=int(data.get("cores", 1)),
        memory=str(data.get("memory", "")),
        gpus=int(data.get("gpus", 0)),
        qos=str(data.get("qos", "")),
        modules=[str(m) for m in modules],
        pre_commands=[str(c) for c in pre_commands],
        post_commands=[str(c) for c in post_commands],
    )


def _is_valid_walltime(walltime: str) -> bool:
    """Check if a walltime string has valid HH:MM:SS or D-HH:MM:SS format."""
    import re

    # D-HH:MM:SS or HH:MM:SS or H:MM:SS or MM:SS
    return bool(re.match(r"^(\d+-)?(\d{1,3}:)?\d{1,2}:\d{2}$", walltime))


def load_case(case_dir: Path) -> CaseData:
    """Load and validate a case.toml file.

    Args:
        case_dir: Directory containing case.toml.

    Returns:
        Validated CaseData instance.

    Raises:
        CaseNotFoundError: If case.toml does not exist.
        CaseConfigError: If required fields are missing or invalid.
    """
    case_dir = case_dir.resolve()
    case_file = case_dir / _CASE_FILE

    if not case_file.exists():
        raise CaseNotFoundError(f"{_CASE_FILE} not found in {case_dir}")

    try:
        with open(case_file, "rb") as f:
            raw = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise CaseConfigError(f"Invalid TOML in {case_file}: {e}") from e

    case_section = raw.get("case")
    if not isinstance(case_section, dict):
        raise CaseConfigError(f"Missing or invalid [case] section in {case_file}")

    name = case_section.get("name")
    if not isinstance(name, str) or not name:
        raise CaseConfigError(f"Missing or empty 'case.name' in {case_file}")

    simulator = case_section.get("simulator")
    if not isinstance(simulator, str) or not simulator:
        raise CaseConfigError(f"Missing or empty 'case.simulator' in {case_file}")

    launcher = case_section.get("launcher")
    if not isinstance(launcher, str) or not launcher:
        raise CaseConfigError(f"Missing or empty 'case.launcher' in {case_file}")

    description = str(case_section.get("description", ""))

    classification = _parse_classification(raw.get("classification", {}))
    job = _parse_job(raw.get("job", {}))
    params = dict(raw.get("params", {}))

    # Validate walltime format
    if job.walltime and not _is_valid_walltime(job.walltime):
        raise CaseConfigError(
            f"Invalid walltime format '{job.walltime}' in {case_file}. "
            f"Expected HH:MM:SS or D-HH:MM:SS."
        )

    # Warn about unknown top-level keys
    known_sections = {
        "case",
        "classification",
        "job",
        "params",
        "slurm",
    }
    for key in raw:
        if key not in known_sections:
            import logging

            logging.getLogger(__name__).warning(
                "Unknown section [%s] in %s", key, case_file
            )

    return CaseData(
        name=name,
        simulator=simulator,
        launcher=launcher,
        description=description,
        classification=classification,
        job=job,
        params=params,
        case_dir=case_dir,
        raw=raw,
    )


def resolve_case(case_name: str, project_dir: Path) -> Path:
    """Resolve a case name to its directory path.

    Resolution order:
    1. ``cases/<case_name>/case.toml`` (exact match, supports ``sim/name``)
    2. ``cases/<campaign_simulator>/<case_name>/case.toml``
    3. Scan all ``cases/<sim>/<case_name>/case.toml`` subdirectories

    Args:
        case_name: Logical name of the case (e.g. ``"flat"`` or ``"emses/flat"``).
        project_dir: Root of the runops project.

    Returns:
        Path to the case directory.

    Raises:
        CaseNotFoundError: If the case directory or case.toml is not found.
    """
    cases_root = project_dir.resolve() / "cases"

    # 1. Direct match: cases/<case_name>/case.toml
    case_dir = cases_root / case_name
    if case_dir.is_dir() and (case_dir / _CASE_FILE).exists():
        return case_dir

    # 2. Campaign simulator fallback: cases/<campaign.simulator>/<case_name>
    from runops.core.campaign import load_campaign

    campaign = load_campaign(project_dir)
    if campaign and campaign.simulator:
        case_dir = cases_root / campaign.simulator / case_name
        if case_dir.is_dir() and (case_dir / _CASE_FILE).exists():
            return case_dir

    # 3. Scan all simulator subdirectories
    if cases_root.is_dir():
        matches: list[Path] = []
        for sim_dir in sorted(cases_root.iterdir()):
            candidate = sim_dir / case_name
            if candidate.is_dir() and (candidate / _CASE_FILE).exists():
                matches.append(candidate)
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            paths = ", ".join(str(m.relative_to(project_dir)) for m in matches)
            raise CaseNotFoundError(
                f"Ambiguous case name '{case_name}': found in multiple "
                f"simulators ({paths}). Use '<simulator>/{case_name}' to "
                f"disambiguate."
            )

    raise CaseNotFoundError(
        f"Case '{case_name}' not found under {cases_root}. "
        f"Tried: cases/{case_name}/, cases/<sim>/{case_name}/."
    )
