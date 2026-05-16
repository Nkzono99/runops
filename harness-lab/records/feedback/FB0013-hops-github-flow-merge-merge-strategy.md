---
id: FB0013
record_type: imported_feedback
created_at: '2026-05-17T04:08:03+09:00'
status: triaged
source:
  type: harness-feedback-export
  original_id: ISSUE-87
  source_project: redacted
  issue:
    provider: github
    repo: Nkzono99/runops
    number: 87
    url: https://github.com/Nkzono99/runops/issues/87
    title: hops github-flow merge で merge strategy を指定できるようにする
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
  issue_url: https://github.com/Nkzono99/runops/issues/87
---

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
