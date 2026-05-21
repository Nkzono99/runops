---
id: H0017
record_type: hypothesis
created_at: '2026-05-22T04:16:32+09:00'
status: proposed
target_capability: safety_contract_matrix
source_eval_case: E0017
---

# H0017: E0017-rs0006-unified-safety-matrix-for-cli-actionspec-mcp-and-harness-gates の仮説

## 仮説

A generated or linted safety matrix can prevent drift between CLI --yes prompts, ActionSpec risk/confirmation metadata, MCP mutating-tool gates, and harness command policy by deriving rows from existing action metadata plus a small explicit harness-policy source instead of adding another narrative safety document.

## メカニズム

Collect ActionSpec risk, confirmation, cli_command, and mcp_tool fields; compare them against MCP registry safety checks and harness policy categories; fail or warn when a mutating/high-risk surface lacks a matching confirmation or disabled-by-default gate.

## 最小実装

Add a HOPS/runops-facing generated safety matrix or lint command that reads existing action metadata and reports mismatches; start with read-only reporting and no automatic policy edits.

## 代替案: 削除または統合

Keep scattered documentation in sync manually across agent guide, ActionSpec, MCP registry checks, and harness rules.

## 期待される利点

Makes confirmation policy drift visible before steward lanes or MCP exposure rely on inconsistent safety assumptions.

## 想定される欠点

May overfit to current metadata shape unless the matrix treats unknown surfaces as warnings and documents source ownership.

## 評価計画

Use E0017 to check whether the proposal detects or prevents split_confirmation_policy_drift without requiring private project context; validate with HOPS record checks and existing MCP check where available.

## 中止基準

Reject if the matrix becomes a second hand-maintained policy page, cannot be generated or linted from source metadata, or requires private project details to judge safety.
