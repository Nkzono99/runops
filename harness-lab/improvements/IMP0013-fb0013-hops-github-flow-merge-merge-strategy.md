---
id: IMP0013
record_type: improvement_dossier
created_at: '2026-05-17T04:12:53+09:00'
updated_at: '2026-05-17T04:12:53+09:00'
status: active
source_type: observation
scope: harnessops-core
maturity: hypothesis
relation: new
promotion_level: target-lab-case
source_feedback: FB0013
eval_cases:
- E0013
hypotheses:
- H0013
decisions: []
research_scans: []
classification:
  capability: unclassified
  failure_class: unclassified
guard:
  status: not-defined
  path:
investigation: []
links:
  issue_url: https://github.com/Nkzono99/runops/issues/87
---

# IMP0013: FB0013: hops github-flow merge で merge strategy を指定できるようにする

## Status

- status: active
- maturity: hypothesis
- source_type: observation
- scope: harnessops-core
- relation: new
- promotion_level: target-lab-case
- source_feedback: `FB0013`
- linked_records: `FB0013`, `E0013`, `H0013`

## Source Observation

Source: `harness-lab/records/feedback/FB0013-hops-github-flow-merge-merge-strategy.md`

# FB0013: hops github-flow merge で merge strategy を指定できるようにする

## 概要

GitHub issue: https://github.com/Nkzono99/runops/issues/87
author: Nkzono99
labels: enhancement, codex
created_at: 2026-05-16T05:07:29Z
updated_at: 2026-05-16T05:07:29Z

## Issue本文
## 背景

`hops github-flow merge` は現在 `gh pr merge --merge` を実行しており、merge strategy を呼び出し側から選べない。runops の automation では PR #82 を手動 `gh pr merge --squash` 相当で処理した一方、PR #83 は HOPS 経由で merge commit になった。

repository policy や automation lane ごとに squash / merge commit / rebase の方針が違う場合、HOPS 側で strategy を明示できる必要がある。

## 提案

`hops github-flow merge` に merge strategy 指定を追加する。

候補:

- `--strategy merge|squash|rebase`
- または `--merge`, `--squash`, `--rebase` の排他 option
- `.harnessops/project.toml` の `[github_flow]` に既定 strategy を持てるようにする

## 受け入れ基準

- `hops github-flow merge <PR> --strategy squash` で squash merge できる。
- `--strategy merge` は現行挙動と互換。
- unsupported strategy や repo 側で無効な strategy は明確なエラーになる。
- `--json` output に実際に使った strategy が含まれる。
- required checks / branch deletion の挙動は既存と整合する。

## 再現メモ

2026-05-16 の runops PR #83 では `hops github-flow merge` が `gh pr merge --merge --delete-branch` を実行し、merge commit `4e52609` が作られた。呼び出し側から squash を選ぶ option は見当たらなかった。

## 再現

送信元フィードバックバンドルを参照してください。

## 期待する上流変更

送信元フィードバックバンドルを参照してください。

## Target Capability

- capability: unclassified
- failure_class: unclassified

## Investigation

調査メモはまだありません。

## Research Scans

research scan はまだありません。


## Evaluation

### E0013: E0013: FB0013-hops-github-flow-merge-merge-strategy を評価


- source: `harness-lab/records/eval-cases/E0013-fb0013-hops-github-flow-merge-merge-strategy.md`

- capability: unclassified

- failure_class: unclassified

- manual_eval: 未実施


## Hypotheses

### H0013: H0013: E0013-fb0013-hops-github-flow-merge-merge-strategy の仮説


Source: `harness-lab/records/hypotheses/H0013-e0013-fb0013-hops-github-flow-merge-merge-strategy.md`


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


## Evidence

評価結果はまだありません。

## Guard

- status: not-defined
- path: None

## Links

- issue_url: https://github.com/Nkzono99/runops/issues/87

## Open Questions And Next Action

次の実装または評価ステップは、この dossier と紐づく正規化レコードを更新してから再生成してください。

## Decision Log

判断レコードはまだありません。
