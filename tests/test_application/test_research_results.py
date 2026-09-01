"""Tests for research result evidence checks and sealing."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from runops.application.research import results as results_module
from runops.application.research.results import (
    EvidenceRequest,
    check_result,
    seal_result,
)
from runops.application.research.workspace import (
    ResearchWorkspaceError,
    archive_result,
    create_result,
)
from runops.application.run_creation.workflow import directory_content_hash
from runops.core.manifest import ManifestData, read_manifest, write_manifest
from runops.core.research.result import ResultEvidence, read_result_manifest
from runops.core.research.workspace import ResearchBudget


def _scaffold(root: Path) -> None:
    (root / "research" / "results").mkdir(parents=True)
    (root / "research" / "archive" / "results").mkdir(parents=True)


def _write_run(root: Path, run_id: str) -> Path:
    run_dir = root / "runs" / "pilot" / run_id
    (run_dir / "input").mkdir(parents=True)
    (run_dir / "input" / "params.toml").write_text("nx = 64\n", encoding="utf-8")
    write_manifest(
        run_dir,
        ManifestData(
            run={"id": run_id, "status": "completed"},
            origin={"case": "base"},
            simulator={"name": "generic"},
            launcher={"name": "srun"},
            simulator_source={
                "git_commit": "abc123",
                "git_dirty": False,
                "exe_hash": "sha256:" + "a" * 64,
                "package_version": "1.0.0",
            },
            job={"scheduler": "slurm", "job_id": "1", "submitted_at": "now"},
            params_snapshot={},
            files={"input_dir": "input"},
            intent={
                "experiment_id": "E20260801-0001",
                "baseline_run": run_id,
            },
            identity={
                "condition_hash": "sha256:" + "b" * 64,
                "input_hash": directory_content_hash(run_dir / "input"),
                "execution_hash": "sha256:" + "c" * 64,
                "provenance_hash": "sha256:" + "d" * 64,
            },
            curation={
                "review_status": "reviewed",
                "reviewed_at": "2026-09-01T00:00:00+00:00",
                "reviewed_by": "human",
                "reason": "accepted for Result evidence",
            },
        ),
    )
    return run_dir


def test_create_result_uses_active_and_archive_sequence_and_canonical_manifest(
    tmp_path: Path,
) -> None:
    _scaffold(tmp_path)
    (tmp_path / "research/results/R0002-active").mkdir()
    (tmp_path / "research/archive/results/R0008-old").mkdir()

    created = create_result(tmp_path, "Dust release")
    manifest = read_result_manifest(created.path)

    assert created.result_id == "R0009-dust-release"
    assert manifest.status == "draft"
    assert manifest.claim == ""
    assert manifest.outcome is None
    assert not list((tmp_path / "research/results").glob(".tmp-result-*"))


def test_create_result_allocator_serializes_concurrent_creators(tmp_path: Path) -> None:
    _scaffold(tmp_path)

    with ThreadPoolExecutor(max_workers=2) as pool:
        created = list(
            pool.map(
                lambda name: create_result(tmp_path, name),
                ("First result", "Second result"),
            )
        )

    assert {item.result_id[:5] for item in created} == {"R0001", "R0002"}
    assert all(item.path.is_dir() for item in created)
    assert not list((tmp_path / "research/results").glob(".tmp-result-*"))


def test_seal_result_records_run_and_artifact_receipts_atomically(
    tmp_path: Path,
) -> None:
    _scaffold(tmp_path)
    run_id = "R20260801-0001"
    run_dir = _write_run(tmp_path, run_id)
    run_manifest_before = (run_dir / "manifest.toml").read_bytes()
    created = create_result(tmp_path, "Dust release")
    artifact = created.path / "artifacts" / "summary.csv"
    artifact.write_text("value\n1\n", encoding="utf-8")

    sealed = seal_result(
        tmp_path,
        created.result_id,
        claim="Release rises above the baseline.",
        outcome="supported",
        evidence=(
            EvidenceRequest.run(
                run_id,
                role="primary",
                reason="primary completed comparison",
            ),
            EvidenceRequest.path(
                artifact.relative_to(tmp_path).as_posix(),
                role="summary",
                reason="derived summary used by the claim",
            ),
        ),
    )
    manifest = read_result_manifest(created.path)
    checked = check_result(tmp_path, created.result_id)

    assert sealed.changed is True
    assert manifest.status == "sealed"
    assert len(manifest.evidence) == 2
    assert all(
        item.sha256 and item.byte_count is not None for item in manifest.evidence
    )
    assert manifest.seal["readme_sha256"]
    assert "[[evidence]]" in (created.path / "manifest.toml").read_text(
        encoding="utf-8"
    )
    assert (run_dir / "manifest.toml").read_bytes() == run_manifest_before
    assert checked.ok is True
    assert checked.sealed is True

    archived = archive_result(tmp_path, created.result_id)
    assert archived == tmp_path / "research/archive/results" / created.result_id
    assert check_result(tmp_path, created.result_id).ok is True

    operational_before = (run_dir / "manifest.toml").read_text(encoding="utf-8")
    operational = operational_before.replace(
        'status = "completed"',
        'status = "archived"',
    )
    assert operational != operational_before
    (run_dir / "manifest.toml").write_text(operational, encoding="utf-8")
    assert check_result(tmp_path, created.result_id).ok is True


@pytest.mark.parametrize(
    ("violation", "expected_code"),
    [
        ("readme_chars", "result.readme_too_large"),
        ("artifact_files", "artifact.too_many_files"),
        ("artifact_bytes", "artifact.too_large"),
        ("artifact_markdown", "artifact.markdown_forbidden"),
    ],
)
def test_result_local_hard_gates_are_shared_by_check_and_seal(
    tmp_path: Path,
    violation: str,
    expected_code: str,
) -> None:
    _scaffold(tmp_path)
    run_id = "R20260801-0001"
    _write_run(tmp_path, run_id)
    created = create_result(tmp_path, "Bounded Result")
    budget = ResearchBudget()

    if violation == "readme_chars":
        (created.path / "README.md").write_text("12345", encoding="utf-8")
        budget = ResearchBudget(result_readme_chars=4)
    elif violation == "artifact_files":
        (created.path / "artifacts" / "first.csv").write_text("", encoding="utf-8")
        (created.path / "artifacts" / "second.csv").write_text("", encoding="utf-8")
        budget = ResearchBudget(result_artifact_files=1)
    elif violation == "artifact_bytes":
        (created.path / "artifacts" / "large.bin").write_bytes(b"12345")
        budget = ResearchBudget(result_artifact_bytes=4)
    else:
        (created.path / "artifacts" / "notes.md").write_text(
            "narrative",
            encoding="utf-8",
        )

    checked = check_result(tmp_path, created.result_id, budget=budget)
    manifest_path = created.path / "manifest.toml"
    manifest_before = manifest_path.read_bytes()

    assert checked.ok is False
    assert checked.ready_to_seal is False
    assert expected_code in {issue.code for issue in checked.issues}
    with pytest.raises(ResearchWorkspaceError, match=expected_code):
        seal_result(
            tmp_path,
            created.result_id,
            claim="A bounded claim.",
            outcome="supported",
            evidence=(EvidenceRequest.run(run_id, reason="selected reviewed source"),),
            budget=budget,
        )
    assert manifest_path.read_bytes() == manifest_before
    assert read_result_manifest(created.path).status == "draft"


def test_same_seal_is_idempotent_but_changed_source_refuses_reseal(
    tmp_path: Path,
) -> None:
    _scaffold(tmp_path)
    run_id = "R20260801-0001"
    run_dir = _write_run(tmp_path, run_id)
    created = create_result(tmp_path, "Dust release")
    request = (EvidenceRequest.run(run_id, reason="selected completed Run"),)

    first = seal_result(
        tmp_path,
        created.result_id,
        claim="Stable result.",
        outcome="inconclusive",
        evidence=request,
    )
    second = seal_result(
        tmp_path,
        created.result_id,
        claim="Stable result.",
        outcome="inconclusive",
        evidence=request,
    )

    assert first.changed is True
    assert second.changed is False

    source_before = (run_dir / "manifest.toml").read_text(encoding="utf-8")
    changed = source_before.replace(
        'case = "base"',
        'case = "changed"',
    )
    assert changed != source_before
    (run_dir / "manifest.toml").write_text(changed, encoding="utf-8")
    with pytest.raises(ResearchWorkspaceError, match="changed after sealing"):
        seal_result(
            tmp_path,
            created.result_id,
            claim="Stable result.",
            outcome="inconclusive",
            evidence=request,
        )


def test_path_evidence_records_run_owner_and_survives_run_relocation(
    tmp_path: Path,
) -> None:
    _scaffold(tmp_path)
    run_id = "R20260801-0001"
    run_dir = _write_run(tmp_path, run_id)
    table = run_dir / "analysis" / "summary.csv"
    table.parent.mkdir()
    table.write_text("value\n1\n", encoding="utf-8")
    created = create_result(tmp_path, "Run artifact")

    seal_result(
        tmp_path,
        created.result_id,
        claim="The run produced the expected value.",
        outcome="supported",
        evidence=(
            EvidenceRequest.path(
                table.relative_to(tmp_path).as_posix(),
                reason="selected Run-owned summary",
            ),
        ),
    )
    manifest = read_result_manifest(created.path)

    assert manifest.evidence[0].owner_kind == "run"
    assert manifest.evidence[0].owner_id == run_id
    assert manifest.evidence[0].owner_relative_path == "analysis/summary.csv"

    relocated_parent = tmp_path / "runs" / "relocated"
    relocated_parent.mkdir()
    run_dir.rename(relocated_parent / run_id)
    assert check_result(tmp_path, created.result_id).ok is True


def test_path_evidence_uses_canonical_run_root_not_nested_manifest(
    tmp_path: Path,
) -> None:
    _scaffold(tmp_path)
    owner_id = "R20260801-0001"
    owner_dir = _write_run(tmp_path, owner_id)
    owner_manifest = read_manifest(owner_dir)
    owner_manifest.curation = {"review_status": "unreviewed"}
    write_manifest(owner_dir, owner_manifest)

    unrelated_id = "R20260801-0002"
    unrelated_dir = _write_run(tmp_path, unrelated_id)
    nested = owner_dir / "work" / "payload"
    nested.mkdir(parents=True)
    write_manifest(nested, read_manifest(unrelated_dir))
    artifact = nested / "summary.csv"
    artifact.write_text("value\n1\n", encoding="utf-8")
    created = create_result(tmp_path, "Canonical path owner")

    with pytest.raises(ResearchWorkspaceError, match="not been reviewed"):
        seal_result(
            tmp_path,
            created.result_id,
            claim="Nested payload manifests cannot change evidence ownership.",
            outcome="supported",
            evidence=(
                EvidenceRequest.path(
                    artifact.relative_to(tmp_path).as_posix(),
                    reason="Run-owned nested artifact",
                ),
            ),
        )

    assert read_result_manifest(created.path).status == "draft"


def test_seal_rejects_a_downgraded_sealed_manifest(tmp_path: Path) -> None:
    _scaffold(tmp_path)
    run_id = "R20260801-0001"
    _write_run(tmp_path, run_id)
    created = create_result(tmp_path, "Dust release")
    request = (EvidenceRequest.run(run_id, reason="selected completed Run"),)
    seal_result(
        tmp_path,
        created.result_id,
        claim="Stable result.",
        outcome="supported",
        evidence=request,
    )
    manifest_path = created.path / "manifest.toml"
    downgraded = manifest_path.read_text(encoding="utf-8").replace(
        'status = "sealed"',
        'status = "draft"',
    )
    manifest_path.write_text(downgraded, encoding="utf-8")

    with pytest.raises(ResearchWorkspaceError, match="changed after sealing"):
        seal_result(
            tmp_path,
            created.result_id,
            claim="Stable result.",
            outcome="supported",
            evidence=request,
        )


def test_seal_rejects_test_receipts(
    tmp_path: Path,
) -> None:
    _scaffold(tmp_path)
    created = create_result(tmp_path, "Dust release")

    with pytest.raises(ResearchWorkspaceError, match="test attempt"):
        seal_result(
            tmp_path,
            created.result_id,
            claim="Claim",
            outcome="invalid",
            evidence=(EvidenceRequest.run("T20260801-0001"),),
        )


def test_seal_rejects_excluded_evidence_without_reason(tmp_path: Path) -> None:
    _scaffold(tmp_path)
    run_id = "R20260801-0001"
    _write_run(tmp_path, run_id)
    created = create_result(tmp_path, "Selection reasons")

    with pytest.raises(
        ResearchWorkspaceError, match="excluded evidence requires a reason"
    ):
        seal_result(
            tmp_path,
            created.result_id,
            claim="Claim",
            outcome="inconclusive",
            evidence=(
                EvidenceRequest.run(run_id, reason="selected primary source"),
                EvidenceRequest.run(run_id, disposition="exclude"),
            ),
        )


def test_seal_blocks_unreviewed_or_incomplete_run_evidence(tmp_path: Path) -> None:
    _scaffold(tmp_path)
    run_id = "R20260801-0001"
    run_dir = _write_run(tmp_path, run_id)
    manifest = read_manifest(run_dir)
    manifest.run["status"] = "failed"
    manifest.curation["review_status"] = "unreviewed"
    write_manifest(run_dir, manifest)
    created = create_result(tmp_path, "Unsafe source")

    with pytest.raises(ResearchWorkspaceError, match="quality gate failed") as exc:
        seal_result(
            tmp_path,
            created.result_id,
            claim="Claim",
            outcome="invalid",
            evidence=(EvidenceRequest.run(run_id, reason="candidate evidence"),),
        )

    assert "not completed-equivalent" in str(exc.value)
    assert "not been reviewed" in str(exc.value)


def test_seal_blocks_review_status_without_complete_metadata(tmp_path: Path) -> None:
    _scaffold(tmp_path)
    run_id = "R20260801-0001"
    run_dir = _write_run(tmp_path, run_id)
    manifest = read_manifest(run_dir)
    manifest.curation["reviewed_at"] = ""
    write_manifest(run_dir, manifest)
    created = create_result(tmp_path, "Incomplete review")

    with pytest.raises(ResearchWorkspaceError, match="quality gate failed") as exc:
        seal_result(
            tmp_path,
            created.result_id,
            claim="Claim",
            outcome="inconclusive",
            evidence=(EvidenceRequest.run(run_id, reason="candidate evidence"),),
        )

    assert "a complete timestamped record" in str(exc.value)


def test_seal_rejects_unsafe_hidden_formal_run_namespace(tmp_path: Path) -> None:
    _scaffold(tmp_path)
    run_id = "R20260801-0001"
    _write_run(tmp_path, run_id)
    outside = tmp_path / "outside-runs"
    outside.mkdir()
    (tmp_path / "runs" / "hidden").symlink_to(outside, target_is_directory=True)
    created = create_result(tmp_path, "Unsafe namespace")

    with pytest.raises(
        ResearchWorkspaceError,
        match="cannot safely inspect the formal Run namespace",
    ):
        seal_result(
            tmp_path,
            created.result_id,
            claim="This must remain a draft.",
            outcome="invalid",
            evidence=(EvidenceRequest.run(run_id, reason="negative namespace test"),),
        )

    assert read_result_manifest(created.path).status == "draft"


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("identity", "condition_hash", "sha256:short"),
        ("identity", "provenance_hash", "sha256:" + "A" * 64),
        ("simulator_source", "exe_hash", "sha256:short"),
        ("simulator_source", "exe_hash", "sha256:" + "A" * 64),
        ("simulator_source", "executable_hash", "sha256:short"),
    ],
)
def test_seal_rejects_noncanonical_scientific_hashes(
    tmp_path: Path,
    section: str,
    key: str,
    value: str,
) -> None:
    _scaffold(tmp_path)
    run_id = "R20260801-0001"
    run_dir = _write_run(tmp_path, run_id)
    manifest = read_manifest(run_dir)
    target = manifest.identity if section == "identity" else manifest.simulator_source
    target[key] = value
    write_manifest(run_dir, manifest)
    created = create_result(tmp_path, "Invalid hash source")

    with pytest.raises(ResearchWorkspaceError, match="quality gate failed"):
        seal_result(
            tmp_path,
            created.result_id,
            claim="This source must not be sealable.",
            outcome="invalid",
            evidence=(EvidenceRequest.run(run_id, reason="negative test source"),),
        )


@pytest.mark.parametrize("status", ["archived", "purged"])
def test_seal_accepts_reviewed_completed_equivalent_evidence(
    tmp_path: Path,
    status: str,
) -> None:
    _scaffold(tmp_path)
    run_id = "R20260801-0001"
    run_dir = _write_run(tmp_path, run_id)
    manifest = read_manifest(run_dir)
    manifest.run["status"] = status
    write_manifest(run_dir, manifest)
    created = create_result(tmp_path, f"Cold source {status}")

    sealed = seal_result(
        tmp_path,
        created.result_id,
        claim="The cold source remains valid evidence.",
        outcome="supported",
        evidence=(EvidenceRequest.run(run_id, reason="reviewed cold evidence"),),
    )

    assert sealed.changed is True


def test_seal_rejects_input_snapshot_modified_after_identity_freeze(
    tmp_path: Path,
) -> None:
    _scaffold(tmp_path)
    run_id = "R20260801-0001"
    run_dir = _write_run(tmp_path, run_id)
    created = create_result(tmp_path, "Tampered input")
    request = EvidenceRequest.run(run_id, reason="tampered candidate")
    seal_result(
        tmp_path,
        created.result_id,
        claim="The initial snapshot is intact.",
        outcome="supported",
        evidence=(request,),
    )
    (run_dir / "input" / "params.toml").write_text("nx = 128\n", encoding="utf-8")

    checked = check_result(tmp_path, created.result_id)
    assert checked.ok is False
    assert any("input_hash" in issue.message for issue in checked.issues)

    with pytest.raises(ResearchWorkspaceError, match="does not match"):
        seal_result(
            tmp_path,
            created.result_id,
            claim="The initial snapshot is intact.",
            outcome="supported",
            evidence=(request,),
        )


def test_seal_rejects_run_input_tree_with_external_symlink(tmp_path: Path) -> None:
    _scaffold(tmp_path)
    run_id = "R20260801-0001"
    run_dir = _write_run(tmp_path, run_id)
    outside = tmp_path / "mutable-external-input.toml"
    outside.write_text("nx = 64\n", encoding="utf-8")
    (run_dir / "input" / "critical.toml").symlink_to(outside)
    created = create_result(tmp_path, "Unsafe input snapshot")

    with pytest.raises(ResearchWorkspaceError, match="quality gate failed") as exc:
        seal_result(
            tmp_path,
            created.result_id,
            claim="The snapshot is reproducible.",
            outcome="supported",
            evidence=(EvidenceRequest.run(run_id, reason="candidate run evidence"),),
        )

    assert "symbolic links" in str(exc.value)


def test_sealed_result_detects_symlink_added_to_source_input(tmp_path: Path) -> None:
    _scaffold(tmp_path)
    run_id = "R20260801-0001"
    run_dir = _write_run(tmp_path, run_id)
    created = create_result(tmp_path, "Initially safe input")
    seal_result(
        tmp_path,
        created.result_id,
        claim="The snapshot is reproducible.",
        outcome="supported",
        evidence=(EvidenceRequest.run(run_id, reason="candidate run evidence"),),
    )
    outside = tmp_path / "mutable-after-seal.toml"
    outside.write_text("nx = 128\n", encoding="utf-8")
    (run_dir / "input" / "critical.toml").symlink_to(outside)

    checked = check_result(tmp_path, created.result_id)

    assert checked.ok is False
    assert any("symbolic links" in issue.message for issue in checked.issues)


def test_seal_blocks_missing_reproducibility_provenance(tmp_path: Path) -> None:
    _scaffold(tmp_path)
    run_id = "R20260801-0001"
    run_dir = _write_run(tmp_path, run_id)
    manifest = read_manifest(run_dir)
    manifest.identity["input_hash"] = ""
    manifest.simulator_source["git_commit"] = ""
    manifest.simulator_source["package_version"] = ""
    manifest.intent["baseline_run"] = ""
    manifest.intent["baseline_runs"] = []
    manifest.intent["baseline_reason"] = ""
    write_manifest(run_dir, manifest)
    for path in (run_dir / "input").iterdir():
        path.unlink()
    created = create_result(tmp_path, "Missing provenance")

    with pytest.raises(ResearchWorkspaceError, match="quality gate failed") as exc:
        seal_result(
            tmp_path,
            created.result_id,
            claim="Claim",
            outcome="invalid",
            evidence=(EvidenceRequest.run(run_id, reason="candidate evidence"),),
        )

    message = str(exc.value)
    assert "input_hash" in message
    assert "source commit" in message
    assert "baseline Run" in message
    assert "input snapshot" in message

    with pytest.raises(ResearchWorkspaceError, match="RYYYYMMDD-NNNN"):
        seal_result(
            tmp_path,
            created.result_id,
            claim="Claim",
            outcome="invalid",
            evidence=(EvidenceRequest.run("not-a-run"),),
        )

    receipt = tmp_path / ".runops" / "test-runs" / "T0001" / "receipt.toml"
    receipt.parent.mkdir(parents=True)
    receipt.write_text("status = 'passed'\n", encoding="utf-8")
    with pytest.raises(ResearchWorkspaceError, match="test attempt"):
        seal_result(
            tmp_path,
            created.result_id,
            claim="Claim",
            outcome="invalid",
            evidence=(
                EvidenceRequest.path(
                    receipt.relative_to(tmp_path).as_posix(),
                ),
            ),
        )

    material = tmp_path / "materials" / "unowned.csv"
    material.parent.mkdir()
    material.write_text("value\n1\n", encoding="utf-8")
    with pytest.raises(ResearchWorkspaceError, match="must belong"):
        seal_result(
            tmp_path,
            created.result_id,
            claim="Claim",
            outcome="invalid",
            evidence=(EvidenceRequest.path(material.relative_to(tmp_path).as_posix()),),
        )

    with pytest.raises(ResearchWorkspaceError, match="reason"):
        seal_result(
            tmp_path,
            created.result_id,
            claim="Claim",
            outcome="invalid",
            evidence=(
                EvidenceRequest(
                    kind="path",
                    path_value="README.md",
                    disposition="exclude",
                    role="candidate",
                ),
            ),
        )


@pytest.mark.parametrize(
    ("missing_key", "expected_message"),
    [
        ("git_commit", "source commit is missing"),
        ("package_version", "simulator/package version is missing"),
    ],
)
def test_seal_requires_each_source_identity_component(
    tmp_path: Path,
    missing_key: str,
    expected_message: str,
) -> None:
    _scaffold(tmp_path)
    run_id = "R20260801-0001"
    run_dir = _write_run(tmp_path, run_id)
    manifest = read_manifest(run_dir)
    manifest.simulator_source[missing_key] = ""
    write_manifest(run_dir, manifest)
    created = create_result(tmp_path, "Incomplete source identity")

    with pytest.raises(ResearchWorkspaceError, match="quality gate failed") as exc:
        seal_result(
            tmp_path,
            created.result_id,
            claim="This source identity is incomplete.",
            outcome="invalid",
            evidence=(EvidenceRequest.run(run_id, reason="negative source test"),),
        )

    assert expected_message in str(exc.value)


def test_seal_requires_diff_reference_for_dirty_source_without_commit(
    tmp_path: Path,
) -> None:
    _scaffold(tmp_path)
    run_id = "R20260801-0001"
    run_dir = _write_run(tmp_path, run_id)
    manifest = read_manifest(run_dir)
    manifest.simulator_source["git_commit"] = ""
    manifest.simulator_source["git_dirty"] = True
    write_manifest(run_dir, manifest)
    created = create_result(tmp_path, "Unrecorded dirty source")

    with pytest.raises(ResearchWorkspaceError, match="quality gate failed") as exc:
        seal_result(
            tmp_path,
            created.result_id,
            claim="Dirty source must retain its diff.",
            outcome="invalid",
            evidence=(EvidenceRequest.run(run_id, reason="negative dirty test"),),
        )

    message = str(exc.value)
    assert "source commit is missing" in message
    assert "dirty simulator source has no diff reference" in message


@pytest.mark.parametrize(
    ("mutation", "expected_message"),
    [
        ("input", "input snapshot does not match identity.input_hash"),
        ("status", "source Run is not completed-equivalent"),
        ("review", "source Run has not been reviewed"),
    ],
)
def test_seal_rechecks_run_readiness_after_evidence_refresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    expected_message: str,
) -> None:
    _scaffold(tmp_path)
    run_id = "R20260801-0001"
    run_dir = _write_run(tmp_path, run_id)
    created = create_result(tmp_path, "Racing source readiness")
    original_resolve = results_module._resolve_evidence
    resolve_count = 0

    def resolve_with_mutation(
        root: Path,
        request: EvidenceRequest,
        *,
        result_dir: Path | None = None,
    ) -> ResultEvidence:
        nonlocal resolve_count
        resolve_count += 1
        if resolve_count == 2:
            if mutation == "input":
                (run_dir / "input" / "params.toml").write_text(
                    "nx = 128\n",
                    encoding="utf-8",
                )
            else:
                manifest = read_manifest(run_dir)
                if mutation == "status":
                    manifest.run["status"] = "failed"
                else:
                    manifest.curation["reviewed_at"] = ""
                write_manifest(run_dir, manifest)
        return original_resolve(root, request, result_dir=result_dir)

    monkeypatch.setattr(results_module, "_resolve_evidence", resolve_with_mutation)

    with pytest.raises(ResearchWorkspaceError, match="quality gate failed") as exc:
        seal_result(
            tmp_path,
            created.result_id,
            claim="The source must remain ready through publication.",
            outcome="invalid",
            evidence=(EvidenceRequest.run(run_id, reason="race regression"),),
        )

    assert resolve_count == 2
    assert expected_message in str(exc.value)
    assert read_result_manifest(created.path).status == "draft"


@pytest.mark.parametrize("unsafe_kind", ["traversal", "symlink", "hardlink"])
def test_seal_rejects_unsafe_path_evidence(
    tmp_path: Path,
    unsafe_kind: str,
) -> None:
    _scaffold(tmp_path)
    created = create_result(tmp_path, "Dust release")
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("outside", encoding="utf-8")
    if unsafe_kind == "traversal":
        source = f"../{outside.name}"
    elif unsafe_kind == "symlink":
        link = tmp_path / "linked.txt"
        link.symlink_to(outside)
        source = "linked.txt"
    else:
        original = tmp_path / "original.txt"
        original.write_text("same inode", encoding="utf-8")
        linked = tmp_path / "hardlinked.txt"
        os.link(original, linked)
        source = "hardlinked.txt"

    with pytest.raises(ResearchWorkspaceError, match=r"unsafe|escape|hardlink"):
        seal_result(
            tmp_path,
            created.result_id,
            claim="Claim",
            outcome="invalid",
            evidence=(EvidenceRequest.path(source),),
        )


def test_check_accepts_legacy_manifests_without_mutating_them(tmp_path: Path) -> None:
    _scaffold(tmp_path)
    for name, manifest in {
        "R0001-flat": 'schema_version = 1\nid = "R0001-flat"\nstatus = "active"\n',
        "R0002-comparison": (
            "[comparison]\n"
            'schema_version = 1\nid = "old"\nname = "Old"\nstatus = "draft"\n'
        ),
    }.items():
        result_dir = tmp_path / "research/results" / name
        result_dir.mkdir()
        (result_dir / "README.md").write_text("# Legacy\n", encoding="utf-8")
        (result_dir / "manifest.toml").write_text(manifest, encoding="utf-8")
        before = (result_dir / "manifest.toml").read_bytes()

        checked = check_result(tmp_path, name)

        assert checked.ok is True
        assert checked.layout.startswith("legacy-")
        assert (result_dir / "manifest.toml").read_bytes() == before
