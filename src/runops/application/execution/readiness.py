"""Analysis-readiness checks for completed run directories."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
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
    reason_codes: tuple[str, ...] = ()
    recommended_action: str = ""
    requires_human: bool = False
    evaluation_mode: str = "deep"

    @property
    def missing_required_artifacts(self) -> tuple[str, ...]:
        """Return required output keys that were not detected."""
        return tuple(check.key for check in self.checks if not check.present)

    @property
    def partial_outputs(self) -> dict[str, int]:
        """Return compact required-output counts for action planning."""
        return {check.key: check.count for check in self.checks}

    @property
    def recommended_command(self) -> str:
        """Return an executable next command for agent workflows."""
        if self.recommended_action == "analyze":
            return f"runo analyze summarize {self.run_id}"
        if self.recommended_action == "retry":
            return f"runo runs retry {self.run_id}"
        if self.recommended_action == "review_outputs":
            return f"runo runs log {self.run_id}"
        if self.recommended_action == "deep_validate":
            return f"runo runs status {self.run_id}"
        return ""

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
            "reason_codes": list(self.reason_codes),
            "recommended_action": self.recommended_action,
            "recommended_command": self.recommended_command,
            "requires_human": self.requires_human,
            "evaluation_mode": self.evaluation_mode,
            "partial_outputs": self.partial_outputs,
        }

    def to_summary_dict(self) -> dict[str, Any]:
        """Return the bounded subset used by bulk agent-facing views."""
        return {
            "analysis_status": self.analysis_status,
            "analysis_ready": self.analysis_ready,
            "reason_codes": list(self.reason_codes),
            "partial_outputs": self.partial_outputs,
            "recommended_action": self.recommended_action,
            "recommended_command": self.recommended_command,
            "requires_human": self.requires_human,
            "evaluation_mode": self.evaluation_mode,
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
            reason_codes=("adapter_missing",),
            recommended_action="deep_validate",
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
            reason_codes=(f"adapter_unknown:{adapter_name}",),
            recommended_action="deep_validate",
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

    adapter_warning_count = len(warnings)

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

    reason_codes = _reason_codes(
        checks=checks,
        simulator_status=simulator_status,
        adapter_warning_count=adapter_warning_count,
    )
    analysis_ready = not warnings
    analysis_status = "ready" if analysis_ready else "incomplete"
    recommended_action, requires_human = _recommendation(
        analysis_status=analysis_status,
        simulator_status=simulator_status,
        missing=bool(missing),
    )
    return RunReadiness(
        run_id=run_id,
        execution_status=execution_status,
        adapter=adapter_name,
        simulator_status=simulator_status,
        analysis_status=analysis_status,
        analysis_ready=analysis_ready,
        checks=tuple(checks),
        warnings=tuple(warnings),
        reason_codes=reason_codes,
        recommended_action=recommended_action,
        requires_human=requires_human,
    )


def probe_run_readiness(
    run_dir: Path,
    *,
    manifest: ManifestData | None = None,
) -> RunReadiness:
    """Run the adapter's bounded terminal-readiness probe.

    Unlike :func:`evaluate_run_readiness`, this path is safe to attach to a
    scheduler terminal transition: adapters are required to avoid unbounded
    log reads and full output enumeration.
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
            reason_codes=("execution_not_completed",),
            recommended_action="wait",
            evaluation_mode="bounded",
        )
    if not adapter_name:
        return RunReadiness(
            run_id=run_id,
            execution_status=execution_status,
            adapter="",
            simulator_status="unknown",
            analysis_status="unknown",
            analysis_ready=False,
            checks=(),
            warnings=("No simulator adapter is recorded in manifest.toml.",),
            reason_codes=("adapter_missing",),
            recommended_action="deep_validate",
            evaluation_mode="bounded",
        )

    try:
        from runops.adapters import get as get_adapter

        adapter_cls = get_adapter(adapter_name)
    except KeyError:
        return RunReadiness(
            run_id=run_id,
            execution_status=execution_status,
            adapter=adapter_name,
            simulator_status="unknown",
            analysis_status="unknown",
            analysis_ready=False,
            checks=(),
            warnings=(f"Unknown simulator adapter: {adapter_name}.",),
            reason_codes=(f"adapter_unknown:{adapter_name}",),
            recommended_action="deep_validate",
            evaluation_mode="bounded",
        )

    adapter = adapter_cls()
    try:
        observation = adapter.probe_readiness(run_dir)
    except Exception as exc:  # pragma: no cover - defensive adapter boundary
        observation = {
            "simulator_status": "unknown",
            "outputs": {},
            "warnings": [f"Adapter bounded readiness probe failed: {exc}"],
        }
    simulator_status = str(observation.get("simulator_status", "unknown"))
    outputs_value = observation.get("outputs", {})
    outputs = outputs_value if isinstance(outputs_value, Mapping) else {}
    warnings_value = observation.get("warnings", [])
    warnings = [str(item) for item in _as_iterable(warnings_value)]
    adapter_warning_count = len(warnings)

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
    warnings.extend(
        f"Missing required artifact: {check.key} ({check.description})"
        for check in missing
    )
    if simulator_status != RunState.COMPLETED.value:
        warnings.append(
            "Adapter status is "
            f"{simulator_status!r}, expected {RunState.COMPLETED.value!r}."
        )

    reason_codes = _reason_codes(
        checks=checks,
        simulator_status=simulator_status,
        adapter_warning_count=adapter_warning_count,
    )
    analysis_ready = not warnings
    analysis_status = "ready" if analysis_ready else "incomplete"
    if simulator_status == "unknown" and not checks and warnings:
        analysis_status = "unknown"
    recommended_action, requires_human = _recommendation(
        analysis_status=analysis_status,
        simulator_status=simulator_status,
        missing=bool(missing),
    )
    return RunReadiness(
        run_id=run_id,
        execution_status=execution_status,
        adapter=adapter_name,
        simulator_status=simulator_status,
        analysis_status=analysis_status,
        analysis_ready=analysis_ready,
        checks=tuple(checks),
        warnings=tuple(warnings),
        reason_codes=reason_codes,
        recommended_action=recommended_action,
        requires_human=requires_human,
        evaluation_mode="bounded",
    )


