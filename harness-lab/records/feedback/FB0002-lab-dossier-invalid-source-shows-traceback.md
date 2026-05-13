---
id: FB0002
record_type: imported_feedback
created_at: '2026-05-13T18:12:43+09:00'
status: triaged
source:
  type: local-capture
  original_id: local runops HarnessOps research session 2026-05-13
  source_project: runops
classification:
  capability: lab_cli_error_handling
  failure_class: expected_user_error_traceback
links:
  eval_case:
  issue_url:
---

# FB0002: Lab dossier invalid source shows traceback

## 概要

Running hops lab dossier --from RS0001 is an expected user mistake because research scans are adjacent lab records, but the command currently lets a ValueError escape as a rich traceback instead of returning a concise user-facing error.

## 再現

In a HarnessOps lab with RS0001 present, run hops lab dossier --from RS0001; the command exits nonzero and prints a traceback ending with ValueError: dossier は FB/E/H/D レコードから作成してください: RS0001.

## 期待する上流変更

The lab dossier command should catch unsupported source record types and print a short actionable message, preserving nonzero exit status without a traceback in normal operation.
