---
id: D0001
record_type: decision
created_at: '2026-05-13T21:08:31+09:00'
status: needs-more-evidence
source: H0002
evidence:
  summary: harness-lab/views/eval-results/E0002-manual-score.yml plus local reproduction command uv run --with-editable . hops lab dossier --from RS0001.
  guard_path: harnessops-core:tests/test_cli/test_mvp_flow.py::test_lab_dossier_rejects_research_scan_without_traceback
---

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
