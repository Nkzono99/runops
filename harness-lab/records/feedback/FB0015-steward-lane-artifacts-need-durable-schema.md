---
id: FB0015
record_type: imported_feedback
created_at: '2026-05-18T04:20:42+09:00'
status: triaged
source:
  type: local-capture
  original_id: RS0003
  source_project: runops
classification:
  capability: steward_lane_handoff
  failure_class: transient_lane_artifact_loss
links:
  eval_case:
  issue_url:
---

# FB0015: Steward lane artifacts need durable schema

## 概要

Daily steward lanes now pass structured open-meta artifacts through the run ledger, but those artifacts have no first-class schema, expiry, or promotion lifecycle. RS0003 captured the research scan; this feedback turns it into an evaluable upstream HOPS improvement packet.

## 再現

Run 20260518-040139-5c4808b stored artifacts.meta_scan in the steward ledger and later lanes depended on it; review queue can show RS0003, but current eval/dossier flow is feedback-centric rather than research-scan-centric.

## 期待する上流変更

HarnessOps should define a narrow steward lane artifact lifecycle: schema-checked artifacts in the run ledger or managed cache, explicit expiry/promotion rules, lint/review visibility, and no requirement to promote every broad scan to a permanent improvement dossier.
