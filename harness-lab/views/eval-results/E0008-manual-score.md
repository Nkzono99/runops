<!-- harnessops により生成; source records が正本 -->
# 手動評価結果: E0008

送信元: `harness-lab/records/eval-cases/E0008-fb0008-paper-request-draft-duplicate-id-append.md`

## スコア

- impact: 3
- mechanism_clarity: 5
- evaluability: 5
- minimality: 5
- regression_risk: 1
- operator_burden: 5
- anti_theater: 5
- maintainability: 4
- privacy_sanitization_risk: 5

## メモ

Changed runops.paper.request.draft so duplicate request_id is no longer appendable: duplicate id is reported as paper_request_duplicate_id error, data.valid=false, toml_snippet is empty, append next_actions are omitted, and suggested_request_id points to the next non-colliding id. Updated docs and tests. Validation passed: ruff format --check src/ tests/, ruff check src/ tests/, mypy src/, pytest -q, runo mcp check, and hops doctor --check-overlay --check-records.

## 評価ケース

- capability: unclassified
- failure_class: unclassified
- source_feedback: FB0008
