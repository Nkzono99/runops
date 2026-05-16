---
id: D0008
record_type: decision
created_at: '2026-05-17T04:24:23+09:00'
status: needs-more-evidence
source: H0009
evidence:
  summary: 'E0009 manual score plus priority-lane reproduction: hops lab classify --help lacks capability/failure-class options, and hops lab review queue shows IMP0010-IMP0014 still unclassified before scoring.'
  guard_path: harnessops-core:tests/test_cli/test_lab_classify.py::test_lab_classify_backfills_capability_and_failure_class
---

# D0008: needs-more-evidence H0009

## 判断

needs-more-evidence

## 理由

The failure is reproduced and the proposed taxonomy backfill path is clear, but no HarnessOps core implementation or passing guard has been recorded yet.

## 証拠

E0009 manual score plus priority-lane reproduction: hops lab classify --help lacks capability/failure-class options, and hops lab review queue shows IMP0010-IMP0014 still unclassified before scoring.

## 回帰リスク

Medium if implemented as a broad metadata rewrite: it could mutate historical decision evidence or silently change unrelated dossiers. Keep the backfill command explicit and fixture-driven.

## フォローアップ

Implement the HarnessOps core backfill or pre-eval classification gate, run the guard, regenerate affected dossiers/views, then classify and score IMP0010-IMP0014.

## 回帰ガード

harnessops-core:tests/test_cli/test_lab_classify.py::test_lab_classify_backfills_capability_and_failure_class
