<!-- harnessops により生成; source records が正本 -->
# 手動評価結果: E0004

送信元: `harness-lab/records/eval-cases/E0004-fb0004-mcp-publication-export-manifest-inspect.md`

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

Implemented read-only MCP publication export tools: runops.publication.exports.list and runops.publication.export.inspect. Validation passed: ruff check src/ tests/, mypy src/, pytest, pytest --cov=runops --cov-branch --cov-report=term-missing --cov-fail-under=80, and runo mcp check.

## 評価ケース

- capability: mcp_publication_export_inspection
- failure_class: missing_publication_export_manifest_inspect
- source_feedback: FB0004
