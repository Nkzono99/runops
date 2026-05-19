---
id: D0012
record_type: decision
created_at: '2026-05-20T04:25:49+09:00'
status: needs-more-evidence
source: H0011
evidence:
  summary: E0011 manual score; RS0002/IMP0009 consolidation context; supervisor run 20260520-040215-980747f
  guard_path: harnessops-core:tests/test_cli/test_github_flow.py::test_checks_required_states_and_watch_json
---

# D0012: needs-more-evidence H0011

## 判断

needs-more-evidence

## 理由

Worth pursuing upstream, but it needs HarnessOps core implementation and mocked check-state guards before any issue can be closed.

## 証拠

E0011 manual score; RS0002/IMP0009 consolidation context; supervisor run 20260520-040215-980747f

## 回帰リスク

Medium: ambiguous pending/failed/missing/skipped check normalization could make automation merge decisions unsafe.

## フォローアップ

Implement github-flow view and checks/watch in HarnessOps, reuse merge required-check semantics, and guard pending, failed, passed, missing, skipped, and timeout JSON.

## 回帰ガード

harnessops-core:tests/test_cli/test_github_flow.py::test_checks_required_states_and_watch_json
