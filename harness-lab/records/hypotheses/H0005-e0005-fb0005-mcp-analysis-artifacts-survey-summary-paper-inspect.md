---
id: H0005
record_type: hypothesis
created_at: '2026-05-15T04:09:30+09:00'
status: proposed
target_capability: mcp_analysis_result_inspection
source_eval_case: E0005
---

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
