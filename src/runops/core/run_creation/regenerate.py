"""Regenerate existing run inputs from recorded case metadata."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from runops.core.case import load_case, resolve_case
from runops.core.exceptions import ProjectConfigError
from runops.core.manifest import read_manifest
from runops.core.models import run_creation as run_creation_models
from runops.core.project import ProjectConfig

from .resolve import load_adapter_for_simulator
from .staging import copy_case_files

RegenerateResult = run_creation_models.RegenerateResult

_REGENERATE_ALLOWED_STATES = frozenset({"created", "failed", "cancelled"})


def regenerate_run(
    project: ProjectConfig,
    run_dir: Path,
    *,
    dry_run: bool = False,
) -> RegenerateResult:
    """Re-render ``input/`` for an existing run from its recorded case."""
    manifest = read_manifest(run_dir)
    run_id = str(manifest.run.get("id", run_dir.name))
    state = str(manifest.run.get("status", ""))
    if state not in _REGENERATE_ALLOWED_STATES:
        raise ProjectConfigError(
            f"cannot regenerate run in state '{state}': "
            f"expected one of {sorted(_REGENERATE_ALLOWED_STATES)}"
        )

    case_name = str(manifest.origin.get("case", "")) if manifest.origin else ""
    if not case_name:
        raise ProjectConfigError(
            f"run {run_id} has no origin.case recorded; cannot regenerate"
        )

    simulator_name = (
        str(manifest.simulator.get("name", "")) if manifest.simulator else ""
    )
    if not simulator_name:
        raise ProjectConfigError(
            f"run {run_id} has no simulator.name recorded; cannot regenerate"
        )

    case_dir = resolve_case(case_name, project.root_dir)
    case_data = load_case(case_dir)
    adapter = load_adapter_for_simulator(project, simulator_name)

    effective_params = dict(case_data.params)
    if manifest.params_snapshot:
        effective_params.update(manifest.params_snapshot)

    case_section = {
        **case_data.raw.get("case", {}),
        "case_dir": str(case_data.case_dir),
    }
    validation_data = {"case": case_section, "params": effective_params}

    input_dir = run_dir / "input"
    work_exists = (run_dir / "work").is_dir() and any((run_dir / "work").iterdir())

    with tempfile.TemporaryDirectory(prefix="runops-regen-") as staging_root:
        staged_run = Path(staging_root)
        (staged_run / "input").mkdir()
        copy_case_files(case_data.case_dir, staged_run / "input")
        adapter.render_inputs(validation_data, staged_run)

        staged_input = staged_run / "input"
        old_files: dict[str, bytes] = {}
        if input_dir.is_dir():
            for path in input_dir.rglob("*"):
                if path.is_file():
                    rel = str(path.relative_to(input_dir)).replace("\\", "/")
                    old_files[rel] = path.read_bytes()

        new_files: dict[str, bytes] = {}
        for path in staged_input.rglob("*"):
            if path.is_file():
                rel = str(path.relative_to(staged_input)).replace("\\", "/")
                new_files[rel] = path.read_bytes()

        added = tuple(sorted(set(new_files) - set(old_files)))
        removed = tuple(sorted(set(old_files) - set(new_files)))
        common = set(new_files) & set(old_files)
        modified = tuple(sorted(p for p in common if new_files[p] != old_files[p]))
        unchanged = tuple(sorted(p for p in common if new_files[p] == old_files[p]))

        if dry_run:
            return RegenerateResult(
                run_id=run_id,
                case_name=case_name,
                added=added,
                modified=modified,
                removed=removed,
                unchanged=unchanged,
                work_exists=work_exists,
            )

        if input_dir.is_dir():
            shutil.rmtree(input_dir)
        shutil.copytree(staged_input, input_dir)

    return RegenerateResult(
        run_id=run_id,
        case_name=case_name,
        added=added,
        modified=modified,
        removed=removed,
        unchanged=unchanged,
        work_exists=work_exists,
    )
