---
id: RS0005
record_type: research_scan
created_at: '2026-05-21T04:13:30+09:00'
status: captured
scope: harnessops-core
existing_dossier:
classification:
  capability: target_intent_context
  failure_class: steward_target_context_inference
evidence:
  local:
  - summary: Open-meta scan found steward lanes infer runops target intent, memory boundaries, and human gates from scattered docs while automation memory tracks lane-local state.
    ref: automation memory 20260521-040240-b6fdb3d; open-meta raw ideas 1-3
  codebase:
  - summary: runops documents agent context via runo context --json, project memory, explicit human gates, and high-cost lifecycle commands; paper/MCP docs keep experiment requests plan-only and disable submit/cancel/delete by default.
    ref: README.md:94; README.md:120; docs/agent-user-guide.md:20; docs/agent-user-guide.md:70; docs/layers/interface.md:55; docs/layers/execution-kernel.md:105; docs/mcp.md:44; docs/mcp.md:143; .codex/rules/commands.md:13
  external: []
  risk:
  - summary: A durable digest can drift from target source-of-truth if copied into HOPS records; keep it as a generated/pre-lane read model or context contract, not a second project memory.
    ref: docs/layers/knowledge.md:556; docs/agent-user-guide.md:197
candidates:
- title: Pre-lane target-intent digest
  relation: new
  recommendation: Evaluate a generated digest sourced from runo context --json plus configured docs before autonomous steward lanes; do not persist target decisions as HOPS truth.
  next_command: hops lab eval-case create after priority selection
- title: Human-gate evidence requirement
  relation: extends target-intent digest
  recommendation: Require autonomous lanes to cite target-owned gate evidence before submit/cancel/delete/release-like actions; keep gates advisory unless target docs mark them blocking.
  next_command: hops lab investigate/classify after priority selection
recommendation: Queue as a workflow-design research candidate; priority lane should evaluate a read-only context contract before any implementation.
---

# RS0005: Target intent and human-gate context before steward lanes

## Scope

- scope: harnessops-core
- existing_dossier: 未設定
- capability: target_intent_context
- failure_class: steward_target_context_inference

## Evidence

### Local

- Open-meta scan found steward lanes infer runops target intent, memory boundaries, and human gates from scattered docs while automation memory tracks lane-local state. (ref: automation memory 20260521-040240-b6fdb3d; open-meta raw ideas 1-3)

### Codebase

- runops documents agent context via runo context --json, project memory, explicit human gates, and high-cost lifecycle commands; paper/MCP docs keep experiment requests plan-only and disable submit/cancel/delete by default. (ref: README.md:94; README.md:120; docs/agent-user-guide.md:20; docs/agent-user-guide.md:70; docs/layers/interface.md:55; docs/layers/execution-kernel.md:105; docs/mcp.md:44; docs/mcp.md:143; .codex/rules/commands.md:13)

### External

- なし

### Risk And Counterexample

- A durable digest can drift from target source-of-truth if copied into HOPS records; keep it as a generated/pre-lane read model or context contract, not a second project memory. (ref: docs/layers/knowledge.md:556; docs/agent-user-guide.md:197)

## Candidates

| candidate | relation | recommendation | next_command |
|---|---|---|---|
| Pre-lane target-intent digest | new | Evaluate a generated digest sourced from runo context --json plus configured docs before autonomous steward lanes; do not persist target decisions as HOPS truth. | hops lab eval-case create after priority selection |
| Human-gate evidence requirement | extends target-intent digest | Require autonomous lanes to cite target-owned gate evidence before submit/cancel/delete/release-like actions; keep gates advisory unless target docs mark them blocking. | hops lab investigate/classify after priority selection |

## Recommendation

Queue as a workflow-design research candidate; priority lane should evaluate a read-only context contract before any implementation.

## Next Commands

- `hops lab eval-case create after priority selection`
- `hops lab investigate/classify after priority selection`
