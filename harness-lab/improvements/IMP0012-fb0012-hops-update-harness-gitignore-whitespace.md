---
id: IMP0012
record_type: improvement_dossier
created_at: '2026-05-17T04:12:44+09:00'
updated_at: '2026-05-17T04:12:44+09:00'
status: active
source_type: observation
scope: harnessops-core
maturity: hypothesis
relation: new
promotion_level: target-lab-case
source_feedback: FB0012
eval_cases:
- E0012
hypotheses:
- H0012
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
  issue_url: https://github.com/Nkzono99/runops/issues/86
---

# IMP0012: FB0012: hops update-harness で .gitignore の改行/whitespace 差分を抑える

## Status

- status: active
- maturity: hypothesis
- source_type: observation
- scope: harnessops-core
- relation: new
- promotion_level: target-lab-case
- source_feedback: `FB0012`
- linked_records: `FB0012`, `E0012`, `H0012`

## Source Observation

Source: `harness-lab/records/feedback/FB0012-hops-update-harness-gitignore-whitespace.md`

# FB0012: hops update-harness で .gitignore の改行/whitespace 差分を抑える

## 概要

GitHub issue: https://github.com/Nkzono99/runops/issues/86
author: Nkzono99
labels: enhancement, codex
created_at: 2026-05-16T05:07:29Z
updated_at: 2026-05-16T05:07:29Z

## Issue本文
## 背景

`hops update-harness` 実行後、`.gitignore` に内容上の大きな変更がないにもかかわらず、改行差分だけで 450 行規模の diff が出た。さらに `git diff --check` で Visual Studio Code コメント行の trailing whitespace が検出され、手動で 2 行だけ trim する必要があった。

HarnessOps managed artifact 更新で `.gitignore` のような既存ファイルを触る場合、無意味な line-ending churn や whitespace noise は review コストを増やし、本質的な skill/lock 更新が見えにくくなる。

## 提案

`hops update-harness` が既存ファイルを更新するとき、以下を守る。

- 既存ファイルの改行スタイルを保持する、または内容差分がない場合は書き換えない
- managed template 側の trailing whitespace を出力しない
- update 後に `git diff --check` 相当の whitespace 問題を検出できるようにする

## 受け入れ基準

- `.gitignore` の内容が変わらない場合、line-ending だけの巨大 diff が出ない。
- `hops update-harness` 後に generated/managed files 由来の trailing whitespace が出ない。
- `.gitignore` のような既存ユーザー管理ファイルは、必要最小限の実差分だけになる。
- 可能なら update summary に「line ending preserved」または「unchanged due to normalized content match」が分かる情報が出る。

## 再現メモ

2026-05-16 に runops で `uvx --refresh-package harnessops --from harnessops hops update-harness` を実行したところ、`.gitignore` がほぼ CRLF/LF 由来の 450 行 diff になり、`git diff --check` が trailing whitespace を報告した。

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

### E0012: E0012: FB0012-hops-update-harness-gitignore-whitespace を評価


- source: `harness-lab/records/eval-cases/E0012-fb0012-hops-update-harness-gitignore-whitespace.md`

- capability: unclassified

- failure_class: unclassified

- manual_eval: 未実施


## Hypotheses

### H0012: H0012: E0012-fb0012-hops-update-harness-gitignore-whitespace の仮説


Source: `harness-lab/records/hypotheses/H0012-e0012-fb0012-hops-update-harness-gitignore-whitespace.md`


# H0012: E0012-fb0012-hops-update-harness-gitignore-whitespace の仮説

## 仮説

Preserving existing file line endings and skipping normalized no-op writes will remove update-harness whitespace churn.

## メカニズム

Compare managed output against existing files after normalization, preserve detected newline style when writing, and trim template trailing whitespace before emission.

## 最小実装

Add normalized content comparison and newline-style preservation to update-harness writes, surface unchanged status in summaries, and run diff-check validation in tests.

## 代替案: 削除または統合

Accept line-ending-only diffs and rely on humans to trim whitespace, which obscures real managed artifact changes.

## 期待される利点

Harness updates become smaller, easier to review, and less likely to fail git diff --check for generated artifacts.

## 想定される欠点

Normalization rules must not hide intentional whitespace-sensitive changes in managed files.

## 評価計画

Create fixtures with LF and CRLF .gitignore files plus template trailing spaces; assert no diff on equivalent content and no diff-check violations after update.

## 中止基準

Reject if the writer silently rewrites user-managed files or suppresses real content differences.


## Evidence

評価結果はまだありません。

## Guard

- status: not-defined
- path: None

## Links

- issue_url: https://github.com/Nkzono99/runops/issues/86

## Open Questions And Next Action

次の実装または評価ステップは、この dossier と紐づく正規化レコードを更新してから再生成してください。

## Decision Log

判断レコードはまだありません。
