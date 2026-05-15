---
id: FB0007
record_type: imported_feedback
created_at: '2026-05-15T14:43:52+09:00'
status: triaged
source:
  type: harness-feedback-export
  original_id: ISSUE-75
  source_project: redacted
  issue:
    provider: github
    repo: Nkzono99/runops
    number: 75
    url: https://github.com/Nkzono99/runops/issues/75
    title: paper request の draft/validate MCP を追加して paperops handoff を安全化する
    author: Nkzono99
    labels:
    - enhancement
    created_at: '2026-05-15T04:02:03Z'
    updated_at: '2026-05-15T04:02:03Z'
    comments: []
classification:
  failure_class: unclassified
  capability: unclassified
links:
  eval_case:
  issue_url: https://github.com/Nkzono99/runops/issues/75
---

# FB0007: paper request の draft/validate MCP を追加して paperops handoff を安全化する

## 概要

GitHub issue: https://github.com/Nkzono99/runops/issues/75
author: Nkzono99
labels: enhancement
created_at: 2026-05-15T04:02:03Z
updated_at: 2026-05-15T04:02:03Z

## Issue本文
## 背景

paperops 側では `refs/links.toml` と `notes/research-requests.md` から runops project へ追加解析・図表・追加実験要望を戻す導線を作っている。runops #69 で `research/paper_requests.toml` と read/plan MCP は整ったが、paperops 側が request を作る時点では runops schema / enum / id 形式を複製する必要がある。

paperops から直接ファイルを書き換える前に、runops 側で candidate request を検証し、TOML snippet と保存先を返せる read/plan 系 entrypoint があると、schema drift と手作業ミスを減らせる。

## 提案

- MCP に paper request draft/validate 用の非破壊 tool を追加する。
  - 候補名: `runops.paper.request.draft` または `runops.paper.request.validate`
  - safety は `plan` または `read`。file mutation / run creation / job submit はしない。
- 入力例:
  - `paper_id`, `source_link`, `type`, `title`, `paper_context`, `desired_artifact`, `priority`, `related_runs`, `related_surveys`, `human_gate`
  - 任意で `request_id`。未指定なら既存 queue と衝突しない候補 id を返す。
- 出力例:
  - normalized request object
  - `research/paper_requests.toml` に追記できる TOML snippet
  - target path / existing queue status / duplicate id warnings
  - schema validation errors / enum mismatch warnings
- 既存 `runops.paper.requests.list` と `runops.paper.request.plan` は維持する。

## 受け入れ基準

- paperops が runops schema を再実装せずに request handoff の preview/validation を行える。
- empty queue、既存 queue、duplicate id、invalid type/status/priority のテストがある。
- MCP conformance で mutating/external/destructive tool として扱われない。
- docs に paperops からの handoff 手順が追記される。

## 再現

送信元フィードバックバンドルを参照してください。

## 期待する上流変更

送信元フィードバックバンドルを参照してください。
