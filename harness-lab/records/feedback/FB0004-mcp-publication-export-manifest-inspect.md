---
id: FB0004
record_type: imported_feedback
created_at: '2026-05-14T11:14:06+09:00'
status: triaged
source:
  type: harness-feedback-export
  original_id: ISSUE-67
  source_project: redacted
  issue:
    provider: github
    repo: Nkzono99/runops
    number: 67
    url: https://github.com/Nkzono99/runops/issues/67
    title: MCP から publication export 一覧と manifest を inspect できるようにする
    author: Nkzono99
    labels: []
    created_at: '2026-05-14T01:53:06Z'
    updated_at: '2026-05-14T01:53:06Z'
    comments: []
classification:
  failure_class: missing_publication_export_manifest_inspect
  capability: mcp_publication_export_inspection
links:
  eval_case:
  issue_url: https://github.com/Nkzono99/runops/issues/67
disposition:
  type: protocol-candidate
  target:
  status: draft
---

# FB0004: MCP から publication export 一覧と manifest を inspect できるようにする

## 概要

GitHub issue: https://github.com/Nkzono99/runops/issues/67
author: Nkzono99
labels: なし
created_at: 2026-05-14T01:53:06Z
updated_at: 2026-05-14T01:53:06Z

## Issue本文
## 背景

paperops の paper draft link registry から runops project を参照し、論文に使う export bundle を discovery / inspect したい。runops には `runo analyze export <run-or-survey> --paper <paper-id>` と `exports/papers/<paper-id>/<export-name>/manifest.json` が既にあるため、MCP 側では既存成果物を read/inspect する薄い入口が欲しい。

## 提案

- `runops.publication.exports.list` を追加する。
  - 入力: `project_root`, optional `paper_id`, optional `limit`
  - 出力: export id, paper id, export name, target kind, source run ids, created_at, manifest path, README path, warning count
- `runops.publication.export.inspect` を追加する。
  - 入力: `project_root`, `export` または `paper_id` + `name`
  - 出力: `manifest.json` の要約、files[], source metadata, warnings
- safety は read/inspect。file mutation は行わない。
- `runo mcp tools --json`, `runo mcp check`, tests を更新する。

## paperops からの利用イメージ

paper draft 側は `refs/links.toml` の `kind = "runops_project"` link を解決し、MCP 経由で利用可能な export を列挙する。論文側に取り込む証拠は export manifest / files の参照に寄せる。

## 受け入れ基準

- export が無い project でも空配列で成功する。
- `paper_id` filter が効く。
- 壊れた manifest は warnings/errors として envelope に表現し、MCP protocol error にしない。
- docs/mcp.md に tool が追記される。

## 再現

送信元フィードバックバンドルを参照してください。

## 期待する上流変更

送信元フィードバックバンドルを参照してください。
