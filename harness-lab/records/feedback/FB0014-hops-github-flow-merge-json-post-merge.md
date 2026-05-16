---
id: FB0014
record_type: imported_feedback
created_at: '2026-05-17T04:08:13+09:00'
status: triaged
source:
  type: harness-feedback-export
  original_id: ISSUE-88
  source_project: redacted
  issue:
    provider: github
    repo: Nkzono99/runops
    number: 88
    url: https://github.com/Nkzono99/runops/issues/88
    title: hops github-flow merge --json が post-merge 状態を返すようにする
    author: Nkzono99
    labels:
    - enhancement
    - codex
    created_at: '2026-05-16T05:07:30Z'
    updated_at: '2026-05-16T05:07:30Z'
    comments: []
classification:
  failure_class: unclassified
  capability: unclassified
links:
  eval_case:
  issue_url: https://github.com/Nkzono99/runops/issues/88
---

# FB0014: hops github-flow merge --json が post-merge 状態を返すようにする

## 概要

GitHub issue: https://github.com/Nkzono99/runops/issues/88
author: Nkzono99
labels: enhancement, codex
created_at: 2026-05-16T05:07:30Z
updated_at: 2026-05-16T05:07:30Z

## Issue本文
## 背景

`hops github-flow merge --json` は PR merge 前の `gh pr view` 結果を `pr` field に入れて返しているため、実際には merge 済みでも JSON 上の `pr.state` が `OPEN` のまま残る。automation lane では merge 後に別途 `gh pr view --json state,mergedAt,mergeCommit` を呼んで確認する必要があった。

GitHub Flow を HOPS CLI に委譲するなら、merge command 自体の JSON が post-merge 状態を machine-readable に返す方が扱いやすい。

## 提案

`hops github-flow merge --json` の戻り値に、merge 後の PR 状態を含める。

候補 fields:

- `merged: true/false`
- `pr.number`, `pr.url`, `pr.state`
- `mergedAt`
- `mergeCommit.oid`
- `headRefName`, `baseRefName`
- `deletedBranch: true/false`
- `checksSummary`

## 受け入れ基準

- merge 成功後の JSON で `state=MERGED` または `merged=true` が確認できる。
- merge commit SHA が JSON から取得できる。
- branch deletion の成功/失敗が JSON から分かる。
- merge 前 snapshot と merge 後 state が混ざる場合は、field 名で区別される（例: `pre_merge_pr` / `post_merge_pr`）。
- automation が追加の `gh pr view` を呼ばずに final report を作れる。

## 再現メモ

runops PR #83 の merge 時、`hops github-flow merge 83 --require-checks --delete-branch --json` は merge 自体に成功したが、返却 JSON の `pr.state` は pre-merge の `OPEN` だった。

## 再現

送信元フィードバックバンドルを参照してください。

## 期待する上流変更

送信元フィードバックバンドルを参照してください。
