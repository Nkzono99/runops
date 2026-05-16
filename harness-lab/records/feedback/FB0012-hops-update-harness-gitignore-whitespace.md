---
id: FB0012
record_type: imported_feedback
created_at: '2026-05-17T04:07:52+09:00'
status: triaged
source:
  type: harness-feedback-export
  original_id: ISSUE-86
  source_project: redacted
  issue:
    provider: github
    repo: Nkzono99/runops
    number: 86
    url: https://github.com/Nkzono99/runops/issues/86
    title: hops update-harness で .gitignore の改行/whitespace 差分を抑える
    author: Nkzono99
    labels:
    - enhancement
    - codex
    created_at: '2026-05-16T05:07:29Z'
    updated_at: '2026-05-16T05:07:29Z'
    comments: []
classification:
  failure_class: unclassified
  capability: unclassified
links:
  eval_case:
  issue_url: https://github.com/Nkzono99/runops/issues/86
---

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
