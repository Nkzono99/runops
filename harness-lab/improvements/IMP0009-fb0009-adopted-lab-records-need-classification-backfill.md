---
id: IMP0009
record_type: improvement_dossier
created_at: '2026-05-16T04:06:28+09:00'
updated_at: '2026-05-17T04:24:33+09:00'
status: needs-more-evidence
source_type: local-reproduction
scope: harnessops-core
maturity: investigated
relation: extends
promotion_level: core-bugfix
source_feedback: FB0009
eval_cases:
- E0009
hypotheses:
- H0009
decisions:
- D0008
research_scans:
- RS0002
classification:
  capability: lab_classification_metadata
  failure_class: missing_classification_backfill_command
guard:
  status: candidate
  path: harnessops-core:tests/test_cli/test_lab_classify.py::test_lab_classify_backfills_capability_and_failure_class
investigation:
- created_at: '2026-05-17T04:17:10+09:00'
  kind: codebase
  summary: 'Open scan found the same classification gap before adoption: issue-execution imported FB0010-FB0014 and created IMP0010-IMP0014, but all five are already in the manual-eval queue with capability/failure_class still unclassified. This broadens the failure from post-adoption backfill to an import/propose-time taxonomy gate before evaluator scoring.'
  evidence_ref: harness-lab/views/improvements.md; harness-lab/views/imported-feedback.md; hops lab review queue --json
- created_at: '2026-05-17T04:23:51+09:00'
  kind: reproduction
  summary: 'Reconfirmed priority-lane blocker: hops lab classify exposes maturity/scope/relation/promotion/guard options but no capability or failure-class option, while review queue contains IMP0010-IMP0014 already awaiting manual eval with unclassified taxonomy.'
  evidence_ref: uvx --from harnessops hops lab classify --help; uvx --from harnessops hops lab review queue --json
links:
  issue_url:
---

# IMP0009: FB0009: Adopted lab records need classification backfill

## Status

- status: needs-more-evidence
- maturity: investigated
- source_type: local-reproduction
- scope: harnessops-core
- relation: extends
- promotion_level: core-bugfix
- source_feedback: `FB0009`
- linked_records: `FB0009`, `RS0002`, `E0009`, `H0009`, `D0008`

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

- 2026-05-17T04:17:10+09:00 [codebase] Open scan found the same classification gap before adoption: issue-execution imported FB0010-FB0014 and created IMP0010-IMP0014, but all five are already in the manual-eval queue with capability/failure_class still unclassified. This broadens the failure from post-adoption backfill to an import/propose-time taxonomy gate before evaluator scoring. (evidence: harness-lab/views/improvements.md; harness-lab/views/imported-feedback.md; hops lab review queue --json)
- 2026-05-17T04:23:51+09:00 [reproduction] Reconfirmed priority-lane blocker: hops lab classify exposes maturity/scope/relation/promotion/guard options but no capability or failure-class option, while review queue contains IMP0010-IMP0014 already awaiting manual eval with unclassified taxonomy. (evidence: uvx --from harnessops hops lab classify --help; uvx --from harnessops hops lab review queue --json)

## Research Scans

### RS0002: RS0002: Issue import taxonomy guard before scoring


Source: `harness-lab/records/research-scans/RS0002-issue-import-taxonomy-guard-before-scoring.md`


# RS0002: Issue import taxonomy guard before scoring

## Scope

- scope: harnessops-core
- existing_dossier: IMP0009
- capability: lab_classification_metadata
- failure_class: missing_import_taxonomy_gate

## Evidence

### Local

- Issue lane imported #84-#88 as FB0010-FB0014 and created IMP0010-IMP0014; all five remain unclassified before evaluator scoring (ref: harness-lab/views/improvements.md)

### Codebase

- lab review queue prioritizes IMP0010-IMP0014 for manual eval/decisions while capability and failure_class are unclassified (ref: hops lab review queue --json)

### External

- なし

### Risk And Counterexample

- Scoring five related GitHub Flow records before taxonomy and relation are clear can fragment evaluator effort and hide the shared delegated-finalization capability (ref: harness-lab/records/feedback/FB0010-hops-github-flow-pr-label.md; harness-lab/records/feedback/FB0011-hops-github-flow-pr-view-checks-watch.md; harness-lab/records/feedback/FB0013-hops-github-flow-merge-merge-strategy.md; harness-lab/records/feedback/FB0014-hops-github-flow-merge-json-post-merge.md)

## Candidates

| candidate | relation | recommendation | next_command |
|---|---|---|---|
| Issue-import classification gate | extends IMP0009 | Require import/propose flow to capture capability/failure_class before manual eval queue, or mark records blocked for classification | hops lab classify/backfill or import taxonomy option |
| Bundle related github-flow records | queued_for_later | Classify FB0010-FB0014 under a common GitHub Flow finalization capability before evaluator decides each separately | hops lab investigate/classify related IMP0010-IMP0014 |

## Recommendation

classify existing IMP0009 and queue taxonomy gating before manual scoring

## Next Commands

- `hops lab classify/backfill or import taxonomy option`
- `hops lab investigate/classify related IMP0010-IMP0014`


## Evaluation

### E0009: E0009: FB0009-adopted-lab-records-need-classification-backfill を評価


- source: `harness-lab/records/eval-cases/E0009-fb0009-adopted-lab-records-need-classification-backfill.md`

- capability: lab_classification_metadata

- failure_class: missing_classification_backfill_command

- manual_eval_yml: `harness-lab/views/eval-results/E0009-manual-score.yml`
- manual_eval_md: `harness-lab/views/eval-results/E0009-manual-score.md`
- scores: impact=4, mechanism_clarity=5, evaluability=5, minimality=4, regression_risk=2, operator_burden=5, anti_theater=5, maintainability=4, privacy_sanitization_risk=5
- notes: Priority-lane evidence confirms the failure remains current: the public hops lab classify command still lacks capability/failure-class options, and review queue already contains IMP0010-IMP0014 awaiting manual eval with unclassified taxonomy. The narrow upstream fix is testable as a CLI-supported backfill or pre-eval gate that updates related FB/E/H/IMP records and generated views without direct overlay edits. Adoption should wait until the HarnessOps core guard passes, because broad metadata rewriting could corrupt historical decision evidence.


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

`harness-lab/views/eval-results/E0009-manual-score.md`

## Guard

- status: candidate
- path: harnessops-core:tests/test_cli/test_lab_classify.py::test_lab_classify_backfills_capability_and_failure_class

## Links

- issue_url: 未設定

## Open Questions And Next Action

次の実装または評価ステップは、この dossier と紐づく正規化レコードを更新してから再生成してください。

## Decision Log

### D0008: D0008: needs-more-evidence H0009


Source: `harness-lab/records/decisions/D0008-needs-more-evidence-h0009.md`


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
