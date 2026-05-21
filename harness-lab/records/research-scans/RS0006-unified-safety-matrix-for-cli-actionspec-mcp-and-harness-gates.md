---
id: RS0006
record_type: research_scan
created_at: '2026-05-22T04:12:44+09:00'
status: captured
scope: harnessops-core
existing_dossier: RS0004
classification:
  capability: safety_contract_matrix
  failure_class: split_confirmation_policy_drift
evidence:
  local:
  - summary: Open-meta idea 2
    ref: Safety policy is currently distributed across CLI --yes prompts, ActionSpec confirmation metadata, MCP disabled tools, and harness/rules guidance.
  codebase:
  - summary: docs/agent-user-guide.md:148-151
    ref: submit/cancel guidance and --yes are documented separately from MCP safety.
  - summary: src/runops/core/actions/specs.py:95-109,225-251
    ref: ActionSpec carries risk, confirmation, CLI commands, and MCP tool mapping.
  - summary: src/runops/mcp/registry.py:257-307
    ref: MCP check already validates disabled mutating tools and unsafe action confirmation metadata.
  external: []
  risk:
  - summary: duplicate-docs
    ref: Do not add another narrative safety page unless it is generated/linted from source metadata or replaces existing scattered guidance.
candidates:
- title: Safety matrix linter
  relation: extends RS0004
  recommendation: Evaluate a single generated/linted matrix that compares CLI prompts, ActionSpec confirmation, MCP safety metadata, and harness rules.
  next_command: hops lab eval-case create after priority selection
recommendation: Queue for priority review as an evaluation-methodology candidate; prefer a lint/generated matrix over hand-maintained documentation.
---

# RS0006: Unified safety matrix for CLI, ActionSpec, MCP, and harness gates

## Scope

- scope: harnessops-core
- existing_dossier: RS0004
- capability: safety_contract_matrix
- failure_class: split_confirmation_policy_drift

## Evidence

### Local

- Open-meta idea 2 (ref: Safety policy is currently distributed across CLI --yes prompts, ActionSpec confirmation metadata, MCP disabled tools, and harness/rules guidance.)

### Codebase

- docs/agent-user-guide.md:148-151 (ref: submit/cancel guidance and --yes are documented separately from MCP safety.)
- src/runops/core/actions/specs.py:95-109,225-251 (ref: ActionSpec carries risk, confirmation, CLI commands, and MCP tool mapping.)
- src/runops/mcp/registry.py:257-307 (ref: MCP check already validates disabled mutating tools and unsafe action confirmation metadata.)

### External

- なし

### Risk And Counterexample

- duplicate-docs (ref: Do not add another narrative safety page unless it is generated/linted from source metadata or replaces existing scattered guidance.)

## Candidates

| candidate | relation | recommendation | next_command |
|---|---|---|---|
| Safety matrix linter | extends RS0004 | Evaluate a single generated/linted matrix that compares CLI prompts, ActionSpec confirmation, MCP safety metadata, and harness rules. | hops lab eval-case create after priority selection |

## Recommendation

Queue for priority review as an evaluation-methodology candidate; prefer a lint/generated matrix over hand-maintained documentation.

## Next Commands

- `hops lab eval-case create after priority selection`
