---
id: IMP0015
record_type: improvement_dossier
created_at: '2026-05-18T04:20:52+09:00'
updated_at: '2026-05-18T04:22:05+09:00'
status: needs-more-evidence
source_type: local-reproduction
scope: harnessops-core
maturity: investigated
relation: new
promotion_level: core-workflow
source_feedback: FB0015
eval_cases:
- E0015
hypotheses:
- H0015
decisions:
- D0009
research_scans: []
classification:
  capability: steward_lane_handoff
  failure_class: transient_lane_artifact_loss
guard:
  status: candidate
  path: harnessops-core:tests/test_steward/test_lane_artifacts.py::test_open_meta_artifacts_are_schema_checked_and_expire
investigation:
- created_at: '2026-05-18T04:21:03+09:00'
  kind: codebase
  summary: 'Priority review confirmed RS0003 is a valid cross-lane handoff problem, but the current lab promotion path is feedback-centric: create_eval_case records source_feedback and create_or_update_improvement_dossier only normalizes FB/E/H/D back to imported_feedback. A direct RS-to-eval route would risk an orphan eval/hypothesis, so this lane promoted RS0003 through FB0015 before scoring.'
  evidence_ref: RS0003; harnessops.core.lab_records.create_eval_case; harnessops.core.improvement_dossier._feedback_for_record
links:
  issue_url:
---

# IMP0015: FB0015: Steward lane artifacts need durable schema

## Status

- status: needs-more-evidence
- maturity: investigated
- source_type: local-reproduction
- scope: harnessops-core
- relation: new
- promotion_level: core-workflow
- source_feedback: `FB0015`
- linked_records: `FB0015`, `E0015`, `H0015`, `D0009`

## Source Observation

Source: `harness-lab/records/feedback/FB0015-steward-lane-artifacts-need-durable-schema.md`

# FB0015: Steward lane artifacts need durable schema

## 概要

Daily steward lanes now pass structured open-meta artifacts through the run ledger, but those artifacts have no first-class schema, expiry, or promotion lifecycle. RS0003 captured the research scan; this feedback turns it into an evaluable upstream HOPS improvement packet.

## 再現

Run 20260518-040139-5c4808b stored artifacts.meta_scan in the steward ledger and later lanes depended on it; review queue can show RS0003, but current eval/dossier flow is feedback-centric rather than research-scan-centric.

## 期待する上流変更

HarnessOps should define a narrow steward lane artifact lifecycle: schema-checked artifacts in the run ledger or managed cache, explicit expiry/promotion rules, lint/review visibility, and no requirement to promote every broad scan to a permanent improvement dossier.

## Target Capability

- capability: steward_lane_handoff
- failure_class: transient_lane_artifact_loss

## Investigation

- 2026-05-18T04:21:03+09:00 [codebase] Priority review confirmed RS0003 is a valid cross-lane handoff problem, but the current lab promotion path is feedback-centric: create_eval_case records source_feedback and create_or_update_improvement_dossier only normalizes FB/E/H/D back to imported_feedback. A direct RS-to-eval route would risk an orphan eval/hypothesis, so this lane promoted RS0003 through FB0015 before scoring. (evidence: RS0003; harnessops.core.lab_records.create_eval_case; harnessops.core.improvement_dossier._feedback_for_record)

## Research Scans

research scan はまだありません。


## Evaluation

### E0015: E0015: FB0015-steward-lane-artifacts-need-durable-schema を評価


- source: `harness-lab/records/eval-cases/E0015-fb0015-steward-lane-artifacts-need-durable-schema.md`

- capability: steward_lane_handoff

- failure_class: transient_lane_artifact_loss