def resolve_run_readiness(
    run_dir: Path,
    *,
    manifest: ManifestData | None = None,
) -> RunReadiness:
    """Reuse a valid terminal cache, falling back to one cached deep evaluation."""
    manifest_data = manifest or read_manifest(run_dir)
    cached = read_cached_run_readiness(run_dir, manifest=manifest_data)
    if cached is not None and (
        cached.analysis_status != "unknown" or cached.evaluation_mode == "deep"
    ):
        return cached
    readiness = evaluate_run_readiness(run_dir, manifest=manifest_data)
    if readiness.execution_status == RunState.COMPLETED.value:
        with suppress(OSError, TypeError, ValueError):
            write_readiness_cache(run_dir, readiness, manifest=manifest_data)
    return readiness


def readiness_for_bulk_view(
    run_dir: Path,
    *,
    manifest: ManifestData | None = None,
) -> RunReadiness | None:
    """Return cache-only readiness for a bulk view without deep evaluation.

    Non-completed runs have no analysis-readiness dimension and return
    ``None``. A completed run without a current-attempt cache returns an
    explicit ``unknown`` result with the exact deep-validation command.
    """
    manifest_data = manifest or read_manifest(run_dir)
    execution_status = str(manifest_data.run.get("status", "unknown"))
    if execution_status != RunState.COMPLETED.value:
        return None
    cached = read_cached_run_readiness(run_dir, manifest=manifest_data)
    if cached is not None:
        return cached
    run_id = str(manifest_data.run.get("id", run_dir.name))
    return RunReadiness(
        run_id=run_id,
        execution_status=execution_status,
        adapter=_adapter_name(manifest_data),
        simulator_status="unknown",
        analysis_status="unknown",
        analysis_ready=False,
        checks=(),
        warnings=("No current-attempt readiness cache is available.",),
        reason_codes=("readiness_not_cached",),
        recommended_action="deep_validate",
        evaluation_mode="not_evaluated",
    )


