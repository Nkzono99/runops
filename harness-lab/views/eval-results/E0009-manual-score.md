<!-- harnessops により生成; source records が正本 -->
# 手動評価結果: E0009

送信元: `harness-lab/records/eval-cases/E0009-fb0009-adopted-lab-records-need-classification-backfill.md`

## スコア

- impact: 4
- mechanism_clarity: 5
- evaluability: 5
- minimality: 4
- regression_risk: 2
- operator_burden: 5
- anti_theater: 5
- maintainability: 4
- privacy_sanitization_risk: 5

## メモ

Priority-lane evidence confirms the failure remains current: the public hops lab classify command still lacks capability/failure-class options, and review queue already contains IMP0010-IMP0014 awaiting manual eval with unclassified taxonomy. The narrow upstream fix is testable as a CLI-supported backfill or pre-eval gate that updates related FB/E/H/IMP records and generated views without direct overlay edits. Adoption should wait until the HarnessOps core guard passes, because broad metadata rewriting could corrupt historical decision evidence.

## 評価ケース

- capability: lab_classification_metadata
- failure_class: missing_classification_backfill_command
- source_feedback: FB0009
