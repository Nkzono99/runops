<!-- harnessops により生成; source records が正本 -->
# 手動評価結果: E0006

送信元: `harness-lab/records/eval-cases/E0006-fb0006-paper-draft-runops-research-agenda-contract.md`

## スコア

- impact: 3
- mechanism_clarity: 5
- evaluability: 5
- minimality: 4
- regression_risk: 2
- operator_burden: 4
- anti_theater: 5
- maintainability: 4
- privacy_sanitization_risk: 5

## メモ

Implemented the paper request contract with docs, schema, scaffold template, and read/plan MCP tools: runops.paper.requests.list and runops.paper.request.plan. The tools do not mutate files or submit jobs. Validation passed: ruff check src/ tests/, mypy src/, pytest, pytest --cov=runops --cov-branch --cov-report=term-missing --cov-fail-under=80, and runo mcp check.

## 評価ケース

- capability: unclassified
- failure_class: unclassified
- source_feedback: FB0006
