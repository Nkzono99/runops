---
id: FB0006
record_type: imported_feedback
created_at: '2026-05-14T11:14:14+09:00'
status: triaged
source:
  type: harness-feedback-export
  original_id: ISSUE-69
  source_project: redacted
  issue:
    provider: github
    repo: Nkzono99/runops
    number: 69
    url: https://github.com/Nkzono99/runops/issues/69
    title: paper draft からの追加解析・追加実験要望を runops research agenda に取り込む contract を設計する
    author: Nkzono99
    labels: []
    created_at: '2026-05-14T01:53:22Z'
    updated_at: '2026-05-14T01:53:22Z'
    comments: []
classification:
  failure_class: unclassified
  capability: unclassified
links:
  eval_case:
  issue_url: https://github.com/Nkzono99/runops/issues/69
---

# FB0006: paper draft からの追加解析・追加実験要望を runops research agenda に取り込む contract を設計する

## 概要

GitHub issue: https://github.com/Nkzono99/runops/issues/69
author: Nkzono99
labels: なし
created_at: 2026-05-14T01:53:22Z
updated_at: 2026-05-14T01:53:22Z

## Issue本文
## 背景

paperops の執筆中に、結果セクションや図表設計から「この追加解析が必要」「この条件の run を追加したい」「この export は placeholder 扱い」などの需要が出る。これを runops project 側の research agenda / case / survey design に戻すための軽い contract が欲しい。

## 提案

- paper-facing request schema を設計する。
  - 例: `analysis_request`, `figure_request`, `experiment_request`, `evidence_gap`, `export_request`
  - fields: id, title, paper_context, desired_artifact, source_link, related_runs/surveys, priority, status
- runops 側で import 先を決める。
  - 候補: `research/agenda.md`, `research/proposals/`, または structured TOML/JSONL
- MCP または CLI に read/plan entrypoint を追加するか検討する。
  - 初期は read/plan のみでよい。
  - 実際の run creation / survey expansion は既存 `create-run` / `setup-campaign` flow に委ねる。
- paperops の link registry から runops project link と request を対応づけられるようにする。

## 受け入れ基準

- request schema の docs と例がある。
- paperops 側の `refs/links.toml` / notes から参照できる stable id を持つ。
- runops project 内で未処理・処理中・完了を追える。
- 追加実験の実行そのものは明示操作に残し、MCP 経由で勝手に submit しない。

## 再現

送信元フィードバックバンドルを参照してください。

## 期待する上流変更

送信元フィードバックバンドルを参照してください。