- manual_eval_yml: `harness-lab/views/eval-results/E0015-manual-score.yml`
- manual_eval_md: `harness-lab/views/eval-results/E0015-manual-score.md`
- scores: impact=4, mechanism_clarity=4, evaluability=4, minimality=3, regression_risk=3, operator_burden=4, anti_theater=4, maintainability=3, privacy_sanitization_risk=5
- notes: Priority-lane evidence supports the problem: run 20260518 used structured artifacts.meta_scan as a handoff from open-meta to invention and priority, while current review context only surfaces RS0003 after it is promoted. The proposed fix is evaluable with steward-run fixtures for required fields, malformed artifact rejection, and expiry/promotion behavior. Adoption should wait for HarnessOps core implementation because an artifact store can become a second source of truth if schema, expiry, and promotion boundaries are not enforced.


## Hypotheses

### H0015: H0015: E0015-fb0015-steward-lane-artifacts-need-durable-schema の仮説


Source: `harness-lab/records/hypotheses/H0015-e0015-fb0015-steward-lane-artifacts-need-durable-schema.md`


# H0015: E0015-fb0015-steward-lane-artifacts-need-durable-schema の仮説

## 仮説

Adding a schema-checked, expiring steward lane artifact lifecycle will preserve cross-lane handoffs without forcing every exploratory scan into permanent lab records.

## メカニズム

Store lane artifacts under a documented contract keyed by run_id and lane, validate required fields when recording lane results, expose them through review context, and require explicit promotion before they become feedback, research scans, or improvement dossiers.

## 最小実装

In HarnessOps core, extend steward run record-lane-result validation for declared artifact contracts, add expiry or retention metadata for non-promoted artifacts, and add focused tests for open-meta artifact availability to invention and priority lanes.

## 代替案: 削除または統合

Keep artifacts only inside each lane's final text or JSON result. This avoids new state, but loses schema validation, expiry semantics, and review discoverability once the run ledger is no longer in active context.

## 期待される利点

Later lanes can consume structured handoffs reliably, supervisors can lint missing or stale artifacts, and agents avoid creating permanent records just to transfer raw ideas between lanes.

## 想定される欠点

A new artifact lifecycle can become metadata theater if it duplicates lab records or hides important decisions in ephemeral state; retention and promotion rules must stay narrow.

## 評価計画

Use a steward-run fixture with open-meta artifacts, assert invention and priority context can retrieve required fields, assert malformed artifacts fail validation, and assert unpromoted artifacts expire or remain clearly non-authoritative.

## 中止基準

Reject if the design creates a second source of truth for decisions, requires direct overlay edits, exposes private project details, or adds artifact records without schema and expiry enforcement.


## Evidence

`harness-lab/views/eval-results/E0015-manual-score.md`

## Guard

- status: candidate
- path: harnessops-core:tests/test_steward/test_lane_artifacts.py::test_open_meta_artifacts_are_schema_checked_and_expire

## Links

- issue_url: 未設定

## Open Questions And Next Action

次の実装または評価ステップは、この dossier と紐づく正規化レコードを更新してから再生成してください。

## Decision Log

### D0009: D0009: needs-more-evidence H0015


Source: `harness-lab/records/decisions/D0009-needs-more-evidence-h0015.md`


# D0009: needs-more-evidence H0015

## 判断

needs-more-evidence

## 理由

The mechanism and evaluation path are clear, but this run only produced target-lab evidence; no HarnessOps core implementation or passing guard exists yet.

## 証拠

RS0003 plus E0015 manual score: the steward ledger carried artifacts.meta_scan across lanes, and current lab tooling needed promotion through FB0015 to make the candidate evaluable without orphaning eval records.

## 回帰リスク

Medium. A durable artifact lifecycle could duplicate lab records or preserve private transient context unless schema validation, expiry, and explicit promotion rules are enforced.

## フォローアップ

Implement the HarnessOps core steward artifact contract with fixture coverage, then rerun review context and decide whether to adopt. Keep RS0004 queued until validation taxonomy work is ready.

## 回帰ガード

harnessops-core:tests/test_steward/test_lane_artifacts.py::test_open_meta_artifacts_are_schema_checked_and_expire
