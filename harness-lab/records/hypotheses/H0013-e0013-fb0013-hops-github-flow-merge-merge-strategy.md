---
id: H0013
record_type: hypothesis
created_at: '2026-05-17T04:10:47+09:00'
status: proposed
target_capability: unclassified
source_eval_case: E0013
---

# H0013: E0013-fb0013-hops-github-flow-merge-merge-strategy の仮説

## 仮説

A merge strategy option for hops github-flow merge will align automated merges with repository policy without bypassing HOPS.

## メカニズム

Accept an explicit merge, squash, or rebase strategy, map it to the corresponding gh pr merge flag, and report the actual strategy in JSON output.

## 最小実装

Add a validated strategy option with current merge behavior as default, wire it through merge execution, and test allowed, unsupported, and repo-disabled strategies.

## 代替案: 削除または統合

Keep only merge commits in HOPS and require manual gh pr merge calls for squash or rebase policies.

## 期待される利点

Automation can use repository-specific merge policy while preserving required-check and branch-deletion safeguards.

## 想定される欠点

Repos with disabled strategies may fail after checks pass, so errors must clearly identify the rejected strategy.

## 評価計画

Mock gh pr merge invocations for merge, squash, and rebase; assert command flags, JSON strategy fields, and failure messages.

## 中止基準

Reject if strategy support weakens required-check enforcement or changes the current default merge behavior.
