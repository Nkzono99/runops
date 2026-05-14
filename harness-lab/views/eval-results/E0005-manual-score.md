<!-- harnessops により生成; source records が正本 -->
# 手動評価結果: E0005

送信元: `harness-lab/records/eval-cases/E0005-fb0005-mcp-analysis-artifacts-survey-summary-paper-inspect.md`

## スコア

- impact: 4
- mechanism_clarity: 5
- evaluability: 5
- minimality: 4
- regression_risk: 2
- operator_burden: 4
- anti_theater: 5
- maintainability: 4
- privacy_sanitization_risk: 5

## メモ

Implemented read-only MCP analysis tools: runops.analysis.artifacts, runops.survey.summary, and runops.analysis.plot_columns. They inspect existing artifacts/summary files and report missing data through envelopes without collecting or plotting. Validation passed: ruff check src/ tests/, mypy src/, pytest, pytest --cov=runops --cov-branch --cov-report=term-missing --cov-fail-under=80, and runo mcp check.

## 評価ケース

- capability: mcp_analysis_result_inspection
- failure_class: missing_paper_facing_analysis_artifact_inspect
- source_feedback: FB0005
