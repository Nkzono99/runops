---
id: IMP0002
record_type: improvement_dossier
created_at: '2026-05-13T18:13:12+09:00'
updated_at: '2026-05-13T18:13:22+09:00'
status: active
source_type: local-reproduction
scope: harnessops-core
maturity: proposed
relation: new
promotion_level: core-bugfix
source_feedback: FB0002
eval_cases:
- E0002
hypotheses:
- H0002
decisions: []
research_scans: []
classification:
  capability: lab_cli_error_handling
  failure_class: expected_user_error_traceback
guard:
  status: candidate
  path: tests/test_cli/test_mvp_flow.py::test_lab_dossier_rejects_research_scan_without_traceback
investigation: []
links:
  issue_url:
---

# IMP0002: FB0002: Lab dossier invalid source shows traceback

## Status

- status: active
- maturity: proposed
- source_type: local-reproduction
- scope: harnessops-core
- relation: new
- promotion_level: core-bugfix
- source_feedback: `FB0002`
- linked_records: `FB0002`, `E0002`, `H0002`

## Source Observation

Source: `harness-lab/records/feedback/FB0002-lab-dossier-invalid-source-shows-traceback.md`

# FB0002: Lab dossier invalid source shows traceback

## 概要

Running hops lab dossier --from RS0001 is an expected user mistake because research scans are adjacent lab records, but the command currently lets a ValueError escape as a rich traceback instead of returning a concise user-facing error.

## 再現

In a HarnessOps lab with RS0001 present, run hops lab dossier --from RS0001; the command exits nonzero and prints a traceback ending with ValueError: dossier は FB/E/H/D レコードから作成してください: RS0001.

## 期待する上流変更

The lab dossier command should catch unsupported source record types and print a short actionable message, preserving nonzero exit status without a traceback in normal operation.

## Target Capability

- capability: lab_cli_error_handling
- failure_class: expected_user_error_traceback

## Investigation

調査メモはまだありません。

## Research Scans

research scan はまだありません。


## Evaluation

### E0002: E0002: FB0002-lab-dossier-invalid-source-shows-traceback を評価


- source: `harness-lab/records/eval-cases/E0002-fb0002-lab-dossier-invalid-source-shows-traceback.md`

- capability: lab_cli_error_handling

- failure_class: expected_user_error_traceback

- manual_eval: 未実施


## Hypotheses

### H0002: H0002: E0002-fb0002-lab-dossier-invalid-source-shows-traceback の仮説


Source: `harness-lab/records/hypotheses/H0002-e0002-fb0002-lab-dossier-invalid-source-shows-traceback.md`


# H0002: E0002-fb0002-lab-dossier-invalid-source-shows-traceback の仮説

## 仮説

Catching expected domain ValueError exceptions in lab dossier will make HarnessOps lab CLI safer for agents and humans by turning invalid source records into actionable messages instead of tracebacks.

## メカニズム

Wrap create_or_update_improvement_dossier in the lab dossier command with ValueError handling, echo the domain message, suggest valid source record prefixes FB/E/H/D or the correct research-scan path, and exit with code 1.

## 最小実装

Add a ValueError except block around create_or_update_improvement_dossier in harnessops.cli.lab.dossier and add a CliRunner test that hops lab dossier --from RS0001 exits 1, includes the concise message, and omits Traceback.

## 代替案: 削除または統合

Keep core records.py unchanged and rely on agents to know valid prefixes, but this leaves expected mistakes noisy and harder to recover from.

## 期待される利点

Normal invalid input becomes readable, testable, and consistent with existing eval/feedback CLI error handling.

## 想定される欠点

Catching broad ValueError in this command could hide an internal bug if the message is not domain-specific; the handler should remain narrow or use a domain exception later.

## 評価計画

Create a fixture with an RS record, run lab dossier against it, and assert nonzero exit, no traceback, and a message explaining supported source record types.

## 中止基準

Reject if the fix suppresses unexpected internal exceptions or makes debugging real corruption harder.


## Evidence

評価結果はまだありません。

## Guard

- status: candidate
- path: tests/test_cli/test_mvp_flow.py::test_lab_dossier_rejects_research_scan_without_traceback

## Links

- issue_url: 未設定

## Open Questions And Next Action

次の実装または評価ステップは、この dossier と紐づく正規化レコードを更新してから再生成してください。

## Decision Log

判断レコードはまだありません。
