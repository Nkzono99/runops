---
id: FB0010
record_type: imported_feedback
created_at: '2026-05-17T04:07:31+09:00'
status: triaged
source:
  type: harness-feedback-export
  original_id: ISSUE-84
  source_project: redacted
  issue:
    provider: github
    repo: Nkzono99/runops
    number: 84
    url: https://github.com/Nkzono99/runops/issues/84
    title: hops github-flow pr で label 指定をサポートする
    author: Nkzono99
    labels:
    - enhancement
    - codex
    created_at: '2026-05-16T05:06:05Z'
    updated_at: '2026-05-16T05:06:05Z'
    comments: []
classification:
  failure_class: unclassified
  capability: unclassified
links:
  eval_case:
  issue_url: https://github.com/Nkzono99/runops/issues/84
---

# FB0010: hops github-flow pr で label 指定をサポートする

## 概要

GitHub issue: https://github.com/Nkzono99/runops/issues/84
author: Nkzono99
labels: enhancement, codex
created_at: 2026-05-16T05:06:05Z
updated_at: 2026-05-16T05:06:05Z

## Issue本文
## 背景

`hops github-flow pr` は daily steward / automation lane から PR を作る標準経路になっているが、現状は PR 作成時に label を付ける option がない。そのため automation では PR 作成後に別途 `gh pr edit --add-label ...` を呼ぶ必要があり、GitHub Flow を HOPS CLI に委譲する方針から少しはみ出る。

## 提案

`hops github-flow pr` に label 指定を追加する。

候補:

- `--label <name>` を複数回指定可能にする
- または `--labels "codex,enhancement"` をサポートする
- 既存 label がない場合の挙動を明確化する（失敗、warning、または作成しない）

## 受け入れ基準

- `hops github-flow pr --label codex --label enhancement ...` のように PR 作成と同時に label を付けられる。
- PR 作成後の別 `gh pr edit --add-label` 呼び出しが不要になる。
- label 付与に失敗した場合、PR URL と失敗理由が分かる形で返る。
- `--json` output に label 付与結果が含まれる。
- 既存の PR 作成挙動と後方互換性がある。

## 補足

2026-05-16 の runops harness update PR 作成時、`hops github-flow pr` 後に手動で `gh pr edit 83 --add-label codex` を実行した。

## 再現

送信元フィードバックバンドルを参照してください。

## 期待する上流変更

送信元フィードバックバンドルを参照してください。
