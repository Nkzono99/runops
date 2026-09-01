"""Domain contract for durable research Result manifests.

Selection is deliberately represented by an evidence edge owned by a Result.
There is no project-global ``selected`` flag on a run manifest because the same
run may be useful for one claim and excluded from another.
"""

from __future__ import annotations

import copy
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

_RESULT_ID = re.compile(r"^R\d{4}-[a-z0-9][a-z0-9-]*$")
_RUN_ID = re.compile(r"^R\d{8}-\d{4}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_STATUSES = frozenset({"draft", "sealed"})
_OUTCOMES = frozenset({"supported", "refuted", "inconclusive", "invalid"})
_KINDS = frozenset({"run", "path"})
_DISPOSITIONS = frozenset({"include", "exclude"})
_RECEIPT_KINDS = frozenset({"run-scientific-snapshot-v1", "file-bytes-v1"})


class ResultManifestError(ValueError):
    """Raised when a Result manifest cannot be parsed safely."""


class ResultManifestLayout(str, Enum):
    """Supported on-disk layouts during the v0 transition."""

    CANONICAL = "canonical"
    LEGACY_FLAT = "legacy-flat"
    LEGACY_COMPARISON = "legacy-comparison"


@dataclass(frozen=True)
class ResultEvidence:
    """One Result-local evidence inclusion or exclusion decision."""

    kind: str
    disposition: str
    role: str
    reason: str
    run_id: str | None = None
    path: str | None = None
    source_path: str | None = None
    owner_kind: str | None = None
    owner_id: str | None = None
    owner_relative_path: str | None = None
    receipt_kind: str | None = None
    sha256: str | None = None
    byte_count: int | None = None


@dataclass(frozen=True)
class ResultManifest:
    """Normalized read view that leaves the original TOML mapping available."""

    layout: ResultManifestLayout
    result_id: str
    status: str
    title: str
    claim: str
    outcome: str | None
    evidence: tuple[ResultEvidence, ...]
    seal: dict[str, Any]
    raw: dict[str, Any]

    @property
    def sealed(self) -> bool:
        """Return whether this is a canonical sealed Result."""
        return self.layout is ResultManifestLayout.CANONICAL and self.status == "sealed"


def parse_result_manifest(
    payload: Mapping[str, Any],
    *,
    default_id: str = "",
) -> ResultManifest:
    """Parse canonical and explicitly supported legacy Result layouts."""
    raw = copy.deepcopy(dict(payload))
    result = raw.get("result")
    if isinstance(result, dict):
        return _parse_canonical(raw, result)

    comparison = raw.get("comparison")
    if isinstance(comparison, dict):
        return ResultManifest(
            layout=ResultManifestLayout.LEGACY_COMPARISON,
            result_id=default_id or _string(comparison, "id", allow_empty=False),
            status=_optional_string(comparison, "status") or "draft",
            title=_optional_string(comparison, "name")
            or _optional_string(comparison, "title")
            or default_id,
            claim="",
            outcome=None,
            evidence=(),
            seal={},
            raw=raw,
        )

    if any(key in raw for key in ("id", "title", "status")):
        return ResultManifest(
            layout=ResultManifestLayout.LEGACY_FLAT,
            result_id=_optional_string(raw, "id") or default_id,
            status=_optional_string(raw, "status") or "active",
            title=_optional_string(raw, "title") or default_id,
            claim=_optional_string(raw, "claim") or "",
            outcome=_parse_outcome(_optional_string(raw, "outcome")),
            evidence=(),
            seal={},
            raw=raw,
        )

    raise ResultManifestError(
        "result manifest must contain [result], legacy flat fields, or [comparison]"
    )


def read_result_manifest(result_dir: Path) -> ResultManifest:
    """Read a Result manifest without rewriting or migrating legacy layouts."""
    manifest_path = result_dir / "manifest.toml"
    try:
        with manifest_path.open("rb") as stream:
            payload = tomllib.load(stream)
    except FileNotFoundError as exc:
        raise ResultManifestError(
            f"result manifest not found: {manifest_path}"
        ) from exc
    except tomllib.TOMLDecodeError as exc:
        raise ResultManifestError(
            f"invalid result TOML in {manifest_path}: {exc}"
        ) from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise ResultManifestError(
            f"cannot read result manifest {manifest_path}: {exc}"
        ) from exc
    return parse_result_manifest(payload, default_id=result_dir.name)


def valid_result_outcomes() -> tuple[str, ...]:
    """Return canonical outcome values for interface validation/help."""
    return tuple(sorted(_OUTCOMES))


def _parse_canonical(
    raw: dict[str, Any],
    result: dict[str, Any],
) -> ResultManifest:
    schema_version = result.get("schema_version")
    if type(schema_version) is not int or schema_version != 1:
        raise ResultManifestError("result.schema_version must be integer 1")
    result_id = _string(result, "id", allow_empty=False)
    if not _RESULT_ID.fullmatch(result_id):
        raise ResultManifestError(
            "result.id must match RNNNN-topic using lowercase ASCII slug characters"
        )
    status = _string(result, "status", allow_empty=False)
    if status not in _STATUSES:
        raise ResultManifestError("result.status must be draft or sealed")
    title = _string(result, "title", allow_empty=False)
    claim = _optional_string(result, "claim") or ""
    outcome = _parse_outcome(_optional_string(result, "outcome"))

    raw_evidence = raw.get("evidence", [])
    if not isinstance(raw_evidence, list):
        raise ResultManifestError("evidence must be an array of TOML tables")
    evidence = tuple(
        _parse_evidence(item, index=index) for index, item in enumerate(raw_evidence)
    )
    raw_seal = raw.get("seal", {})
    if not isinstance(raw_seal, dict):
        raise ResultManifestError("seal must be a TOML table")

    return ResultManifest(
        layout=ResultManifestLayout.CANONICAL,
        result_id=result_id,
        status=status,
        title=title,
        claim=claim,
        outcome=outcome,
        evidence=evidence,
        seal=copy.deepcopy(raw_seal),
        raw=raw,
    )


def _parse_evidence(value: object, *, index: int) -> ResultEvidence:
    if not isinstance(value, dict):
        raise ResultManifestError(f"evidence[{index}] must be a TOML table")
    kind = _string(value, "kind", allow_empty=False)
    if kind not in _KINDS:
        raise ResultManifestError(f"evidence[{index}].kind must be run or path")
    disposition = _string(value, "disposition", allow_empty=False)
    if disposition not in _DISPOSITIONS:
        raise ResultManifestError(
            f"evidence[{index}].disposition must be include or exclude"
        )
    role = _string(value, "role", allow_empty=False)
    reason = _string(value, "reason", allow_empty=True)
    run_id = _optional_string(value, "run_id")
    path = _optional_string(value, "path")
    source_path = _optional_string(value, "source_path")
    owner_kind = _optional_string(value, "owner_kind")
    owner_id = _optional_string(value, "owner_id")
    owner_relative_path = _optional_string(value, "owner_relative_path")
    owner_values = (owner_kind, owner_id, owner_relative_path)
    if any(item is not None for item in owner_values) and not all(
        item is not None for item in owner_values
    ):
        raise ResultManifestError(
            f"evidence[{index}] owner_kind/owner_id/owner_relative_path "
            "must be recorded together"
        )
    if owner_kind is not None and owner_kind not in {"run", "result"}:
        raise ResultManifestError(f"evidence[{index}].owner_kind is invalid")
    if owner_kind == "run" and owner_id is not None and not _RUN_ID.fullmatch(owner_id):
        raise ResultManifestError(f"evidence[{index}].owner_id is not a run ID")
    if owner_relative_path is not None:
        owner_relative = Path(owner_relative_path)
        if owner_relative.is_absolute() or ".." in owner_relative.parts:
            raise ResultManifestError(
                f"evidence[{index}].owner_relative_path is unsafe"
            )
    receipt_kind = _optional_string(value, "receipt_kind")
    if receipt_kind is not None and receipt_kind not in _RECEIPT_KINDS:
        raise ResultManifestError(f"evidence[{index}].receipt_kind is invalid")
    if kind == "run" and not run_id:
        raise ResultManifestError(f"evidence[{index}].run_id is required")
    if kind == "run" and run_id is not None and not _RUN_ID.fullmatch(run_id):
        raise ResultManifestError(f"evidence[{index}].run_id must match RYYYYMMDD-NNNN")
    if kind == "path" and not path:
        raise ResultManifestError(f"evidence[{index}].path is required")

    sha256 = _optional_string(value, "sha256")
    if sha256 is not None and not _SHA256.fullmatch(sha256):
        raise ResultManifestError(f"evidence[{index}].sha256 is invalid")
    byte_count = value.get("bytes")
    if byte_count is not None and (
        isinstance(byte_count, bool)
        or not isinstance(byte_count, int)
        or byte_count < 0
    ):
        raise ResultManifestError(f"evidence[{index}].bytes must be non-negative")
    return ResultEvidence(
        kind=kind,
        disposition=disposition,
        role=role,
        reason=reason,
        run_id=run_id,
        path=path,
        source_path=source_path,
        owner_kind=owner_kind,
        owner_id=owner_id,
        owner_relative_path=owner_relative_path,
        receipt_kind=receipt_kind,
        sha256=sha256,
        byte_count=byte_count,
    )


def _parse_outcome(value: str | None) -> str | None:
    if value in (None, ""):
        return None
    if value not in _OUTCOMES:
        raise ResultManifestError(
            "result.outcome must be supported, refuted, inconclusive, or invalid"
        )
    return value


def _string(
    mapping: Mapping[str, Any],
    key: str,
    *,
    allow_empty: bool,
) -> str:
    value = mapping.get(key)
    if not isinstance(value, str):
        raise ResultManifestError(f"{key} must be a string")
    if not allow_empty and not value.strip():
        raise ResultManifestError(f"{key} must not be empty")
    return value.strip()


def _optional_string(mapping: Mapping[str, Any], key: str) -> str | None:
    value = mapping.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ResultManifestError(f"{key} must be a string")
    return value.strip()
