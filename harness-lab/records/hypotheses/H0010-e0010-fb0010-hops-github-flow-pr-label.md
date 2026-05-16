---
id: H0010
record_type: hypothesis
created_at: '2026-05-17T04:09:59+09:00'
status: proposed
target_capability: unclassified
source_eval_case: E0010
---

# H0010: E0010-fb0010-hops-github-flow-pr-label の仮説

## 仮説

Adding repeatable label options to hops github-flow pr will keep automation PR creation delegated to HOPS while preserving current behavior.

## メカニズム

Parse zero or more labels in the pr command, apply them during or immediately after PR creation, and include structured label results in JSON output.

## 最小実装

Add label options, wire them into the GitHub Flow PR helper, report label success or failure, and test labeled plus unlabeled PR paths.

## 代替案: 削除または統合

Continue calling gh pr edit after hops github-flow pr, which keeps label handling outside the delegated HOPS path.

## 期待される利点

Automation finalization can create labeled PRs through one HOPS command and produce clearer machine-readable reports.

## 想定される欠点

Label application may fail after PR creation, so output must preserve the PR URL and exact label failure.

## 評価計画

Use a mocked gh fixture for PR creation with multiple labels, missing labels, and no labels; assert JSON includes label results without breaking existing output.

## 中止基準

Reject if label support requires direct gh calls in lane scripts or changes current unlabeled PR behavior.
