"""Analysis-readiness checks for completed run directories."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runops.core.manifest import ManifestData, read_manifest
from runops.core.state import RunState


@dataclass(frozen=True)
class ArtifactCheck:
    """Result for one adapter-declared output requirement."""

    key: str
    description: str
    present: bool
    count: int
    paths: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return {
            "key": self.key,
            "description": self.description,
            "present": self.present,
            "count": self.count,
            "paths": list(self.paths),
        }


@dataclass(frozen=True)
class RunReadiness:
    """Analysis-readiness summary for one run."""

    run_id: str
    execution_status: str
    adapter: str
    simulator_status: str
    analysis_status: str
    analysis_ready: bool
    checks: tuple[ArtifactCheck, ...]
    warnings: tuple[str, ...]

    @property
    def missing_required_artifacts(self) -> tuple[str, ...]:
        """Return required output keys that were not detected."""
        return tuple(check.key for check in self.checks if not check.present)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return {
            "run_id": self.run_id,
            "execution_status": self.execution_status,
            "adapter": self.adapter,
            "simulator_status": self.simulator_status,
            "analysis_status": self.analysis_status,
            "analysis_ready": self.analysis_ready,
            "missing_required_artifacts": list(self.missing_required_artifacts),
            "checks": [check.to_dict() for check in self.checks],
            "warnings": list(self.warnings),
        }


def evaluate_run_readiness(
    run_dir: Path,
    *,
    manifest: ManifestData | None = None,
) -> RunReadiness:
    """Evaluate whether a completed run has analysis-required artifacts.

    Args:
        run_dir: Run directory containing ``manifest.toml``.
        manifest: Optional already-read manifest to avoid duplicate I/O.

    Returns:
        Readiness result. Non-completed runs are reported as
        ``analysis_status == "not_completed"`` rather than failures.
    """
    manifest_data = manifest or read_manifest(run_dir)
    run_id = str(manifest_data.run.get("id", run_dir.name))
    execution_status = str(manifest_data.run.get("status", "unknown"))
    adapter_name = _adapter_name(manifest_data)

    if execution_status != RunState.COMPLETED.value:
        return RunReadiness(
            run_id=run_id,
            execution_status=execution_status,
            adapter=adapter_name,
            simulator_status="",
            analysis_status="not_completed",
            analysis_ready=False,
            checks=(),
            warnings=(),
        )

    if not adapter_name:
        return RunReadiness(
            run_id=run_id,
            execution_status=execution_status,
            adapter="",
            simulator_status="",
            analysis_status="unknown",
            analysis_ready=False,
            checks=(),
            warnings=("No simulator adapter is recorded in manifest.toml.",),
        )

    try:
        from runops.adapters import get as get_adapter

        adapter_cls = get_adapter(adapter_name)
    except KeyError:
        return RunReadiness(
            run_id=run_id,
            execution_status=execution_status,
            adapter=adapter_name,
            simulator_status="",
            analysis_status="unknown",
            analysis_ready=False,
            checks=(),
            warnings=(f"Unknown simulator adapter: {adapter_name}.",),
        )

    adapter = adapter_cls()
    warnings: list[str] = []
    try:
        simulator_status = adapter.detect_status(run_dir)
    except Exception as exc:  # pragma: no cover - defensive adapter boundary
        simulator_status = "unknown"
        warnings.append(f"Adapter status detection failed: {exc}")

    try:
        outputs = adapter.detect_outputs(run_dir)
    except Exception as exc:  # pragma: no cover - defensive adapter boundary
        outputs = {}
        warnings.append(f"Adapter output detection failed: {exc}")

    checks: list[ArtifactCheck] = []
    for key, description in adapter.required_outputs().items():
        paths = _output_paths(outputs.get(key))
        checks.append(
            ArtifactCheck(
                key=key,
                description=description,
                present=bool(paths),
                count=len(paths),
                paths=paths,
            )
        )

    missing = [check for check in checks if not check.present]
    for check in missing:
        warnings.append(f"Missing required artifact: {check.key} ({check.description})")

    if simulator_status and simulator_status != RunState.COMPLETED.value:
        warnings.append(
            "Adapter status is "
            f"{simulator_status!r}, expected {RunState.COMPLETED.value!r}."
        )

    analysis_ready = not warnings
    analysis_status = "ready" if analysis_ready else "incomplete"
    return RunReadiness(
        run_id=run_id,
        execution_status=execution_status,
        adapter=adapter_name,
        simulator_status=simulator_status,
        analysis_status=analysis_status,
        analysis_ready=analysis_ready,
        checks=tuple(checks),
        warnings=tuple(warnings),
    )


def _adapter_name(manifest: ManifestData) -> str:
    """Return the most specific adapter name recorded in a manifest."""
    for section in (manifest.simulator, manifest.run):
        value = section.get("adapter")
        if value:
            return str(value)
    for section in (manifest.simulator, manifest.run):
        value = section.get("name") or section.get("simulator")
        if value:
            return str(value)
    return ""


def _output_paths(value: Any) -> tuple[str, ...]:
    """Normalize adapter output values into path-like strings."""
    if value is None:
        return ()
    if isinstance(value, Path):
        return (value.as_posix(),)
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Mapping):
        paths: list[str] = []
        for item in value.values():
            paths.extend(_output_paths(item))
        return tuple(paths)
    if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray)):
        paths = []
        for item in value:
            paths.extend(_output_paths(item))
        return tuple(paths)
    return (str(value),)
