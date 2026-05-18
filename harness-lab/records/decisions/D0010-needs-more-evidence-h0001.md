---
id: D0010
record_type: decision
created_at: '2026-05-19T04:23:21+09:00'
status: needs-more-evidence
source: H0001
evidence:
  summary: 'E0001 manual score plus IMP0001/RS0001 evidence: non-issue runops harness improvements and the current paired Codex/Claude skill diff both required explicit capture and drift review.'
  guard_path: harnessops-core:tests/test_skills/test_improve_harness.py::test_target_bridge_suggests_lab_capture_for_paired_harness_drift
---

# D0010: needs-more-evidence H0001

## 判断

needs-more-evidence

## 理由

The cross-target mechanism and target-lab evidence are clear, but this lane only produced evaluation evidence; no HarnessOps core improve-harness workflow or passing guard has been recorded yet.

## 証拠

E0001 manual score plus IMP0001/RS0001 evidence: non-issue runops harness improvements and the current paired Codex/Claude skill diff both required explicit capture and drift review.

## 回帰リスク

Medium if the upstream workflow becomes noisy or rewrites target-specific harness judgment; keep the HOPS workflow as a capture/drift gate with explicit target bridge boundaries.

## フォローアップ

Implement the HarnessOps core improve-harness workflow or update-harness/bridge guard for generated-view conflict warnings and paired Codex/Claude skill divergence, run the guard, then reconsider adoption.

## 回帰ガード

harnessops-core:tests/test_skills/test_improve_harness.py::test_target_bridge_suggests_lab_capture_for_paired_harness_drift
