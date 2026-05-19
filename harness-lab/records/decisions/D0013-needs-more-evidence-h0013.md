---
id: D0013
record_type: decision
created_at: '2026-05-20T04:25:52+09:00'
status: needs-more-evidence
source: H0013
evidence:
  summary: E0013 manual score; RS0002/IMP0009 consolidation context; supervisor run 20260520-040215-980747f
  guard_path: harnessops-core:tests/test_cli/test_github_flow.py::test_merge_strategy_maps_to_gh_flags_and_json
---

# D0013: needs-more-evidence H0013

## 判断

needs-more-evidence

## 理由

Mechanism and guard path are clear, but upstream HOPS implementation and strategy failure reporting are still missing.

## 証拠

E0013 manual score; RS0002/IMP0009 consolidation context; supervisor run 20260520-040215-980747f

## 回帰リスク

Medium: a repo-disabled strategy can fail after checks pass, and the default merge behavior must remain compatible.

## フォローアップ

Add a validated merge strategy option in HarnessOps, map it to gh pr merge flags, include strategy in JSON, and test default/merge/squash/rebase/failure paths.

## 回帰ガード

harnessops-core:tests/test_cli/test_github_flow.py::test_merge_strategy_maps_to_gh_flags_and_json
