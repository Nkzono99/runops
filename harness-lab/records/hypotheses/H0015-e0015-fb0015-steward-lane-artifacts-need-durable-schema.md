---
id: H0015
record_type: hypothesis
created_at: '2026-05-18T04:21:27+09:00'
status: proposed
target_capability: steward_lane_handoff
source_eval_case: E0015
---

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
