---
id: E0016
record_type: eval_case
created_at: '2026-05-21T04:18:04+09:00'
status: active
capability: target_intent_context
failure_class: steward_target_context_inference
source_feedback: FB0016
---

# E0016: FB0016-pre-lane-target-intent-context-for-steward-lanes を評価

## フィクスチャ

- source_feedback: `harness-lab/records/feedback/FB0016-pre-lane-target-intent-context-for-steward-lanes.md`
- fixture_dir: `harness-lab/records/eval-cases/fixtures/E0016`
- observation: Autonomous steward lanes currently infer target intent, memory boundaries, and human gates from scattered target docs and lane-local handoff text. RS0005 captured the need to evaluate a read-only pre-lane context contract sourced from target-owned context surfaces such as runo context --json and documented command gates.

## タスク

`target_intent_context` の `steward_target_context_inference` を減らす最小変更を設計または実装し、次の再現条件が解消されるか評価してください。

Daily steward run 20260521-040240-b6fdb3d produced RS0005 after open-meta and invention observed that priority lanes need target intent and human-gate evidence before implementation; runops already exposes target context via runo context --json and docs.

## 期待される挙動

HarnessOps should evaluate a narrow pre-lane target intent digest contract that cites target-owned sources for project role, memory boundaries, command authority, and human gates before autonomous lanes make release, submit, cancel, delete, or persistent-memory decisions.

## 合格基準

- `steward_target_context_inference` の再現条件が検出または防止される。
- 提案または実装される変更が source feedback の期待変更に対応している。
- `hops lab eval --case E0016 --manual` の score と notes で採用判断に必要な証拠を説明できる。
- 非公開プロジェクト詳細を追加で要求しない。

## 不合格基準

- `steward_target_context_inference` の再現条件を見逃す。
- source feedback の期待変更と無関係な改善案になる。
- 評価が yml score へ記録されず、採用判断の証拠として追えない。
- 再現または判断に非公開文脈が必要になる。
