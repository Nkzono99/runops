---
id: E0017
record_type: eval_case
created_at: '2026-05-22T04:15:56+09:00'
status: active
capability: safety_contract_matrix
failure_class: split_confirmation_policy_drift
source_feedback: RS0006
---

# E0017: RS0006-unified-safety-matrix-for-cli-actionspec-mcp-and-harness-gates を評価

## フィクスチャ

- source_feedback: `harness-lab/records/research-scans/RS0006-unified-safety-matrix-for-cli-actionspec-mcp-and-harness-gates.md`
- fixture_dir: `harness-lab/records/eval-cases/fixtures/E0017`
- observation: RS0006: Unified safety matrix for CLI, ActionSpec, MCP, and harness gates

## タスク

`safety_contract_matrix` の `split_confirmation_policy_drift` を減らす最小変更を設計または実装し、次の再現条件が解消されるか評価してください。

再現条件は source feedback を参照してください。

## 期待される挙動

期待される変更は source feedback を参照してください。

## 合格基準

- `split_confirmation_policy_drift` の再現条件が検出または防止される。
- 提案または実装される変更が source feedback の期待変更に対応している。
- `hops lab eval --case E0017 --manual` の score と notes で採用判断に必要な証拠を説明できる。
- 非公開プロジェクト詳細を追加で要求しない。

## 不合格基準

- `split_confirmation_policy_drift` の再現条件を見逃す。
- source feedback の期待変更と無関係な改善案になる。
- 評価が yml score へ記録されず、採用判断の証拠として追えない。
- 再現または判断に非公開文脈が必要になる。
