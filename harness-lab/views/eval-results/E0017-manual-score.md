<!-- harnessops により生成; source records が正本 -->
# 手動評価結果: E0017

送信元: `harness-lab/records/eval-cases/E0017-rs0006-unified-safety-matrix-for-cli-actionspec-mcp-and-harness-gates.md`

## スコア

- impact: 4
- mechanism_clarity: 4
- evaluability: 4
- minimality: 4
- regression_risk: 3
- operator_burden: 3
- anti_theater: 5
- maintainability: 4
- privacy_sanitization_risk: 4

## メモ

RS0006 and priority review show a plausible drift class across docs/agent-user-guide.md --yes guidance, ActionSpec risk/confirmation metadata, MCP registry safety checks, and .codex/rules/runops.rules command policy. Current runops already has a partial guard in runo mcp check: mutating tools are disabled by default, MCP safety metadata is present, ActionSpec MCP tools are registered, and unsafe action MCP tools require confirmation. The missing piece is a generated or linted cross-surface safety matrix that includes CLI/harness policy alongside ActionSpec and MCP data. Keep it read-only and source-derived; do not add another manually maintained narrative safety page.

## 評価ケース

- capability: safety_contract_matrix
- failure_class: split_confirmation_policy_drift
- source_feedback: RS0006
