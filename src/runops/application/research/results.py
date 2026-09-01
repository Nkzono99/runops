"""Evidence validation and atomic sealing for durable research Results."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import tomli_w

from runops.application.research.workspace import (
    ResearchWorkspaceError,
    _result_allocation_lock,
    inspect_result_workspace,
)
from runops.application.run_creation.workflow import directory_content_hash
from runops.application.run_discovery import collect_run_manifests_strict
from runops.core.exceptions import ManifestError, ManifestNotFoundError, SimctlError
from runops.core.manifest import read_manifest
from runops.core.research.result import (
    ResultEvidence,
    ResultManifest,
    ResultManifestError,
    ResultManifestLayout,
    read_result_manifest,
    valid_result_outcomes,
)
from runops.core.research.workspace import ResearchBudget
from runops.core.run.curation import has_valid_run_review

_RESULT_ROOT = Path("research") / "results"
_RESULT_ARCHIVE_ROOT = Path("research") / "archive" / "results"
_RUN_ID = re.compile(r"^R\d{8}-\d{4}$")
_SHA256_IDENTITY = re.compile(r"^sha256:[0-9a-f]{64}$")
FileReceipt = dict[str, str | int]


@dataclass(frozen=True)
class EvidenceRequest:
    """Unsealed evidence reference supplied by a caller."""

    kind: str
    run_id: str | None = None
    path_value: str | None = None
    disposition: str = "include"
    role: str = "evidence"
    reason: str = ""

    @classmethod
    def run(
        cls,
        run_id: str,
        *,
        disposition: str = "include",
        role: str = "evidence",
        reason: str = "",
    ) -> EvidenceRequest:
        """Construct a run evidence request."""
        return cls(
            kind="run",
            run_id=run_id,
            disposition=disposition,
            role=role,
            reason=reason,
        )

    @classmethod
    def path(
        cls,
        path: str | Path,
        *,
        disposition: str = "include",
        role: str = "evidence",
        reason: str = "",
    ) -> EvidenceRequest:
        """Construct a project-relative file evidence request."""
        return cls(
            kind="path",
            path_value=str(path),
            disposition=disposition,
            role=role,
            reason=reason,
        )


@dataclass(frozen=True)
class ResultCheckIssue:
    """One deterministic Result integrity or seal-readiness issue."""

    severity: str
    code: str
    message: str
    path: str = ""

    def to_dict(self) -> dict[str, str]:
        """Return a stable JSON representation."""
        payload = {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
        }
        if self.path:
            payload["path"] = self.path
        return payload


@dataclass(frozen=True)
class ResultCheck:
    """Read-only validation result for one research Result."""

    result_id: str
    path: Path
    layout: str
    status: str
    sealed: bool
    ready_to_seal: bool
    issues: tuple[ResultCheckIssue, ...]

    @property
    def ok(self) -> bool:
        """Return whether no error-level issue was found."""
        return not any(issue.severity == "error" for issue in self.issues)

    def to_dict(self) -> dict[str, object]:
        """Return the stable CLI/MCP-friendly check shape."""
        return {
            "result_id": self.result_id,
            "path": str(self.path),
            "layout": self.layout,
            "status": self.status,
            "sealed": self.sealed,
            "ready_to_seal": self.ready_to_seal,
            "ok": self.ok,
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class ResultSeal:
    """Outcome of an atomic seal attempt."""

    result_id: str
    path: Path
    sealed_at: str
    content_sha256: str
    changed: bool


@contextmanager
def result_mutation_guard(project_root: Path) -> Iterator[None]:
    """Serialize Result sealing/movement with destructive Run evidence changes."""
    with _result_allocation_lock(project_root.resolve()):
        yield


def protected_results_for_run_paths(
    project_root: Path,
    run_id: str,
    *,
    relative_roots: tuple[str, ...],
) -> tuple[str, ...]:
    """Return sealed Results that include path evidence below Run roots.

    This reverse-reference scan is intentionally performed at purge time so
    archived/restored Results and newly sealed Results cannot leave a stale
    protection flag in the Run manifest.
    """
    root = project_root.resolve()
    protected: set[str] = set()
    prefixes = tuple(Path(value) for value in relative_roots)
    for relative_result_root in (_RESULT_ROOT, _RESULT_ARCHIVE_ROOT):
        result_root = root / relative_result_root
        if not os.path.lexists(result_root):
            continue
        _assert_safe_directory(
            result_root,
            root=root,
            label="Result evidence registry root",
        )
        try:
            result_directories = sorted(result_root.iterdir())
        except OSError as exc:
            raise ResearchWorkspaceError(
                f"cannot enumerate Result evidence registry {result_root}: {exc}"
            ) from exc
        for result_dir in result_directories:
            if result_dir.name.startswith(".tmp-result-"):
                _assert_safe_directory(
                    result_dir,
                    root=root,
                    label="Result staging directory",
                )
                continue
            _assert_safe_directory(
                result_dir,
                root=root,
                label="Result evidence registry directory",
            )
            manifest_path = result_dir / "manifest.toml"
            _assert_safe_regular_file(
                manifest_path,
                root=root,
                label="Result evidence registry manifest",
            )
            manifest_receipt = _file_receipt(
                manifest_path,
                root=root,
                label="Result evidence registry manifest",
            )
            try:
                manifest = read_result_manifest(result_dir)
            except ResultManifestError as exc:
                raise ResearchWorkspaceError(
                    f"cannot verify Result references in {result_dir}: {exc}"
                ) from exc
            if not manifest.sealed:
                if manifest.seal:
                    raise ResearchWorkspaceError(
                        f"cannot trust unsealed Result {manifest.result_id}: "
                        "seal metadata is still present"
                    )
                if (
                    _file_receipt(
                        manifest_path,
                        root=root,
                        label="Result evidence registry manifest",
                    )
                    != manifest_receipt
                ):
                    raise ResearchWorkspaceError(
                        f"Result manifest changed during reverse-reference scan: "
                        f"{result_dir}"
                    )
                continue
            try:
                checked = check_result(root, result_dir)
            except ResearchWorkspaceError as exc:
                raise ResearchWorkspaceError(
                    f"cannot validate sealed Result {manifest.result_id}: {exc}"
                ) from exc
            if (
                _file_receipt(
                    manifest_path,
                    root=root,
                    label="Result evidence registry manifest",
                )
                != manifest_receipt
            ):
                raise ResearchWorkspaceError(
                    f"Result manifest changed during reverse-reference scan: "
                    f"{result_dir}"
                )
            if not checked.ok:
                details = "; ".join(
                    f"{issue.code}: {issue.message}"
                    for issue in checked.issues
                    if issue.severity == "error"
                )
                raise ResearchWorkspaceError(
                    f"sealed Result {manifest.result_id} failed integrity checks: "
                    f"{details}"
                )
            for item in manifest.evidence:
                if item.kind != "path" or item.disposition != "include":
                    continue
                owner_kind, owner_id, owner_relative_path = _path_evidence_record_owner(
                    root,
                    item,
                    result_dir=result_dir,
                )
                if (
                    owner_kind == "run"
                    and owner_id == run_id
                    and any(
                        _is_relative_to(Path(owner_relative_path), prefix)
                        for prefix in prefixes
                    )
                ):
                    protected.add(manifest.result_id)
                    break
    return tuple(sorted(protected))


def _path_evidence_record_owner(
    root: Path,
    item: ResultEvidence,
    *,
    result_dir: Path,
) -> tuple[str, str, str]:
    """Return explicit or safely inferred ownership for path evidence."""
    if (
        item.owner_kind is not None
        and item.owner_id is not None
        and item.owner_relative_path is not None
    ):
        return item.owner_kind, item.owner_id, item.owner_relative_path
    if item.path is None:
        raise ResearchWorkspaceError(
            f"Result {result_dir.name} has path evidence without a path"
        )
    source = _resolve_project_file(root, item.path)
    _assert_safe_regular_file(
        source,
        root=root,
        label=f"Result {result_dir.name} path evidence",
    )
    return _path_evidence_owner(root, source, result_dir=result_dir)


def check_result(
    project_root: Path,
    result: str | Path,
    *,
    budget: ResearchBudget | None = None,
) -> ResultCheck:
    """Validate one Result without modifying or migrating it."""
    root = project_root.resolve()
    result_dir = _resolve_result(root, result)
    manifest_path = result_dir / "manifest.toml"
    _assert_safe_regular_file(manifest_path, root=root, label="result manifest")
    try:
        manifest = read_result_manifest(result_dir)
    except ResultManifestError as exc:
        raise ResearchWorkspaceError(str(exc)) from exc

    issues = _result_workspace_issues(root, result_dir, budget=budget)
    readme = result_dir / "README.md"
    readme_receipt: FileReceipt | None
    try:
        readme_receipt = _file_receipt(readme, root=root, label="result README")
    except ResearchWorkspaceError as exc:
        readme_path = _relative(readme, root)
        if not any(
            issue.severity == "error" and issue.path == readme_path for issue in issues
        ):
            issues.append(_issue("result.readme_invalid", str(exc), path=readme_path))
        readme_receipt = None

    if manifest.layout is not ResultManifestLayout.CANONICAL:
        issues.append(
            ResultCheckIssue(
                severity="warning",
                code="result.legacy_manifest",
                path=_relative(manifest_path, root),
                message=(
                    f"{manifest.layout.value} is accepted read-only; create a new "
                    "canonical Result before sealing"
                ),
            )
        )
        return ResultCheck(
            result_id=manifest.result_id,
            path=result_dir,
            layout=manifest.layout.value,
            status=manifest.status,
            sealed=False,
            ready_to_seal=False,
            issues=tuple(issues),
        )

    issues.extend(_canonical_gate_issues(root, result_dir, manifest))
    if manifest.sealed:
        issues.extend(
            _sealed_receipt_issues(
                root,
                result_dir,
                manifest,
                readme_receipt=readme_receipt,
            )
        )
    return ResultCheck(
        result_id=manifest.result_id,
        path=result_dir,
        layout=manifest.layout.value,
        status=manifest.status,
        sealed=manifest.sealed,
        ready_to_seal=not manifest.sealed
        and not any(issue.severity == "error" for issue in issues),
        issues=tuple(issues),
    )


def seal_result(
    project_root: Path,
    result: str | Path,
    *,
    claim: str,
    outcome: str,
    evidence: tuple[EvidenceRequest, ...],
    budget: ResearchBudget | None = None,
    now: datetime | None = None,
) -> ResultSeal:
    """Seal a canonical draft atomically after validating all source receipts."""
    root = project_root.resolve()
    clean_claim = claim.strip()
    clean_outcome = outcome.strip()
    if not clean_claim:
        raise ResearchWorkspaceError("Result claim must not be empty")
    if clean_outcome not in valid_result_outcomes():
        allowed = ", ".join(valid_result_outcomes())
        raise ResearchWorkspaceError(f"Result outcome must be one of: {allowed}")
    if not evidence:
        raise ResearchWorkspaceError("Result requires at least one evidence item")

    with _result_allocation_lock(root):
        result_dir = _resolve_result(root, result)
        try:
            result_dir.relative_to(root / _RESULT_ROOT)
        except ValueError as exc:
            raise ResearchWorkspaceError(
                "restore an archived Result before sealing it"
            ) from exc
        manifest_path = result_dir / "manifest.toml"
        manifest_receipt = _file_receipt(
            manifest_path,
            root=root,
            label="result manifest",
        )
        try:
            manifest = read_result_manifest(result_dir)
        except ResultManifestError as exc:
            raise ResearchWorkspaceError(str(exc)) from exc
        if manifest.layout is not ResultManifestLayout.CANONICAL:
            raise ResearchWorkspaceError(
                "legacy Result manifests are read-only; create a canonical Result"
            )
        if not manifest.sealed and manifest.seal:
            raise ResearchWorkspaceError(
                "Result changed after sealing: draft status conflicts with "
                "seal metadata"
            )
        _require_result_workspace_ready(root, result_dir, budget=budget)

        requested_signature = _request_signature(evidence)
        if manifest.sealed:
            existing_signature = _evidence_signature(manifest.evidence)
            if (
                manifest.claim != clean_claim
                or manifest.outcome != clean_outcome
                or existing_signature != requested_signature
            ):
                raise ResearchWorkspaceError(
                    "sealed Result cannot be resealed with different content"
                )
            checked = check_result(root, result_dir, budget=budget)
            if not checked.ok:
                messages = "; ".join(
                    issue.message
                    for issue in checked.issues
                    if issue.severity == "error"
                )
                raise ResearchWorkspaceError(
                    f"Result evidence changed after sealing: {messages}"
                )
            return ResultSeal(
                result_id=manifest.result_id,
                path=result_dir,
                sealed_at=str(manifest.seal.get("sealed_at", "")),
                content_sha256=str(manifest.seal.get("content_sha256", "")),
                changed=False,
            )

        records = tuple(
            _resolve_evidence(root, item, result_dir=result_dir) for item in evidence
        )
        _validate_evidence_records(records)
        _validate_result_source_readiness(root, records)
        manifest_relative = _relative(manifest_path, root)
        if any(
            item.kind == "path" and item.path == manifest_relative for item in records
        ):
            raise ResearchWorkspaceError(
                "a Result manifest cannot be evidence for its own seal"
            )
        readme_receipt = _file_receipt(
            result_dir / "README.md",
            root=root,
            label="result README",
        )
        sealed_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        evidence_payload = [_evidence_payload(item) for item in records]

        payload = copy.deepcopy(manifest.raw)
        result_table = payload.get("result")
        if not isinstance(result_table, dict):
            raise ResearchWorkspaceError("canonical Result is missing [result]")
        result_table.update(
            {
                "status": "sealed",
                "claim": clean_claim,
                "outcome": clean_outcome,
            }
        )
        payload["evidence"] = evidence_payload
        payload["seal"] = {
            "sealed_at": sealed_at.isoformat(timespec="seconds"),
            "readme_sha256": readme_receipt["sha256"],
            "readme_bytes": readme_receipt["bytes"],
        }
        content_sha256 = _sealed_manifest_digest(payload)
        payload["seal"]["content_sha256"] = content_sha256
        if (
            _file_receipt(
                manifest_path,
                root=root,
                label="result manifest",
            )
            != manifest_receipt
        ):
            raise ResearchWorkspaceError("Result manifest changed during sealing")
        if (
            _file_receipt(
                result_dir / "README.md",
                root=root,
                label="result README",
            )
            != readme_receipt
        ):
            raise ResearchWorkspaceError("Result README changed during sealing")
        refreshed_records = tuple(
            _resolve_evidence(root, item, result_dir=result_dir) for item in evidence
        )
        if refreshed_records != records:
            raise ResearchWorkspaceError("Result evidence changed during sealing")
        _require_result_workspace_ready(root, result_dir, budget=budget)
        _validate_result_source_readiness(root, refreshed_records)
        _write_toml_atomic(manifest_path, payload)
        return ResultSeal(
            result_id=manifest.result_id,
            path=result_dir,
            sealed_at=sealed_at.isoformat(timespec="seconds"),
            content_sha256=content_sha256,
            changed=True,
        )


def _result_workspace_issues(
    root: Path,
    result_dir: Path,
    *,
    budget: ResearchBudget | None,
) -> list[ResultCheckIssue]:
    """Translate the shared Result-local workspace gate into check issues."""
    inspected = inspect_result_workspace(root, result_dir, budget=budget)
    return [
        ResultCheckIssue(
            severity=issue.severity,
            code=issue.code,
            path=issue.path,
            message=issue.message,
        )
        for issue in inspected.issues
    ]


def _require_result_workspace_ready(
    root: Path,
    result_dir: Path,
    *,
    budget: ResearchBudget | None,
) -> None:
    """Reject sealing while any shared Result-local hard gate is violated."""
    blocking = [
        issue
        for issue in _result_workspace_issues(root, result_dir, budget=budget)
        if issue.severity == "error"
    ]
    if not blocking:
        return
    details = "; ".join(f"{issue.code}: {issue.message}" for issue in blocking)
    raise ResearchWorkspaceError(f"Result workspace has blocking issues: {details}")


def _canonical_gate_issues(
    root: Path,
    result_dir: Path,
    manifest: ResultManifest,
) -> list[ResultCheckIssue]:
    issues: list[ResultCheckIssue] = []
    if not manifest.sealed and manifest.seal:
        issues.append(
            _issue(
                "result.draft_has_seal",
                "draft Result contains seal metadata from a prior seal",
            )
        )
    if not manifest.claim:
        issues.append(_issue("result.claim_missing", "Result claim is required"))
    if manifest.outcome is None:
        issues.append(_issue("result.outcome_missing", "Result outcome is required"))
    if not manifest.evidence:
        issues.append(
            _issue("result.evidence_missing", "at least one evidence item is required")
        )
    if manifest.evidence and not any(
        item.disposition == "include" for item in manifest.evidence
    ):
        issues.append(
            _issue(
                "result.included_evidence_missing",
                "at least one included evidence item is required",
            )
        )

    seen: set[tuple[str, str, str, str, str]] = set()
    resolved_records: list[ResultEvidence] = []
    for index, item in enumerate(manifest.evidence):
        label = f"evidence[{index}]"
        if item.disposition == "exclude" and not item.reason:
            issues.append(
                _issue(
                    "result.exclusion_reason_missing",
                    f"{label} requires a reason when excluded",
                )
            )
        if item.disposition == "include" and not item.reason:
            issues.append(
                _issue(
                    "result.selection_reason_missing",
                    f"{label} requires a reason when included",
                )
            )
        signature = _single_evidence_signature(item)
        if signature in seen:
            issues.append(
                _issue(
                    "result.evidence_duplicate",
                    f"{label} duplicates an earlier item",
                )
            )
        seen.add(signature)
        try:
            resolved_records.append(
                _resolve_existing_evidence(root, item, result_dir=result_dir)
            )
        except ResearchWorkspaceError as exc:
            issues.append(_issue("result.evidence_invalid", f"{label}: {exc}"))
    if not manifest.sealed:
        issues.extend(
            _issue("result.source_not_ready", message)
            for message in _result_source_readiness_issues(
                root,
                tuple(resolved_records),
            )
        )
    else:
        issues.extend(
            _issue("result.source_integrity_failed", message)
            for message in _result_source_input_integrity_issues(
                root,
                tuple(resolved_records),
            )
        )
    return issues


def _result_source_input_integrity_issues(
    root: Path,
    records: tuple[ResultEvidence, ...],
) -> list[str]:
    """Rehash sealed Result source inputs without reapplying lifecycle gates."""
    run_ids = {
        run_id
        for item in records
        if item.disposition == "include"
        for run_id in (
            item.run_id
            if item.kind == "run"
            else item.owner_id
            if item.owner_kind == "run"
            else None,
        )
        if run_id is not None
    }
    issues: list[str] = []
    for run_id in sorted(run_ids):
        try:
            manifest_path = _find_run_manifest(root, run_id)
            manifest = read_manifest(manifest_path.parent)
        except (ManifestError, ManifestNotFoundError, ResearchWorkspaceError) as exc:
            issues.append(f"{run_id}: cannot read manifest ({exc})")
            continue
        input_name = str(manifest.files.get("input_dir", "input")).strip() or "input"
        input_dir = manifest_path.parent / input_name
        expected = str(manifest.identity.get("input_hash", ""))
        if not expected.startswith("sha256:"):
            issues.append(f"{run_id}: identity is missing input_hash")
            continue
        try:
            actual = directory_content_hash(input_dir)
        except (OSError, SimctlError) as exc:
            issues.append(f"{run_id}: cannot hash input snapshot ({exc})")
            continue
        if actual != expected:
            issues.append(
                f"{run_id}: input snapshot does not match identity.input_hash"
            )
    return issues


def _sealed_receipt_issues(
    root: Path,
    result_dir: Path,
    manifest: ResultManifest,
    *,
    readme_receipt: FileReceipt | None,
) -> list[ResultCheckIssue]:
    issues: list[ResultCheckIssue] = []
    expected_readme_hash = manifest.seal.get("readme_sha256")
    expected_readme_bytes = manifest.seal.get("readme_bytes")
    if not isinstance(expected_readme_hash, str) or not isinstance(
        expected_readme_bytes, int
    ):
        issues.append(
            _issue("result.seal_receipt_missing", "sealed Result lacks README receipt")
        )
    elif readme_receipt is not None and (
        readme_receipt["sha256"] != expected_readme_hash
        or readme_receipt["bytes"] != expected_readme_bytes
    ):
        issues.append(
            _issue(
                "result.readme_changed",
                "README changed after sealing",
                path=_relative(result_dir / "README.md", root),
            )
        )

    sealed_at = manifest.seal.get("sealed_at")
    expected_content_hash = manifest.seal.get("content_sha256")
    if not isinstance(sealed_at, str) or not isinstance(expected_content_hash, str):
        issues.append(
            _issue("result.seal_receipt_missing", "sealed Result lacks seal metadata")
        )
    for index, item in enumerate(manifest.evidence):
        try:
            current = _resolve_existing_evidence(
                root,
                item,
                result_dir=result_dir,
            )
        except ResearchWorkspaceError:
            continue
        if item.sha256 is None or item.byte_count is None:
            issues.append(
                _issue(
                    "result.evidence_receipt_missing",
                    f"evidence[{index}] lacks sha256/bytes",
                )
            )
        expected_receipt_kind = (
            "run-scientific-snapshot-v1" if item.kind == "run" else "file-bytes-v1"
        )
        if item.receipt_kind != expected_receipt_kind:
            issues.append(
                _issue(
                    "result.evidence_receipt_kind_invalid",
                    f"evidence[{index}] lacks the canonical receipt kind",
                )
            )
        if (
            item.sha256 is not None
            and item.byte_count is not None
            and (current.sha256 != item.sha256 or current.byte_count != item.byte_count)
        ):
            issues.append(
                _issue(
                    "result.evidence_changed",
                    f"evidence[{index}] changed after sealing",
                    path=current.source_path or current.path or "",
                )
            )
    if isinstance(sealed_at, str) and isinstance(expected_content_hash, str):
        actual_content_hash = _sealed_manifest_digest(manifest.raw)
        if actual_content_hash != expected_content_hash:
            issues.append(
                _issue(
                    "result.sealed_content_changed",
                    "claim, outcome, evidence selection, or seal receipt changed "
                    "after sealing",
                )
            )
    return issues


def _resolve_evidence(
    root: Path,
    request: EvidenceRequest,
    *,
    result_dir: Path | None = None,
) -> ResultEvidence:
    kind = request.kind.strip()
    disposition = request.disposition.strip()
    role = request.role.strip()
    reason = request.reason.strip()
    if kind not in {"run", "path"}:
        raise ResearchWorkspaceError("evidence kind must be run or path")
    if disposition not in {"include", "exclude"}:
        raise ResearchWorkspaceError("evidence disposition must be include or exclude")
    if not role:
        raise ResearchWorkspaceError("evidence role must not be empty")
    if disposition == "exclude" and not reason:
        raise ResearchWorkspaceError("excluded evidence requires a reason")

    if kind == "run":
        run_id = (request.run_id or "").strip()
        if not run_id:
            raise ResearchWorkspaceError("run evidence requires run_id")
        if run_id.startswith("T"):
            raise ResearchWorkspaceError(
                "test attempt IDs cannot be used as scientific Result evidence"
            )
        if not _RUN_ID.fullmatch(run_id):
            raise ResearchWorkspaceError("run evidence ID must match RYYYYMMDD-NNNN")
        source = _find_run_manifest(root, run_id)
        receipt = _run_scientific_receipt(source, root=root, run_id=run_id)
        return ResultEvidence(
            kind="run",
            run_id=run_id,
            disposition=disposition,
            role=role,
            reason=reason,
            source_path=_relative(source, root),
            receipt_kind="run-scientific-snapshot-v1",
            sha256=str(receipt["sha256"]),
            byte_count=int(receipt["bytes"]),
        )

    source_text = (request.path_value or "").strip()
    source = _resolve_project_file(root, source_text)
    receipt = _file_receipt(source, root=root, label="path evidence")
    owner_kind, owner_id, owner_relative_path = _path_evidence_owner(
        root,
        source,
        result_dir=result_dir,
    )
    return ResultEvidence(
        kind="path",
        path=_relative(source, root),
        disposition=disposition,
        role=role,
        reason=reason,
        source_path=_relative(source, root),
        owner_kind=owner_kind,
        owner_id=owner_id,
        owner_relative_path=owner_relative_path,
        receipt_kind="file-bytes-v1",
        sha256=str(receipt["sha256"]),
        byte_count=int(receipt["bytes"]),
    )


def _resolve_existing_evidence(
    root: Path,
    item: ResultEvidence,
    *,
    result_dir: Path | None = None,
) -> ResultEvidence:
    path_value = item.path
    if item.kind == "path" and item.owner_relative_path is not None:
        if item.owner_kind == "run" and item.owner_id is not None:
            owner_manifest = _find_run_manifest(root, item.owner_id)
            path_value = _relative(
                owner_manifest.parent / item.owner_relative_path,
                root,
            )
        elif item.owner_kind == "result" and item.owner_id is not None:
            owner_result = _resolve_result(root, item.owner_id)
            path_value = _relative(
                owner_result / item.owner_relative_path,
                root,
            )
    elif item.kind == "path" and path_value is not None and result_dir is not None:
        active_result = _RESULT_ROOT / result_dir.name
        try:
            suffix = Path(path_value).relative_to(active_result)
        except ValueError:
            pass
        else:
            path_value = _relative(result_dir / suffix, root)
    request = EvidenceRequest(
        kind=item.kind,
        run_id=item.run_id,
        path_value=path_value,
        disposition=item.disposition,
        role=item.role,
        reason=item.reason,
    )
    return _resolve_evidence(root, request, result_dir=result_dir)


def _validate_evidence_records(records: tuple[ResultEvidence, ...]) -> None:
    if not any(item.disposition == "include" for item in records):
        raise ResearchWorkspaceError(
            "Result requires at least one included evidence item"
        )
    signatures = [_single_evidence_signature(item) for item in records]
    if len(signatures) != len(set(signatures)):
        raise ResearchWorkspaceError("Result evidence contains a duplicate item")
    if any(not item.reason.strip() for item in records):
        raise ResearchWorkspaceError(
            "every Result evidence item requires a non-empty selection reason"
        )


def _validate_result_source_readiness(
    root: Path,
    records: tuple[ResultEvidence, ...],
) -> None:
    """Require included Run-owned evidence to be reviewed and reproducible."""
    issues = _result_source_readiness_issues(root, records)
    if issues:
        raise ResearchWorkspaceError(
            "Result source quality gate failed: " + "; ".join(issues)
        )


def _result_source_readiness_issues(
    root: Path,
    records: tuple[ResultEvidence, ...],
) -> list[str]:
    """Return deterministic quality issues for included Run-owned evidence."""
    run_ids = {
        run_id
        for item in records
        if item.disposition == "include"
        for run_id in (
            item.run_id
            if item.kind == "run"
            else item.owner_id
            if item.owner_kind == "run"
            else None,
        )
        if run_id is not None
    }
    issues: list[str] = []
    for run_id in sorted(run_ids):
        manifest_path = _find_run_manifest(root, run_id)
        try:
            manifest = read_manifest(manifest_path.parent)
        except (ManifestError, ManifestNotFoundError) as exc:
            issues.append(f"{run_id}: cannot read manifest ({exc})")
            continue

        status = str(manifest.run.get("status", "")).strip()
        completed_states = {"completed", "archived", "purged"}
        if status not in completed_states:
            issues.append(f"{run_id}: source Run is not completed-equivalent")

        if not has_valid_run_review(manifest.curation):
            issues.append(
                f"{run_id}: source Run has not been reviewed with a complete "
                "timestamped record"
            )

        missing_identity = [
            key
            for key in (
                "condition_hash",
                "input_hash",
                "execution_hash",
                "provenance_hash",
            )
            if _SHA256_IDENTITY.fullmatch(str(manifest.identity.get(key, "")).strip())
            is None
        ]
        if missing_identity:
            issues.append(
                f"{run_id}: identity is missing {', '.join(missing_identity)}"
            )

        source = manifest.simulator_source
        git_commit = str(source.get("git_commit", "")).strip()
        executable_hashes = [
            str(source.get(key, "")).strip()
            for key in ("exe_hash", "executable_hash")
            if str(source.get(key, "")).strip()
        ]
        if not executable_hashes:
            issues.append(f"{run_id}: simulator executable hash is missing")
        elif not all(
            _SHA256_IDENTITY.fullmatch(value) is not None for value in executable_hashes
        ):
            issues.append(
                f"{run_id}: simulator executable hash is not sha256:<64 lowercase hex>"
            )
        version = next(
            (
                str(source.get(key, "")).strip()
                for key in ("package_version", "simulator_version", "version")
                if str(source.get(key, "")).strip()
            ),
            "",
        )
        if not git_commit:
            issues.append(f"{run_id}: simulator source commit is missing")
        if not version:
            issues.append(f"{run_id}: simulator/package version is missing")
        if source.get("git_dirty") is True and not any(
            str(source.get(key, "")).strip()
            for key in ("diff_path", "source_diff", "git_diff")
        ):
            issues.append(f"{run_id}: dirty simulator source has no diff reference")

        baseline = str(manifest.intent.get("baseline_run", "")).strip()
        baseline_runs = manifest.intent.get("baseline_runs", [])
        baseline_reason = str(manifest.intent.get("baseline_reason", "")).strip()
        has_baseline = bool(_RUN_ID.fullmatch(baseline)) or (
            isinstance(baseline_runs, list)
            and bool(baseline_runs)
            and all(
                isinstance(item, str) and _RUN_ID.fullmatch(item)
                for item in baseline_runs
            )
        )
        if not has_baseline and not baseline_reason:
            issues.append(f"{run_id}: baseline Run or not-required reason is missing")
        if has_baseline:
            baseline_ids = [baseline] if baseline else []
            if isinstance(baseline_runs, list):
                baseline_ids.extend(
                    item
                    for item in baseline_runs
                    if isinstance(item, str) and item not in baseline_ids
                )
            for baseline_id in baseline_ids:
                try:
                    baseline_manifest_path = _find_run_manifest(root, baseline_id)
                    baseline_manifest = read_manifest(baseline_manifest_path.parent)
                except (
                    ManifestError,
                    ManifestNotFoundError,
                    ResearchWorkspaceError,
                ) as exc:
                    issues.append(
                        f"{run_id}: baseline Run {baseline_id} is not "
                        f"resolvable ({exc})"
                    )
                    continue
                baseline_status = str(baseline_manifest.run.get("status", "")).strip()
                if baseline_status not in completed_states:
                    issues.append(
                        f"{run_id}: baseline Run {baseline_id} is not "
                        "completed-equivalent"
                    )

        input_name = str(manifest.files.get("input_dir", "input")).strip() or "input"
        input_dir = manifest_path.parent / input_name
        try:
            has_input = (
                input_dir.is_dir()
                and not input_dir.is_symlink()
                and any(
                    path.is_file() and not path.is_symlink()
                    for path in input_dir.rglob("*")
                )
            )
        except OSError:
            has_input = False
        if not has_input:
            issues.append(f"{run_id}: input snapshot is missing")
        elif str(manifest.identity.get("input_hash", "")).startswith("sha256:"):
            try:
                actual_input_hash = directory_content_hash(input_dir)
            except (OSError, SimctlError) as exc:
                issues.append(f"{run_id}: cannot hash input snapshot ({exc})")
            else:
                if actual_input_hash != manifest.identity.get("input_hash"):
                    issues.append(
                        f"{run_id}: input snapshot does not match identity.input_hash"
                    )
    return issues


def _resolve_result(root: Path, result: str | Path) -> Path:
    text = str(result).strip()
    if not text:
        raise ResearchWorkspaceError("Result identifier must not be empty")
    token = Path(text)
    roots = (root / _RESULT_ROOT, root / _RESULT_ARCHIVE_ROOT)
    candidates: list[Path] = []
    if token.is_absolute():
        candidates.append(token)
    elif len(token.parts) > 1:
        if ".." in token.parts:
            raise ResearchWorkspaceError("Result path must not escape the project")
        candidates.append(root / token)
    else:
        candidates.extend(item / text for item in roots)
    matches = [
        candidate
        for candidate in candidates
        if candidate.exists() or candidate.is_symlink()
    ]
    if not matches:
        raise ResearchWorkspaceError(f"Result not found: {text}")
    if len(matches) > 1:
        raise ResearchWorkspaceError(
            f"Result is ambiguous across active/archive: {text}"
        )
    result_dir = matches[0]
    _assert_safe_directory(result_dir, root=root, label="Result")
    try:
        resolved = result_dir.resolve(strict=True)
    except OSError as exc:
        raise ResearchWorkspaceError(f"cannot resolve Result: {exc}") from exc
    if not any(_is_relative_to(resolved, item.resolve()) for item in roots):
        raise ResearchWorkspaceError("Result path is outside active/archive roots")
    return result_dir


def _find_run_manifest(root: Path, run_id: str) -> Path:
    runs_root = root / "runs"
    matches: list[Path] = []
    try:
        records = collect_run_manifests_strict(runs_root)
    except SimctlError as exc:
        raise ResearchWorkspaceError(
            f"cannot safely inspect the formal Run namespace: {exc}"
        ) from exc
    for run_dir, manifest in records:
        manifest_path = run_dir / "manifest.toml"
        if manifest.run.get("id") == run_id:
            matches.append(manifest_path)
    if not matches:
        raise ResearchWorkspaceError(
            f"run evidence not found in project manifests: {run_id}"
        )
    if len(matches) > 1:
        raise ResearchWorkspaceError(f"duplicate project run_id: {run_id}")
    return matches[0]


def _resolve_project_file(root: Path, value: str) -> Path:
    if not value:
        raise ResearchWorkspaceError("path evidence requires a project-relative path")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ResearchWorkspaceError("path evidence must not escape the project")
    forbidden_prefixes = (
        (".runops", "test-runs"),
        (".runops", "scratch", "runs"),
    )
    if any(relative.parts[: len(prefix)] == prefix for prefix in forbidden_prefixes):
        raise ResearchWorkspaceError(
            "test attempt artifacts cannot be used as scientific Result evidence"
        )
    source = root / relative
    try:
        source.resolve(strict=False).relative_to(root)
    except ValueError as exc:
        raise ResearchWorkspaceError("path evidence escapes the project") from exc
    return source


def _path_evidence_owner(
    root: Path,
    source: Path,
    *,
    result_dir: Path | None,
) -> tuple[str, str, str]:
    """Return the Run/Result owner of a path evidence file."""
    for relative_root in (_RESULT_ROOT, _RESULT_ARCHIVE_ROOT):
        results_root = root / relative_root
        try:
            relative = source.relative_to(results_root)
        except ValueError:
            continue
        if len(relative.parts) < 3 or relative.parts[1] != "artifacts":
            raise ResearchWorkspaceError(
                "Result path evidence must be inside its artifacts/ directory"
            )
        owner_dir = results_root / relative.parts[0]
        _assert_safe_directory(owner_dir, root=root, label="evidence Result")
        owner_manifest = owner_dir / "manifest.toml"
        _assert_safe_regular_file(
            owner_manifest,
            root=root,
            label="evidence Result manifest",
        )
        try:
            read_result_manifest(owner_dir)
        except ResultManifestError as exc:
            raise ResearchWorkspaceError(
                f"invalid evidence Result manifest: {exc}"
            ) from exc
        return (
            "result",
            owner_dir.name,
            source.relative_to(owner_dir).as_posix(),
        )

    runs_root = root / "runs"
    try:
        source.relative_to(runs_root)
    except ValueError:
        pass
    else:
        try:
            records = collect_run_manifests_strict(runs_root)
        except SimctlError as exc:
            raise ResearchWorkspaceError(
                f"cannot safely inspect the formal Run namespace: {exc}"
            ) from exc
        owners = [
            (run_dir, manifest)
            for run_dir, manifest in records
            if _is_relative_to(source, run_dir)
        ]
        if len(owners) > 1:
            raise ResearchWorkspaceError(
                "path evidence belongs to multiple canonical Run roots"
            )
        if owners:
            owner_dir, manifest = owners[0]
            owner_id = manifest.run.get("id")
            if not isinstance(owner_id, str) or not _RUN_ID.fullmatch(owner_id):
                raise ResearchWorkspaceError(
                    "path evidence owner must have a canonical run_id"
                )
            relative = source.relative_to(owner_dir)
            if relative == Path("manifest.toml"):
                raise ResearchWorkspaceError(
                    "use evidence-run for a Run manifest source"
                )
            return "run", owner_id, relative.as_posix()

    relation = "Run or Result artifacts/"
    if result_dir is not None:
        relation = f"Run or {result_dir.name}/artifacts"
    raise ResearchWorkspaceError(f"path evidence must belong to a {relation}")


def _file_receipt(path: Path, *, root: Path, label: str) -> FileReceipt:
    metadata = _assert_safe_regular_file(path, root=root, label=label)
    digest = hashlib.sha256()
    byte_count = 0
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
                byte_count += len(chunk)
        after = path.lstat()
    except OSError as exc:
        raise ResearchWorkspaceError(f"cannot read {label}: {exc}") from exc
    identity = (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
    )
    after_identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if identity != after_identity or byte_count != metadata.st_size:
        raise ResearchWorkspaceError(f"{label} changed while hashing")
    return {"sha256": digest.hexdigest(), "bytes": byte_count}


def _run_scientific_receipt(
    manifest_path: Path,
    *,
    root: Path,
    run_id: str,
) -> FileReceipt:
    """Hash immutable scientific provenance, excluding operational state."""
    label = f"run {run_id} manifest"
    before = _file_receipt(manifest_path, root=root, label=label)
    try:
        manifest = read_manifest(manifest_path.parent)
    except (ManifestError, ManifestNotFoundError) as exc:
        raise ResearchWorkspaceError(f"cannot read {label}: {exc}") from exc
    if manifest.run.get("id") != run_id:
        raise ResearchWorkspaceError(f"run manifest id does not match {run_id}")
    after = _file_receipt(manifest_path, root=root, label=label)
    if before != after:
        raise ResearchWorkspaceError(f"{label} changed while reading")

    mutable_job_fields = {
        "job_id",
        "submitted_at",
        "attempt",
        "attempts",
        "queue",
        "last_slurm_state",
    }
    payload = {
        "run_id": run_id,
        "origin": manifest.origin,
        "classification": manifest.classification,
        "simulator": manifest.simulator,
        "launcher": manifest.launcher,
        "simulator_source": manifest.simulator_source,
        "job_configuration": {
            key: value
            for key, value in manifest.job.items()
            if key not in mutable_job_fields
        },
        "variation": manifest.variation,
        "params_snapshot": manifest.params_snapshot,
        "intent": manifest.intent,
        "identity": manifest.identity,
    }
    encoded = _canonical_json(payload)
    return {"sha256": hashlib.sha256(encoded).hexdigest(), "bytes": len(encoded)}


def _assert_safe_regular_file(
    path: Path,
    *,
    root: Path,
    label: str,
) -> os.stat_result:
    _assert_no_symlink_components(path, root=root, label=label)
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ResearchWorkspaceError(f"missing or unreadable {label}: {path}") from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise ResearchWorkspaceError(f"unsafe {label}: expected a regular file")
    if metadata.st_nlink != 1:
        raise ResearchWorkspaceError(f"unsafe hardlink for {label}")
    return metadata


def _assert_safe_directory(path: Path, *, root: Path, label: str) -> None:
    _assert_no_symlink_components(path, root=root, label=label)
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ResearchWorkspaceError(f"missing or unreadable {label}: {path}") from exc
    if not stat.S_ISDIR(metadata.st_mode):
        raise ResearchWorkspaceError(f"unsafe {label}: expected a directory")


def _assert_no_symlink_components(path: Path, *, root: Path, label: str) -> None:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise ResearchWorkspaceError(f"unsafe {label}: path escapes project") from exc
    current = root
    for part in relative.parts:
        current = current / part
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise ResearchWorkspaceError(
                f"missing or unreadable {label}: {current}"
            ) from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise ResearchWorkspaceError(f"unsafe symlink in {label}: {current}")


def _request_signature(
    evidence: tuple[EvidenceRequest, ...],
) -> tuple[tuple[str, str, str, str, str], ...]:
    signatures = []
    for item in evidence:
        locator = item.run_id if item.kind.strip() == "run" else item.path_value
        normalized_locator = (locator or "").strip()
        if item.kind.strip() == "path" and normalized_locator:
            normalized_locator = Path(normalized_locator).as_posix()
        signatures.append(
            (
                item.kind.strip(),
                normalized_locator,
                item.disposition.strip(),
                item.role.strip(),
                item.reason.strip(),
            )
        )
    return tuple(sorted(signatures))


def _evidence_signature(
    evidence: tuple[ResultEvidence, ...],
) -> tuple[tuple[str, str, str, str, str], ...]:
    return tuple(sorted(_single_evidence_signature(item) for item in evidence))


def _single_evidence_signature(item: ResultEvidence) -> tuple[str, str, str, str, str]:
    locator = item.run_id if item.kind == "run" else item.path
    return (
        item.kind,
        locator or "",
        item.disposition,
        item.role,
        item.reason,
    )


def _evidence_payload(item: ResultEvidence) -> dict[str, object]:
    payload: dict[str, object] = {
        "kind": item.kind,
        "disposition": item.disposition,
        "role": item.role,
        "reason": item.reason,
    }
    if item.run_id is not None:
        payload["run_id"] = item.run_id
    if item.path is not None:
        payload["path"] = item.path
    if item.source_path is not None:
        payload["source_path"] = item.source_path
    if item.owner_kind is not None:
        payload["owner_kind"] = item.owner_kind
    if item.owner_id is not None:
        payload["owner_id"] = item.owner_id
    if item.owner_relative_path is not None:
        payload["owner_relative_path"] = item.owner_relative_path
    if item.receipt_kind is not None:
        payload["receipt_kind"] = item.receipt_kind
    if item.sha256 is not None:
        payload["sha256"] = item.sha256
    if item.byte_count is not None:
        payload["bytes"] = item.byte_count
    return payload


def _canonical_json(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sealed_manifest_digest(payload: dict[str, Any]) -> str:
    normalized = copy.deepcopy(payload)
    seal = normalized.get("seal")
    if isinstance(seal, dict):
        seal.pop("content_sha256", None)
    return hashlib.sha256(_canonical_json(normalized)).hexdigest()


def _write_toml_atomic(path: Path, payload: dict[str, Any]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=".manifest-",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            tomli_w.dump(payload, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(
            path.parent,
            os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY,
        )
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise ResearchWorkspaceError(f"cannot seal Result manifest: {exc}") from exc
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _issue(code: str, message: str, *, path: str = "") -> ResultCheckIssue:
    return ResultCheckIssue(severity="error", code=code, message=message, path=path)


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _is_relative_to(path: Path, other: Path) -> bool:
    try:
        path.relative_to(other)
    except ValueError:
        return False
    return True