def write_readiness_cache(
    run_dir: Path,
    readiness: RunReadiness,
    *,
    manifest: ManifestData | None = None,
) -> Path:
    """Atomically persist a derived, attempt-aware readiness observation."""
    manifest_data = manifest or read_manifest(run_dir)
    status_dir = run_dir / "status"
    status_dir.mkdir(parents=True, exist_ok=True)
    target = status_dir / "readiness.json"
    payload = {
        "schema_version": 1,
        "evaluated_at": datetime.now(tz=timezone.utc).isoformat(),
        "attempt": _attempt_identity(manifest_data),
        "readiness": readiness.to_dict(),
    }
    fd, tmp_name = tempfile.mkstemp(prefix=".readiness-", suffix=".tmp", dir=status_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_name, target)
    finally:
        with suppress(FileNotFoundError):
            os.unlink(tmp_name)
    return target


def read_cached_run_readiness(
    run_dir: Path,
    *,
    manifest: ManifestData | None = None,
) -> RunReadiness | None:
    """Return a valid readiness cache for the current attempt, if present."""
    manifest_data = manifest or read_manifest(run_dir)
    cache_path = run_dir / "status" / "readiness.json"
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if payload.get("schema_version") != 1:
        return None
    if payload.get("attempt") != _attempt_identity(manifest_data):
        return None
    readiness_value = payload.get("readiness")
    if not isinstance(readiness_value, Mapping):
        return None
    try:
        return _readiness_from_dict(readiness_value)
    except (KeyError, TypeError, ValueError):
        return None


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


def _as_iterable(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes, bytearray)):
        return (value,)
    if isinstance(value, Iterable):
        return tuple(value)
    return (value,)


def _reason_codes(
    *,
    checks: Iterable[ArtifactCheck],
    simulator_status: str,
    adapter_warning_count: int,
) -> tuple[str, ...]:
    codes = [
        f"missing_required_output:{check.key}" for check in checks if not check.present
    ]
    if simulator_status != RunState.COMPLETED.value:
        codes.append(f"simulator_status:{simulator_status or 'unknown'}")
    if adapter_warning_count > 0:
        codes.append("adapter_diagnostic_warning")
    return tuple(codes)


def _recommendation(
    *,
    analysis_status: str,
    simulator_status: str,
    missing: bool,
) -> tuple[str, bool]:
    if analysis_status == "ready":
        return "analyze", False
    if analysis_status == "unknown":
        return "deep_validate", False
    if simulator_status == RunState.FAILED.value:
        return "retry", False
    if missing or simulator_status != RunState.COMPLETED.value:
        return "review_outputs", False
    return "deep_validate", False


def _attempt_identity(manifest: ManifestData) -> dict[str, Any]:
    return {
        "job_id": str(manifest.job.get("job_id", "")),
        "submitted_at": str(manifest.job.get("submitted_at", "")),
        "attempt": int(manifest.job.get("attempt", 0) or 0),
    }


def _readiness_from_dict(value: Mapping[str, Any]) -> RunReadiness:
    checks_value = value.get("checks", [])
    if not isinstance(checks_value, list):
        raise TypeError("checks must be a list")
    checks = tuple(
        ArtifactCheck(
            key=str(item["key"]),
            description=str(item["description"]),
            present=bool(item["present"]),
            count=int(item["count"]),
            paths=tuple(str(path) for path in item.get("paths", [])),
        )
        for item in checks_value
        if isinstance(item, Mapping)
    )
    return RunReadiness(
        run_id=str(value["run_id"]),
        execution_status=str(value["execution_status"]),
        adapter=str(value["adapter"]),
        simulator_status=str(value["simulator_status"]),
        analysis_status=str(value["analysis_status"]),
        analysis_ready=bool(value["analysis_ready"]),
        checks=checks,
        warnings=tuple(str(item) for item in value.get("warnings", [])),
        reason_codes=tuple(str(item) for item in value.get("reason_codes", [])),
        recommended_action=str(value.get("recommended_action", "")),
        requires_human=bool(value.get("requires_human", False)),
        evaluation_mode=str(value.get("evaluation_mode", "deep")),
    )
