---
id: FB0005
record_type: imported_feedback
created_at: '2026-05-14T11:14:10+09:00'
status: triaged
source:
  type: harness-feedback-export
  original_id: ISSUE-68
  source_project: redacted
  issue:
    provider: github
    repo: Nkzono99/runops
    number: 68
    url: https://github.com/Nkzono99/runops/issues/68
    title: MCP から analysis artifacts / survey summary を paper 向けに inspect できるようにする
    author: Nkzono99
    labels: []
    created_at: '2026-05-14T01:53:14Z'
    updated_at: '2026-05-14T01:53:14Z'
    comments: []
classification:
  failure_class: missing_paper_facing_analysis_artifact_inspect
  capability: mcp_analysis_result_inspection
links:
  eval_case:
  issue_url: https://github.com/Nkzono99/runops/issues/68
disposition:
  type: target-upstream-candidate
  target:
  status: draft
---

# FB0005: MCP から analysis artifacts / survey summary を paper 向けに inspect できるようにする

## 概要

GitHub issue: https://github.com/Nkzono99/runops/issues/68
author: Nkzono99
labels: なし
created_at: 2026-05-14T01:53:14Z
updated_at: 2026-05-14T01:53:14Z

## Issue本文
## 背景

paperops の draft から runops project を link したとき、論文に使う図・表・metric 候補を探索したい。現状 CLI には `runo analyze collect`, `plot`, `export` があり、`analysis/artifacts.toml` や `summary/survey_summary.json` もあるが、MCP から paper-facing に探索する入口がまだない。

## 提案

- `runops.analysis.artifacts` を追加する。
  - 入力: `project_root`, `target` (run id / run dir / survey dir), optional `kind`, optional `limit`
  - 出力: artifacts.toml 由来の artifact rows、absolute/relative path、run_id、caption/title/status
- `runops.survey.summary` を追加する。
  - 入力: `project_root`, `survey`, optional `include_runs`, optional `limit`
  - 出力: `summary/survey_summary.json` の要約、state/readiness counts、numeric_stats、readiness_issues
- 可能なら `runops.analysis.plot_columns` も追加する。
  - `runo analyze plot --list-columns` 相当を structured data として返す。
- safety は read/inspect。collect/plot のような生成を伴う処理は初期 scope から外すか、別途 plan/write tool に分ける。

## paperops からの利用イメージ

paper draft 側で `refs/links.toml` の runops link を選び、MCP で図表候補を見て、必要なら runops 側で export bundle を作る。draft には生 path ではなく export manifest または curated artifact metadata を残す。

## 受け入れ基準

- run と survey の両方を扱える。
- missing artifacts / missing summaries は envelope の warnings に出る。
- large result は `limit` で抑制できる。
- docs/mcp.md と tests が更新される。

## 再現

送信元フィードバックバンドルを参照してください。

## 期待する上流変更

送信元フィードバックバンドルを参照してください。
