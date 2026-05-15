---
id: FB0009
record_type: imported_feedback
created_at: '2026-05-16T04:05:26+09:00'
status: triaged
source:
  type: local-capture
  original_id: 'harness-lab/views/improvements.md; harness-lab/improvements/IMP0007-fb0007-paper-request-draft-validate-mcp-paperops-handoff.md; harness-lab/improvements/IMP0008-fb0008-paper-request-draft-duplicate-id-append.md; command: uvx --from harnessops hops lab classify --help'
  source_project: runops
classification:
  capability: lab_classification_metadata
  failure_class: missing_classification_backfill_command
links:
  eval_case:
  issue_url:
---

# FB0009: Adopted lab records need classification backfill

## 概要

During steward queue selection, adopted runops target dossiers IMP0007 and IMP0008 still show capability/failure_class as unclassified even though their decisions and guards identify paper request MCP behavior. The public HOPS classify command exposes maturity, scope, relation, promotion, and guard fields, but not capability/failure_class, so agents cannot backfill classification metadata without direct overlay edits.

## 再現

Inspect harness-lab/views/improvements.md after issues #75 and #77 were adopted; then run uvx --from harnessops hops lab classify --help and note there is no capability or failure-class option.

## 期待する上流変更

HarnessOps should provide a CLI-supported path to backfill capability and failure_class on imported feedback, eval cases, hypotheses, and dossiers, or prevent adoption from leaving those fields unclassified.
