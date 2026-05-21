---
id: D0017
record_type: decision
created_at: '2026-05-22T04:18:05+09:00'
status: needs-more-evidence
source: H0017
evidence:
  summary: RS0006; E0017 manual score; H0017; priority review observed runo mcp check already covers ActionSpec-to-MCP safety metadata, while CLI --yes and harness command policy remain outside a generated cross-surface matrix.
  guard_path: harnessops-core:tests/test_safety_matrix.py::test_generated_matrix_flags_split_confirmation_policy_drift
---

# D0017: needs-more-evidence H0017

## 判断

needs-more-evidence

## 理由

The candidate has clear cross-surface value and should extend RS0004, but this target repo lane did not implement the HarnessOps core generated/linted safety matrix. Adoption should wait until the upstream implementation proves the matrix is source-derived rather than another manually maintained policy page.

## 証拠

RS0006; E0017 manual score; H0017; priority review observed runo mcp check already covers ActionSpec-to-MCP safety metadata, while CLI --yes and harness command policy remain outside a generated cross-surface matrix.

## 回帰リスク

Medium. A matrix could become stale or duplicate docs unless generated/linted from existing ActionSpec, MCP registry, CLI, and harness policy sources with unknown surfaces reported as warnings.

## フォローアップ

Implement a HarnessOps/runops-facing read-only safety matrix lint/generation path, include fixtures for ActionSpec/MCP alignment and CLI/harness policy coverage, then rerun E0017 and decide adoption.

## 回帰ガード

harnessops-core:tests/test_safety_matrix.py::test_generated_matrix_flags_split_confirmation_policy_drift
