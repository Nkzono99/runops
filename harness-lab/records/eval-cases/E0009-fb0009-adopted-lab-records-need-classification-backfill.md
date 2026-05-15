---
id: E0009
record_type: eval_case
created_at: '2026-05-16T04:05:50+09:00'
status: active
capability: lab_classification_metadata
failure_class: missing_classification_backfill_command
source_feedback: FB0009
---

# E0009: FB0009-adopted-lab-records-need-classification-backfill を評価

## フィクスチャ

- source_feedback: `harness-lab/records/feedback/FB0009-adopted-lab-records-need-classification-backfill.md`
- fixture_dir: `harness-lab/records/eval-cases/fixtures/E0009`
- observation: During steward queue selection, adopted runops target dossiers IMP0007 and IMP0008 still show capability/failure_class as unclassified even though their decisions and guards identify paper request MCP behavior. The public HOPS classify command exposes maturity, scope, relation, promotion, and guard fields, but not capability/failure_class, so agents cannot backfill classification metadata without direct overlay edits.

## タスク

`lab_classification_metadata` の `missing_classification_backfill_command` を減らす最小変更を設計または実装し、次の再現条件が解消されるか評価してください。

Inspect harness-lab/views/improvements.md after issues #75 and #77 were adopted; then run uvx --from harnessops hops lab classify --help and note there is no capability or failure-class option.

## 期待される挙動

HarnessOps should provide a CLI-supported path to backfill capability and failure_class on imported feedback, eval cases, hypotheses, and dossiers, or prevent adoption from leaving those fields unclassified.

## 合格基準

- `missing_classification_backfill_command` の再現条件が検出または防止される。
- 提案または実装される変更が source feedback の期待変更に対応している。
- `hops eval --case E0009 --manual` の score と notes で採用判断に必要な証拠を説明できる。
- 非公開プロジェクト詳細を追加で要求しない。

## 不合格基準

- `missing_classification_backfill_command` の再現条件を見逃す。
- source feedback の期待変更と無関係な改善案になる。
- 評価が yml score へ記録されず、採用判断の証拠として追えない。
- 再現または判断に非公開文脈が必要になる。
