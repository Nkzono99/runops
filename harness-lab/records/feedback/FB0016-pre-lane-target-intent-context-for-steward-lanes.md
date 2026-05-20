---
id: FB0016
record_type: imported_feedback
created_at: '2026-05-21T04:17:04+09:00'
status: triaged
source:
  type: local-capture
  original_id: RS0005; README.md; docs/agent-user-guide.md; docs/layers/interface.md; docs/layers/execution-kernel.md; docs/mcp.md; .codex/rules/commands.md
  source_project: runops
classification:
  capability: target_intent_context
  failure_class: steward_target_context_inference
links:
  eval_case:
  issue_url:
---

# FB0016: Pre-lane target intent context for steward lanes

## 概要

Autonomous steward lanes currently infer target intent, memory boundaries, and human gates from scattered target docs and lane-local handoff text. RS0005 captured the need to evaluate a read-only pre-lane context contract sourced from target-owned context surfaces such as runo context --json and documented command gates.

## 再現

Daily steward run 20260521-040240-b6fdb3d produced RS0005 after open-meta and invention observed that priority lanes need target intent and human-gate evidence before implementation; runops already exposes target context via runo context --json and docs.

## 期待する上流変更

HarnessOps should evaluate a narrow pre-lane target intent digest contract that cites target-owned sources for project role, memory boundaries, command authority, and human gates before autonomous lanes make release, submit, cancel, delete, or persistent-memory decisions.
