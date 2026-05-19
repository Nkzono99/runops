---
id: D0014
record_type: decision
created_at: '2026-05-20T04:25:55+09:00'
status: needs-more-evidence
source: H0014
evidence:
  summary: E0014 manual score; RS0002/IMP0009 consolidation context; supervisor run 20260520-040215-980747f
  guard_path: harnessops-core:tests/test_cli/test_github_flow.py::test_merge_json_includes_post_merge_state
---

# D0014: needs-more-evidence H0014

## 判断

needs-more-evidence

## 理由

Strong upstream candidate, but needs core code and guard evidence for post-merge state and lookup-failure handling.

## 証拠

E0014 manual score; RS0002/IMP0009 consolidation context; supervisor run 20260520-040215-980747f

## 回帰リスク

Low-to-medium: post-merge lookup can fail after a successful merge, so output must preserve merge success and report lookup failure separately.

## フォローアップ

Extend HarnessOps merge JSON with merged/post_merge_pr/mergeCommit/deletedBranch/checks summary fields and guard compatibility with existing JSON.

## 回帰ガード

harnessops-core:tests/test_cli/test_github_flow.py::test_merge_json_includes_post_merge_state
