---
id: IMP0011
record_type: improvement_dossier
created_at: '2026-05-17T04:12:35+09:00'
updated_at: '2026-05-20T04:26:59+09:00'
status: needs-more-evidence
source_type: observation
scope: harnessops-core
maturity: investigated
relation: extends
promotion_level: core-workflow
source_feedback: FB0011
eval_cases:
- E0011
hypotheses:
- H0011
decisions:
- D0012
research_scans: []
classification:
  capability: unclassified
  failure_class: unclassified
guard:
  status: not-defined
  path:
investigation:
- created_at: '2026-05-20T04:24:44+09:00'
  kind: queue-consolidation
  summary: Priority lane consolidated this as part of the GitHub Flow finalization bundle with IMP0010, IMP0013, and IMP0014. It is the shared inspection/checks portion of delegated PR finalization, not a separate target-repo feature.
  evidence_ref: RS0002; IMP0009; .harnessops/cache/steward-runs/20260520-040215-980747f.json
links:
  issue_url: https://github.com/Nkzono99/runops/issues/85
---

# IMP0011: FB0011: hops github-flow で PR view/checks/watch をサポートする

## Status

- status: needs-more-evidence
- maturity: investigated
- source_type: observation
- scope: harnessops-core
- relation: extends
- promotion_level: core-workflow
- source_feedback: `FB0011`
- linked_records: `FB0011`, `E0011`, `H0011`, `D0012`

## Source Observation

Source: `harness-lab/records/feedback/FB0011-hops-github-flow-pr-view-checks-watch.md`

# FB0011: hops github-flow で PR view/checks/watch をサポートする

## 概要

GitHub issue: https://github.com/Nkzono99/runops/issues/85
author: Nkzono99
labels: enhancement, codex
created_at: 2026-05-16T05:06:05Z
updated_at: 2026-05-16T05:06:05Z

## Issue本文
## 背景

`hops github-flow publish/pr/merge` は automation branch push、PR 作成、merge の標準経路になっている。一方で、merge 前の状態確認ではまだ `gh pr view`、`gh pr checks --watch`、`gh pr checks` を直接呼んでいる。

GitHub Flow を HOPS CLI に委譲するなら、PR 状態確認と required checks の watch/check も `hops github-flow` 配下で扱えると、automation lane が一貫する。

## 提案

`hops github-flow` に PR inspection/check commands を追加する。

候補:

- `hops github-flow view [PR] --json`
  - state, mergeable, mergeStateStatus, draft, base/head, labels, URL, checks summary を返す
- `hops github-flow checks [PR] --required --json`
  - required checks の pass/fail/pending を返す
- `hops github-flow checks [PR] --watch --interval 10`
  - CI 完了まで watch し、失敗または timeout を machine-readable に返す

## 受け入れ基準

- `gh pr view` と `gh pr checks` を automation script 側で直接呼ばずに、HOPS CLI 経由で PR 状態と checks を確認できる。
- `--json` output が lane result / steward finalization に取り込める形になっている。
- required checks が pending / failed / missing / skipped の場合を区別できる。
- `hops github-flow merge --require-checks` と整合する check 判定を使う。
- timeout または GitHub API/CLI failure 時に、PR URL と次の確認コマンドが分かる。

## 補足

2026-05-16 の runops harness update PR #83 では、HOPS の `pr` / `merge` は使えたが、merge 前の watch と view は `gh pr view` / `gh pr checks --watch` を直接実行した。

## 再現

送信元フィードバックバンドルを参照してください。

## 期待する上流変更

送信元フィードバックバンドルを参照してください。

## Target Capability

- capability: unclassified
- failure_class: unclassified

## Investigation

- 2026-05-20T04:24:44+09:00 [queue-consolidation] Priority lane consolidated this as part of the GitHub Flow finalization bundle with IMP0010, IMP0013, and IMP0014. It is the shared inspection/checks portion of delegated PR finalization, not a separate target-repo feature. (evidence: RS0002; IMP0009; .harnessops/cache/steward-runs/20260520-040215-980747f.json)

## Research Scans

research scan はまだありません。


## Evaluation

### E0011: E0011: FB0011-hops-github-flow-pr-view-checks-watch を評価


- source: `harness-lab/records/eval-cases/E0011-fb0011-hops-github-flow-pr-view-checks-watch.md`

- capability: unclassified

- failure_class: unclassified

- manual_eval_yml: `harness-lab/views/eval-results/E0011-manual-score.yml`
- manual_eval_md: `harness-lab/views/eval-results/E0011-manual-score.md`
- scores: impact=4, mechanism_clarity=4, evaluability=5, minimality=3, regression_risk=3, operator_burden=5, anti_theater=5, maintainability=4, privacy_sanitization_risk=5
- notes: Consolidated under the GitHub Flow finalization bundle. View/checks/watch support has high automation impact because finalization lanes currently need direct gh pr view/checks calls; complexity is higher because required-check states and watch timeout behavior must match merge semantics.


## Hypotheses

### H0011: H0011: E0011-fb0011-hops-github-flow-pr-view-checks-watch の仮説


Source: `harness-lab/records/hypotheses/H0011-e0011-fb0011-hops-github-flow-pr-view-checks-watch.md`


# H0011: E0011-fb0011-hops-github-flow-pr-view-checks-watch の仮説

## 仮説

Adding HOPS PR view and checks commands will let automation lanes inspect PR state without direct gh calls.

## メカニズム

Expose github-flow view and checks subcommands that wrap gh pr view/checks, normalize required-check states, and support JSON and watch modes.

## 最小実装

Add view and checks commands, reuse existing merge check logic, implement timeout-aware watch output, and test pending, failed, passed, missing, and skipped states.

## 代替案: 削除または統合

Keep lane scripts calling gh pr view and gh pr checks directly, which duplicates GitHub behavior outside HOPS.

## 期待される利点

Finalization lanes can rely on one delegated interface for publish, PR creation, status checks, and merge decisions.

## 想定される欠点

Watch behavior can hang or hide API errors unless timeouts and next-step commands are explicit.

## 評価計画

Use mocked gh outputs for PR metadata and check states, then verify JSON fields and watch exit behavior match merge --require-checks semantics.

## 中止基準

Reject if the commands produce ambiguous check states or require repo-specific lane code to interpret raw gh output.


## Evidence

`harness-lab/views/eval-results/E0011-manual-score.md`

## Guard

- status: not-defined
- path: None

## Links

- issue_url: https://github.com/Nkzono99/runops/issues/85

## Open Questions And Next Action

次の実装または評価ステップは、この dossier と紐づく正規化レコードを更新してから再生成してください。

## Decision Log

### D0012: D0012: needs-more-evidence H0011


Source: `harness-lab/records/decisions/D0012-needs-more-evidence-h0011.md`


# D0012: needs-more-evidence H0011

## 判断

needs-more-evidence

## 理由

Worth pursuing upstream, but it needs HarnessOps core implementation and mocked check-state guards before any issue can be closed.

## 証拠

E0011 manual score; RS0002/IMP0009 consolidation context; supervisor run 20260520-040215-980747f

## 回帰リスク

Medium: ambiguous pending/failed/missing/skipped check normalization could make automation merge decisions unsafe.

## フォローアップ

Implement github-flow view and checks/watch in HarnessOps, reuse merge required-check semantics, and guard pending, failed, passed, missing, skipped, and timeout JSON.

## 回帰ガード

harnessops-core:tests/test_cli/test_github_flow.py::test_checks_required_states_and_watch_json
