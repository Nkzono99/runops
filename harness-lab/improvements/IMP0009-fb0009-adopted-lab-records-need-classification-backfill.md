---
id: IMP0009
record_type: improvement_dossier
created_at: '2026-05-16T04:06:28+09:00'
updated_at: '2026-05-16T04:06:28+09:00'
status: active
source_type: observation
scope: harnessops-core
maturity: hypothesis
relation: new
promotion_level: target-lab-case
source_feedback: FB0009
eval_cases:
- E0009
hypotheses:
- H0009
decisions: []
research_scans: []
classification:
  capability: lab_classification_metadata
  failure_class: missing_classification_backfill_command
guard:
  status: not-defined
  path:
investigation: []
links:
  issue_url:
---

# IMP0009: FB0009: Adopted lab records need classification backfill

## Status

- status: active
- maturity: hypothesis
- source_type: observation
- scope: harnessops-core
- relation: new
- promotion_level: target-lab-case
- source_feedback: `FB0009`
- linked_records: `FB0009`, `E0009`, `H0009`

## Source Observation

Source: `harness-lab/records/feedback/FB0009-adopted-lab-records-need-classification-backfill.md`

# FB0009: Adopted lab records need classification backfill

## 概要

During steward queue selection, adopted runops target dossiers IMP0007 and IMP0008 still show capability/failure_class as unclassified even though their decisions and guards identify paper request MCP behavior. The public HOPS classify command exposes maturity, scope, relation, promotion, and guard fields, but not capability/failure_class, so agents cannot backfill classification metadata without direct overlay edits.

## 再現

Inspect harness-lab/views/improvements.md after issues #75 and #77 were adopted; then run uvx --from harnessops hops lab classify --help and note there is no capability or failure-class option.

## 期待する上流変更

HarnessOps should provide a CLI-supported path to backfill capability and failure_class on imported feedback, eval cases, hypotheses, and dossiers, or prevent adoption from leaving those fields unclassified.

## Target Capability

- capability: lab_classification_metadata
- failure_class: missing_classification_backfill_command

## Investigation

調査メモはまだありません。

## Research Scans

research scan はまだありません。


## Evaluation

### E0009: E0009: FB0009-adopted-lab-records-need-classification-backfill を評価


- source: `harness-lab/records/eval-cases/E0009-fb0009-adopted-lab-records-need-classification-backfill.md`

- capability: lab_classification_metadata

- failure_class: missing_classification_backfill_command

- manual_eval: 未実施


## Hypotheses

### H0009: H0009: E0009-fb0009-adopted-lab-records-need-classification-backfill の仮説


Source: `harness-lab/records/hypotheses/H0009-e0009-fb0009-adopted-lab-records-need-classification-backfill.md`


# H0009: E0009-fb0009-adopted-lab-records-need-classification-backfill の仮説

## 仮説

Providing a CLI-supported capability/failure_class backfill path, or blocking adoption while those fields remain unclassified, will keep HarnessOps lab queues searchable and evaluable after issue-imported target work is implemented.

## メカニズム

Extend the lab classification workflow so agents can update classification metadata through HOPS commands instead of direct overlay edits, and ensure regenerated feedback, eval, hypothesis, dossier, and view records stay consistent.

## 最小実装

Add a narrow HOPS command option or dedicated subcommand for classification metadata backfill, with validation for non-empty capability and failure_class and regeneration of dependent views/dossiers.

## 代替案: 削除または統合

Keep current classify behavior and rely on initial import classification only, but this leaves adopted imported issues such as IMP0007 and IMP0008 permanently unclassified when the original issue bundle lacked taxonomy.

## 期待される利点

Adopted target work remains discoverable by capability/failure class, and agents can repair metadata without bypassing the managed overlay workflow.

## 想定される欠点

A broad rewrite path could accidentally mutate historical records; the implementation should be narrow, explicit, and covered by a fixture with already-adopted records.

## 評価計画

Create a fixture with an imported feedback/eval/hypothesis/dossier set whose classification is unclassified, run the new backfill path, and assert dependent records/views use the new capability and failure_class without changing decision evidence or guard paths.

## 中止基準

Reject if the path requires direct file edits, rewrites unrelated decision evidence, or allows empty/free-form taxonomy updates that make lab records less consistent.


## Evidence

評価結果はまだありません。

## Guard

- status: not-defined
- path: None

## Links

- issue_url: 未設定

## Open Questions And Next Action

次の実装または評価ステップは、この dossier と紐づく正規化レコードを更新してから再生成してください。

## Decision Log

判断レコードはまだありません。
