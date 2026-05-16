---
id: H0011
record_type: hypothesis
created_at: '2026-05-17T04:10:20+09:00'
status: proposed
target_capability: unclassified
source_eval_case: E0011
---

# H0011: E0011-fb0011-hops-github-flow-pr-view-checks-watch の仮説

## 仮説

Adding HOPS PR view and checks commands will let automation lanes inspect PR state without direct gh calls.

## メカニズム

Expose github-flow view and checks subcommands that wrap gh pr view/checks, normalize required-check states, and support JSON and watch modes.

## 最小実装

Add view and checks commands, reuse existing merge check logic, implement timeout-aware watch output, and test pending, failed, passed, missing, and skipped states.

## 代替案: 削除または統合

Keep lane scripts calling gh pr view and gh pr checks directly, which duplicates GitHub behavior outside HOPS.

## 期待される利点

Finalization lanes can rely on one delegated interface for publish, PR creation, status checks, and merge decisions.

## 想定される欠点

Watch behavior can hang or hide API errors unless timeouts and next-step commands are explicit.

## 評価計画

Use mocked gh outputs for PR metadata and check states, then verify JSON fields and watch exit behavior match merge --require-checks semantics.

## 中止基準

Reject if the commands produce ambiguous check states or require repo-specific lane code to interpret raw gh output.
