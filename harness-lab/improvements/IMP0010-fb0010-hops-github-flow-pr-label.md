---
id: IMP0010
record_type: improvement_dossier
created_at: '2026-05-17T04:12:25+09:00'
updated_at: '2026-05-20T04:26:57+09:00'
status: needs-more-evidence
source_type: observation
scope: harnessops-core
maturity: investigated
relation: extends
promotion_level: core-workflow
source_feedback: FB0010
eval_cases:
- E0010
hypotheses:
- H0010
decisions:
- D0011
research_scans: []
classification:
  capability: unclassified
  failure_class: unclassified
guard:
  status: not-defined
  path:
investigation:
- created_at: '2026-05-20T04:24:40+09:00'
  kind: queue-consolidation
  summary: Priority lane consolidated this as part of the GitHub Flow finalization bundle with IMP0011, IMP0013, and IMP0014. Candidate taxonomy is capability=github_flow_finalization and failure_class=delegated_pr_finalization_escape_hatch, but the current HOPS classify CLI cannot backfill capability/failure_class without direct overlay edits.
  evidence_ref: RS0002; IMP0009; .harnessops/cache/steward-runs/20260520-040215-980747f.json
links:
  issue_url: https://github.com/Nkzono99/runops/issues/84
---

# IMP0010: FB0010: hops github-flow pr で label 指定をサポートする

## Status

- status: needs-more-evidence
- maturity: investigated
- source_type: observation
- scope: harnessops-core
- relation: extends
- promotion_level: core-workflow
- source_feedback: `FB0010`
- linked_records: `FB0010`, `E0010`, `H0010`, `D0011`

## Source Observation

Source: `harness-lab/records/feedback/FB0010-hops-github-flow-pr-label.md`

# FB0010: hops github-flow pr で label 指定をサポートする

## 概要

GitHub issue: https://github.com/Nkzono99/runops/issues/84
author: Nkzono99
labels: enhancement, codex
created_at: 2026-05-16T05:06:05Z
updated_at: 2026-05-16T05:06:05Z

## Issue本文
## 背景

`hops github-flow pr` は daily steward / automation lane から PR を作る標準経路になっているが、現状は PR 作成時に label を付ける option がない。そのため automation では PR 作成後に別途 `gh pr edit --add-label ...` を呼ぶ必要があり、GitHub Flow を HOPS CLI に委譲する方針から少しはみ出る。

## 提案

`hops github-flow pr` に label 指定を追加する。

候補:

- `--label <name>` を複数回指定可能にする
- または `--labels "codex,enhancement"` をサポートする
- 既存 label がない場合の挙動を明確化する（失敗、warning、または作成しない）

## 受け入れ基準

- `hops github-flow pr --label codex --label enhancement ...` のように PR 作成と同時に label を付けられる。
- PR 作成後の別 `gh pr edit --add-label` 呼び出しが不要になる。
- label 付与に失敗した場合、PR URL と失敗理由が分かる形で返る。
- `--json` output に label 付与結果が含まれる。
- 既存の PR 作成挙動と後方互換性がある。

## 補足

2026-05-16 の runops harness update PR 作成時、`hops github-flow pr` 後に手動で `gh pr edit 83 --add-label codex` を実行した。

## 再現

送信元フィードバックバンドルを参照してください。

## 期待する上流変更

送信元フィードバックバンドルを参照してください。

## Target Capability

- capability: unclassified
- failure_class: unclassified

## Investigation

- 2026-05-20T04:24:40+09:00 [queue-consolidation] Priority lane consolidated this as part of the GitHub Flow finalization bundle with IMP0011, IMP0013, and IMP0014. Candidate taxonomy is capability=github_flow_finalization and failure_class=delegated_pr_finalization_escape_hatch, but the current HOPS classify CLI cannot backfill capability/failure_class without direct overlay edits. (evidence: RS0002; IMP0009; .harnessops/cache/steward-runs/20260520-040215-980747f.json)

## Research Scans

research scan はまだありません。


## Evaluation

### E0010: E0010: FB0010-hops-github-flow-pr-label を評価


- source: `harness-lab/records/eval-cases/E0010-fb0010-hops-github-flow-pr-label.md`

- capability: unclassified

- failure_class: unclassified

- manual_eval_yml: `harness-lab/views/eval-results/E0010-manual-score.yml`
- manual_eval_md: `harness-lab/views/eval-results/E0010-manual-score.md`
- scores: impact=4, mechanism_clarity=5, evaluability=5, minimality=4, regression_risk=2, operator_burden=4, anti_theater=5, maintainability=4, privacy_sanitization_risk=5
- notes: Consolidated under the GitHub Flow finalization bundle. Label support is a narrow upstream HOPS extension that removes post-PR gh pr edit calls; classify capability/failure_class backfill is still blocked by the current HOPS CLI, so adoption should wait for HarnessOps core implementation and guard evidence.


## Hypotheses

### H0010: H0010: E0010-fb0010-hops-github-flow-pr-label の仮説


Source: `harness-lab/records/hypotheses/H0010-e0010-fb0010-hops-github-flow-pr-label.md`


# H0010: E0010-fb0010-hops-github-flow-pr-label の仮説

## 仮説

Adding repeatable label options to hops github-flow pr will keep automation PR creation delegated to HOPS while preserving current behavior.

## メカニズム

Parse zero or more labels in the pr command, apply them during or immediately after PR creation, and include structured label results in JSON output.

## 最小実装

Add label options, wire them into the GitHub Flow PR helper, report label success or failure, and test labeled plus unlabeled PR paths.

## 代替案: 削除または統合

Continue calling gh pr edit after hops github-flow pr, which keeps label handling outside the delegated HOPS path.

## 期待される利点

Automation finalization can create labeled PRs through one HOPS command and produce clearer machine-readable reports.

## 想定される欠点

Label application may fail after PR creation, so output must preserve the PR URL and exact label failure.

## 評価計画

Use a mocked gh fixture for PR creation with multiple labels, missing labels, and no labels; assert JSON includes label results without breaking existing output.

## 中止基準

Reject if label support requires direct gh calls in lane scripts or changes current unlabeled PR behavior.


## Evidence

`harness-lab/views/eval-results/E0010-manual-score.md`

## Guard

- status: not-defined
- path: None

## Links

- issue_url: https://github.com/Nkzono99/runops/issues/84

## Open Questions And Next Action

次の実装または評価ステップは、この dossier と紐づく正規化レコードを更新してから再生成してください。

## Decision Log

### D0011: D0011: needs-more-evidence H0010


Source: `harness-lab/records/decisions/D0011-needs-more-evidence-h0010.md`


# D0011: needs-more-evidence H0010

## 判断

needs-more-evidence

## 理由

Clear upstream HOPS finalization feature, but no HarnessOps core implementation or passing guard exists in this target repo run.

## 証拠

E0010 manual score; RS0002/IMP0009 consolidation context; supervisor run 20260520-040215-980747f

## 回帰リスク

Low-to-medium: label application can fail after PR creation, so JSON must preserve the PR URL and label failure details without changing unlabeled behavior.

## フォローアップ

Implement label options in HarnessOps github-flow pr, include label result JSON, run mocked labeled/unlabeled PR guards, then backfill capability/failure_class through a supported command.

## 回帰ガード

harnessops-core:tests/test_cli/test_github_flow.py::test_pr_applies_labels_and_reports_json
