<!-- harnessops により生成; source records が正本 -->
# 手動評価結果: E0007

送信元: `harness-lab/records/eval-cases/E0007-fb0007-paper-request-draft-validate-mcp-paperops-handoff.md`

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

Implemented runops.paper.request.draft as a plan-only MCP tool. It normalizes paper request candidates, generates a non-colliding request id, validates required fields and type/priority/status enums, warns on duplicate ids, returns target path and TOML snippet, and never mutates files or submits jobs. Tests cover empty queue, existing queue, duplicate id, invalid type/status/priority, server wiring, and MCP conformance. Validation passed: ruff format --check src/ tests/, ruff check src/ tests/, mypy src/, pytest -q, runo mcp check, and hops doctor --check-overlay --check-records.

## 評価ケース

- capability: unclassified
- failure_class: unclassified
- source_feedback: FB0007
