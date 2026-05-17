---
id: RS0003
record_type: research_scan
created_at: '2026-05-18T04:14:34+09:00'
status: captured
scope: harnessops-core
existing_dossier:
classification:
  capability: steward_lane_handoff
  failure_class: transient_lane_artifact_loss
evidence:
  local:
  - summary: Daily run 20260518 open-meta produced structured raw_ideas/counterframes/routing_hints, and invention/priority depend on that handoff.
    ref: .harnessops/cache/steward-runs/20260518-040139-5c4808b.json
  codebase:
  - summary: hops-daily-steward defines lane_artifact_contracts only for open-meta; hops-invention/priority consume prior artifacts but no expiry/schema lifecycle is visible in review queue.
    ref: .agents/skills/hops-invention-steward/SKILL.md
  external: []
  risk:
  - summary: 'Metadata creep: artifact persistence should help lane handoff without promoting every broad scan to an improvement dossier.'
    ref: open-meta counterframe 20260518
candidates:
- title: Schema-checked ephemeral lane artifacts
  relation: new
  recommendation: Evaluate a small artifact store with expiry and linting before proposing implementation.
  next_command: hops lab eval-case create after priority selection
recommendation: Queue for priority review as a workflow-design research candidate; do not implement until schema, expiry, and promotion rules are evaluated.
---

# RS0003: Steward lane artifacts need durable schema

## Scope

- scope: harnessops-core
- existing_dossier: 未設定
- capability: steward_lane_handoff
- failure_class: transient_lane_artifact_loss

## Evidence

### Local

- Daily run 20260518 open-meta produced structured raw_ideas/counterframes/routing_hints, and invention/priority depend on that handoff. (ref: .harnessops/cache/steward-runs/20260518-040139-5c4808b.json)

### Codebase

- hops-daily-steward defines lane_artifact_contracts only for open-meta; hops-invention/priority consume prior artifacts but no expiry/schema lifecycle is visible in review queue. (ref: .agents/skills/hops-invention-steward/SKILL.md)

### External

- なし

### Risk And Counterexample

- Metadata creep: artifact persistence should help lane handoff without promoting every broad scan to an improvement dossier. (ref: open-meta counterframe 20260518)

## Candidates

| candidate | relation | recommendation | next_command |
|---|---|---|---|
| Schema-checked ephemeral lane artifacts | new | Evaluate a small artifact store with expiry and linting before proposing implementation. | hops lab eval-case create after priority selection |

## Recommendation

Queue for priority review as a workflow-design research candidate; do not implement until schema, expiry, and promotion rules are evaluated.

## Next Commands

- `hops lab eval-case create after priority selection`
