---
id: H0009
record_type: hypothesis
created_at: '2026-05-16T04:06:03+09:00'
status: proposed
target_capability: lab_classification_metadata
source_eval_case: E0009
---

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
