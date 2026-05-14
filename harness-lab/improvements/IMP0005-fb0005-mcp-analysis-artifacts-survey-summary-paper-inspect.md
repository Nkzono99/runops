---
id: IMP0005
record_type: improvement_dossier
created_at: '2026-05-15T04:09:19+09:00'
updated_at: '2026-05-15T04:12:05+09:00'
status: adopted
source_type: local-implementation
scope: runops-target
maturity: adopted
relation: new
promotion_level: target-feature
source_feedback: FB0005
eval_cases:
- E0005
hypotheses:
- H0005
decisions:
- D0004
research_scans: []
classification:
  capability: mcp_analysis_result_inspection
  failure_class: missing_paper_facing_analysis_artifact_inspect
guard:
  status: implemented
  path: tests/test_mcp/test_tools.py::test_survey_summary_and_plot_columns_read_existing_summary; tests/test_mcp/test_server.py
investigation:
- created_at: '2026-05-15T04:09:19+09:00'
  kind: implementation-sync
  summary: 'PR #72 implemented read-only MCP analysis inspection for FB0005: runops.analysis.artifacts, runops.survey.summary, and runops.analysis.plot_columns inspect existing artifact and summary files, apply limits, and report missing data through envelope warnings without generating analysis outputs.'
  evidence_ref: 'PR #72; issue #68; src/runops/mcp/tools.py; src/runops/mcp/server.py; docs/mcp.md; tests/test_mcp/test_tools.py::test_survey_summary_and_plot_columns_read_existing_summary; tests/test_mcp/test_server.py'
links:
  issue_url: https://github.com/Nkzono99/runops/issues/68
---

# IMP0005: FB0005: MCP から analysis artifacts / survey summary を paper 向けに inspect できるようにする

## Status

- status: adopted
- maturity: adopted
- source_type: local-implementation
- scope: runops-target
- relation: new
- promotion_level: target-feature
- source_feedback: `FB0005`
- linked_records: `FB0005`, `E0005`, `H0005`, `D0004`

## Source Observation

Source: `harness-lab/records/feedback/FB0005-mcp-analysis-artifacts-survey-summary-paper-inspect.md`

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

## Target Capability

- capability: mcp_analysis_result_inspection
- failure_class: missing_paper_facing_analysis_artifact_inspect

## Investigation

- 2026-05-15T04:09:19+09:00 [implementation-sync] PR #72 implemented read-only MCP analysis inspection for FB0005: runops.analysis.artifacts, runops.survey.summary, and runops.analysis.plot_columns inspect existing artifact and summary files, apply limits, and report missing data through envelope warnings without generating analysis outputs. (evidence: PR #72; issue #68; src/runops/mcp/tools.py; src/runops/mcp/server.py; docs/mcp.md; tests/test_mcp/test_tools.py::test_survey_summary_and_plot_columns_read_existing_summary; tests/test_mcp/test_server.py)

## Research Scans

research scan はまだありません。


## Evaluation

### E0005: E0005: FB0005-mcp-analysis-artifacts-survey-summary-paper-inspect を評価


- source: `harness-lab/records/eval-cases/E0005-fb0005-mcp-analysis-artifacts-survey-summary-paper-inspect.md`

- capability: mcp_analysis_result_inspection

- failure_class: missing_paper_facing_analysis_artifact_inspect

- manual_eval_yml: `harness-lab/views/eval-results/E0005-manual-score.yml`
- manual_eval_md: `harness-lab/views/eval-results/E0005-manual-score.md`
- scores: impact=4, mechanism_clarity=5, evaluability=5, minimality=4, regression_risk=2, operator_burden=4, anti_theater=5, maintainability=4, privacy_sanitization_risk=5
- notes: Implemented read-only MCP analysis tools: runops.analysis.artifacts, runops.survey.summary, and runops.analysis.plot_columns. They inspect existing artifacts/summary files and report missing data through envelopes without collecting or plotting. Validation passed: ruff check src/ tests/, mypy src/, pytest, pytest --cov=runops --cov-branch --cov-report=term-missing --cov-fail-under=80, and runo mcp check.


## Hypotheses

### H0005: H0005: E0005-fb0005-mcp-analysis-artifacts-survey-summary-paper-inspect の仮説


Source: `harness-lab/records/hypotheses/H0005-e0005-fb0005-mcp-analysis-artifacts-survey-summary-paper-inspect.md`


# H0005: E0005-fb0005-mcp-analysis-artifacts-survey-summary-paper-inspect の仮説

## 仮説

The implemented read-only MCP analysis tools resolve FB0005 by exposing existing analysis artifacts, survey summaries, and plot columns to paper-facing hosts without collecting or plotting new outputs.

## メカニズム

The MCP layer reads analysis/artifacts.toml or summary/artifacts.toml, summary/survey_summary.json, and aggregate columns into structured envelopes; missing files and clipped results are represented as warnings instead of filesystem mutation.

## 最小実装

Use the PR #72 implementation for runops.analysis.artifacts, runops.survey.summary, runops.analysis.plot_columns, registry/server entries, docs/mcp.md, and MCP tests.

## 代替案: 削除または統合

Keep figure/table discovery in CLI-only or ad hoc file inspection workflows, which would force paper-facing hosts to duplicate runops artifact parsing.

## 期待される利点

Paper-facing agents can inspect figure, table, metric, and survey summary candidates safely before requesting curated exports.

## 想定される欠点

The MCP read model must stay aligned with analysis artifact and survey summary file formats.

## 評価計画

Use E0005 manual score plus tests for run/survey artifact reads, missing summary warnings, limit clipping, server registration, runo mcp tools --json, and runo mcp check.

## 中止基準

Reopen if these tools generate artifacts, mutate project files, ignore limits, or return missing data as MCP protocol errors.


## Evidence

`harness-lab/views/eval-results/E0005-manual-score.md`

## Guard

- status: implemented
- path: tests/test_mcp/test_tools.py::test_survey_summary_and_plot_columns_read_existing_summary; tests/test_mcp/test_server.py

## Links

- issue_url: https://github.com/Nkzono99/runops/issues/68

## Open Questions And Next Action

次の実装または評価ステップは、この dossier と紐づく正規化レコードを更新してから再生成してください。

## Decision Log

### D0004: D0004: adopted H0005


Source: `harness-lab/records/decisions/D0004-adopted-h0005.md`


# D0004: adopted H0005

## 判断

adopted

## 理由

PR #72 implemented the requested read-only analysis artifact and survey summary MCP tools and issue #68 is closed.

## 証拠

E0005 manual score records passed validation; code evidence in src/runops/mcp/tools.py and src/runops/mcp/server.py; docs/mcp.md documents the tools; tests/test_mcp/test_tools.py and tests/test_mcp/test_server.py cover the MCP read surfaces; GitHub issue #68 is closed after PR #72.

## 回帰リスク

Low to medium. The implementation is read-only, but it depends on analysis artifact and survey summary schema stability.

## フォローアップ

Keep MCP tests and runo mcp check as guards; update docs/tests when analysis artifact or survey summary formats change.

## 回帰ガード

tests/test_mcp/test_tools.py::test_survey_summary_and_plot_columns_read_existing_summary; tests/test_mcp/test_server.py
