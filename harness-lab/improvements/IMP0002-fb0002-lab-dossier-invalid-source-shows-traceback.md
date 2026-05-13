---
id: IMP0002
record_type: improvement_dossier
created_at: '2026-05-13T18:13:12+09:00'
updated_at: '2026-05-13T21:08:42+09:00'
status: needs-more-evidence
source_type: local-reproduction
scope: harnessops-core
maturity: investigated
relation: new
promotion_level: core-bugfix
source_feedback: FB0002
eval_cases:
- E0002
hypotheses:
- H0002
decisions:
- D0001
research_scans: []
classification:
  capability: lab_cli_error_handling
  failure_class: expected_user_error_traceback
guard:
  status: candidate
  path: harnessops-core:tests/test_cli/test_mvp_flow.py::test_lab_dossier_rejects_research_scan_without_traceback
investigation:
- created_at: '2026-05-13T21:08:03+09:00'
  kind: reproduction
  summary: 'Reproduced the current failure in runops upstream-lab: uv run --with-editable . hops lab dossier --from RS0001 exits 1 with a rich traceback from harnessops.cli.lab.dossier into harnessops.core.records._feedback_for_record, ending in ValueError: dossier は FB/E/H/D レコードから作成してください: RS0001.'
  evidence_ref: 'command: uv run --with-editable . hops lab dossier --from RS0001; guard target: harnessops-core:tests/test_cli/test_mvp_flow.py'
links:
  issue_url:
---

# IMP0002: FB0002: Lab dossier invalid source shows traceback

## Status

- status: needs-more-evidence
- maturity: investigated
- source_type: local-reproduction
- scope: harnessops-core
- relation: new
- promotion_level: core-bugfix
- source_feedback: `FB0002`
- linked_records: `FB0002`, `E0002`, `H0002`, `D0001`

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

- 2026-05-13T21:08:03+09:00 [reproduction] Reproduced the current failure in runops upstream-lab: uv run --with-editable . hops lab dossier --from RS0001 exits 1 with a rich traceback from harnessops.cli.lab.dossier into harnessops.core.records._feedback_for_record, ending in ValueError: dossier は FB/E/H/D レコードから作成してください: RS0001. (evidence: command: uv run --with-editable . hops lab dossier --from RS0001; guard target: harnessops-core:tests/test_cli/test_mvp_flow.py)

## Research Scans

research scan はまだありません。


## Evaluation

### E0002: E0002: FB0002-lab-dossier-invalid-source-shows-traceback を評価


- source: `harness-lab/records/eval-cases/E0002-fb0002-lab-dossier-invalid-source-shows-traceback.md`

- capability: lab_cli_error_handling

- failure_class: expected_user_error_traceback

- manual_eval_yml: `harness-lab/views/eval-results/E0002-manual-score.yml`
- manual_eval_md: `harness-lab/views/eval-results/E0002-manual-score.md`
- scores: impact=3, mechanism_clarity=5, evaluability=5, minimality=5, regression_risk=2, operator_burden=4, anti_theater=5, maintainability=4, privacy_sanitization_risk=5
- notes: Current behavior is confirmed failing: hops lab dossier --from RS0001 prints a rich traceback for an expected user error. The proposed fix is narrow and testable in HarnessOps core by adding a no-traceback CliRunner guard for RS research-scan input. Adoption is blocked until the upstream fix is implemented and the guard test passes; avoid broad ValueError handling that could hide internal corruption.


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

`harness-lab/views/eval-results/E0002-manual-score.md`

## Guard

- status: candidate
- path: harnessops-core:tests/test_cli/test_mvp_flow.py::test_lab_dossier_rejects_research_scan_without_traceback

## Links

- issue_url: 未設定

## Open Questions And Next Action

次の実装または評価ステップは、この dossier と紐づく正規化レコードを更新してから再生成してください。

## Decision Log

### D0001: D0001: needs-more-evidence H0002


Source: `harness-lab/records/decisions/D0001-needs-more-evidence-h0002.md`


# D0001: needs-more-evidence H0002

## 判断

needs-more-evidence

## 理由

Reproduction confirms the failure and E0002 is evaluable, but no HarnessOps core fix or passing guard has been recorded yet.

## 証拠

harness-lab/views/eval-results/E0002-manual-score.yml plus local reproduction command uv run --with-editable . hops lab dossier --from RS0001.

## 回帰リスク

The proposed handler could hide real dossier corruption if it catches broad ValueError without checking the domain condition.

## フォローアップ

Implement the HarnessOps core fix, add tests/test_cli/test_mvp_flow.py::test_lab_dossier_rejects_research_scan_without_traceback, run that guard and full validation, then reconsider adoption.

## 回帰ガード

harnessops-core:tests/test_cli/test_mvp_flow.py::test_lab_dossier_rejects_research_scan_without_traceback
