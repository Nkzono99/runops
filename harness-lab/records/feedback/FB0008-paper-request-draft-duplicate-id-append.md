---
id: FB0008
record_type: imported_feedback
created_at: '2026-05-15T15:35:00+09:00'
status: triaged
source:
  type: harness-feedback-export
  original_id: ISSUE-77
  source_project: redacted
  issue:
    provider: github
    repo: Nkzono99/runops
    number: 77
    url: https://github.com/Nkzono99/runops/issues/77
    title: paper_request.draft で duplicate id を append 可能扱いにしない
    author: Nkzono99
    labels:
    - enhancement
    created_at: '2026-05-15T06:13:42Z'
    updated_at: '2026-05-15T06:13:42Z'
    comments: []
classification:
  failure_class: unclassified
  capability: unclassified
links:
  eval_case:
  issue_url: https://github.com/Nkzono99/runops/issues/77
---

# FB0008: paper_request.draft で duplicate id を append 可能扱いにしない

## 概要

GitHub issue: https://github.com/Nkzono99/runops/issues/77
author: Nkzono99
labels: enhancement
created_at: 2026-05-15T06:13:42Z
updated_at: 2026-05-15T06:13:42Z

## Issue本文
## 背景

`runops.paper.request.draft` は paperops から `research/paper_requests.toml` へ追記する前の preview / validation tool として使う想定です。現在、既存 queue と同じ `request_id` を渡した場合に duplicate warning は出ますが、`data.valid = true` のまま `toml_snippet` と `Append the TOML snippet...` next action が返ります。

## 再現

既存 queue に `PAPER-REQ-0001` がある状態で、同じ `request_id="PAPER-REQ-0001"` を指定して `runops.paper.request.draft` を呼ぶと、以下になります。

```text
status=warning
valid=True
duplicate=True
snippet=True
next_actions=[Append the TOML snippet to research/paper_requests.toml]
```

## 問題

この tool は「追記用 TOML snippet」を返すため、duplicate id のまま append 可能に見えると、paperops handoff で queue に重複 id を入れやすくなります。warning だけでは、下流 agent が `toml_snippet` と next action を優先してしまう可能性があります。

## 提案

- duplicate id を validation error にする、または少なくとも `valid=false` / `toml_snippet=""` / append next action なしにする。
- 代替 id 候補を返す場合は `suggested_request_id` などの別フィールドに出す。
- tests で duplicate id 時に snippet が返らないこと、append next action が出ないことを確認する。

## 受け入れ基準

- duplicate id の `paper_request_draft` 結果が、そのまま append してよいように見えない。
- MCP conformance と既存 paper request tests が通る。
- docs に duplicate id 時の扱いが明記される。

## 再現

送信元フィードバックバンドルを参照してください。

## 期待する上流変更

送信元フィードバックバンドルを参照してください。
