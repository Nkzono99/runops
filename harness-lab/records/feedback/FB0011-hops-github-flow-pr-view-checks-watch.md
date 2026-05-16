---
id: FB0011
record_type: imported_feedback
created_at: '2026-05-17T04:07:41+09:00'
status: triaged
source:
  type: harness-feedback-export
  original_id: ISSUE-85
  source_project: redacted
  issue:
    provider: github
    repo: Nkzono99/runops
    number: 85
    url: https://github.com/Nkzono99/runops/issues/85
    title: hops github-flow で PR view/checks/watch をサポートする
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
  issue_url: https://github.com/Nkzono99/runops/issues/85
---

# FB0011: hops github-flow で PR view/checks/watch をサポートする

## 概要

GitHub issue: https://github.com/Nkzono99/runops/issues/85
author: Nkzono99
labels: enhancement, codex
created_at: 2026-05-16T05:06:05Z
updated_at: 2026-05-16T05:06:05Z

## Issue本文
## 背景

`hops github-flow publish/pr/merge` は automation branch push、PR 作成、merge の標準経路になっている。一方で、merge 前の状態確認ではまだ `gh pr view`、`gh pr checks --watch`、`gh pr checks` を直接呼んでいる。

GitHub Flow を HOPS CLI に委譲するなら、PR 状態確認と required checks の watch/check も `hops github-flow` 配下で扱えると、automation lane が一貫する。

## 提案

`hops github-flow` に PR inspection/check commands を追加する。

候補:

- `hops github-flow view [PR] --json`
  - state, mergeable, mergeStateStatus, draft, base/head, labels, URL, checks summary を返す
- `hops github-flow checks [PR] --required --json`
  - required checks の pass/fail/pending を返す
- `hops github-flow checks [PR] --watch --interval 10`
  - CI 完了まで watch し、失敗または timeout を machine-readable に返す

## 受け入れ基準

- `gh pr view` と `gh pr checks` を automation script 側で直接呼ばずに、HOPS CLI 経由で PR 状態と checks を確認できる。
- `--json` output が lane result / steward finalization に取り込める形になっている。
- required checks が pending / failed / missing / skipped の場合を区別できる。
- `hops github-flow merge --require-checks` と整合する check 判定を使う。
- timeout または GitHub API/CLI failure 時に、PR URL と次の確認コマンドが分かる。

## 補足

2026-05-16 の runops harness update PR #83 では、HOPS の `pr` / `merge` は使えたが、merge 前の watch と view は `gh pr view` / `gh pr checks --watch` を直接実行した。

## 再現

送信元フィードバックバンドルを参照してください。

## 期待する上流変更

送信元フィードバックバンドルを参照してください。
