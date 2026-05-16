---
id: H0014
record_type: hypothesis
created_at: '2026-05-17T04:11:00+09:00'
status: proposed
target_capability: unclassified
source_eval_case: E0014
---

# H0014: E0014-fb0014-hops-github-flow-merge-json-post-merge の仮説

## 仮説

Returning post-merge PR state from hops github-flow merge --json will eliminate extra gh pr view calls after a successful merge.

## メカニズム

After merge succeeds, fetch or derive the merged PR state, merge commit, branch deletion result, and checks summary, separating pre-merge and post-merge fields when needed.

## 最小実装

Extend merge JSON output with merged, post_merge_pr, mergeCommit, deletedBranch, and checks summary fields while preserving existing fields for compatibility.

## 代替案: 削除または統合

Leave merge JSON as a pre-merge snapshot and require automation lanes to call gh pr view after every merge.

## 期待される利点

Final reports can be generated directly from HOPS merge output with less duplicated GitHub inspection logic.

## 想定される欠点

A second PR fetch may fail after merge; output needs to preserve merge success while reporting post-merge lookup failure separately.

## 評価計画

Use mocked merge and post-merge view outputs to assert state MERGED, merge commit SHA, branch deletion status, and compatibility with existing JSON fields.

## 中止基準

Reject if successful merges can be reported as open without an explicit pre_merge field, or if post-merge lookup failure masks merge success.
