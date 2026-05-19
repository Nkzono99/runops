---
id: IMP0014
record_type: improvement_dossier
created_at: '2026-05-17T04:13:04+09:00'
updated_at: '2026-05-20T04:27:05+09:00'
status: needs-more-evidence
source_type: observation
scope: harnessops-core
maturity: investigated
relation: extends
promotion_level: core-workflow
source_feedback: FB0014
eval_cases:
- E0014
hypotheses:
- H0014
decisions:
- D0014
research_scans: []
classification:
  capability: unclassified
  failure_class: unclassified
guard:
  status: not-defined
  path:
investigation:
- created_at: '2026-05-20T04:24:53+09:00'
  kind: queue-consolidation
  summary: Priority lane consolidated this as part of the GitHub Flow finalization bundle with IMP0010, IMP0011, and IMP0013. It is the post-merge reporting portion of delegated PR finalization and should be evaluated with the same upstream guard family.
  evidence_ref: RS0002; IMP0009; .harnessops/cache/steward-runs/20260520-040215-980747f.json
links:
  issue_url: https://github.com/Nkzono99/runops/issues/88
---

# IMP0014: FB0014: hops github-flow merge --json が post-merge 状態を返すようにする

## Status

- status: needs-more-evidence
- maturity: investigated
- source_type: observation
- scope: harnessops-core
- relation: extends
- promotion_level: core-workflow
- source_feedback: `FB0014`
- linked_records: `FB0014`, `E0014`, `H0014`, `D0014`

## Source Observation

Source: `harness-lab/records/feedback/FB0014-hops-github-flow-merge-json-post-merge.md`

# FB0014: hops github-flow merge --json が post-merge 状態を返すようにする

## 概要

GitHub issue: https://github.com/Nkzono99/runops/issues/88
author: Nkzono99
labels: enhancement, codex
created_at: 2026-05-16T05:07:30Z
updated_at: 2026-05-16T05:07:30Z

## Issue本文
## 背景

`hops github-flow merge --json` は PR merge 前の `gh pr view` 結果を `pr` field に入れて返しているため、実際には merge 済みでも JSON 上の `pr.state` が `OPEN` のまま残る。automation lane では merge 後に別途 `gh pr view --json state,mergedAt,mergeCommit` を呼んで確認する必要があった。

GitHub Flow を HOPS CLI に委譲するなら、merge command 自体の JSON が post-merge 状態を machine-readable に返す方が扱いやすい。

## 提案

`hops github-flow merge --json` の戻り値に、merge 後の PR 状態を含める。

候補 fields:

- `merged: true/false`
- `pr.number`, `pr.url`, `pr.state`
- `mergedAt`
- `mergeCommit.oid`
- `headRefName`, `baseRefName`
- `deletedBranch: true/false`
- `checksSummary`

## 受け入れ基準

- merge 成功後の JSON で `state=MERGED` または `merged=true` が確認できる。
- merge commit SHA が JSON から取得できる。
- branch deletion の成功/失敗が JSON から分かる。
- merge 前 snapshot と merge 後 state が混ざる場合は、field 名で区別される（例: `pre_merge_pr` / `post_merge_pr`）。
- automation が追加の `gh pr view` を呼ばずに final report を作れる。

## 再現メモ

runops PR #83 の merge 時、`hops github-flow merge 83 --require-checks --delete-branch --json` は merge 自体に成功したが、返却 JSON の `pr.state` は pre-merge の `OPEN` だった。

## 再現

送信元フィードバックバンドルを参照してください。

## 期待する上流変更

送信元フィードバックバンドルを参照してください。

## Target Capability

- capability: unclassified
- failure_class: unclassified

## Investigation

- 2026-05-20T04:24:53+09:00 [queue-consolidation] Priority lane consolidated this as part of the GitHub Flow finalization bundle with IMP0010, IMP0011, and IMP0013. It is the post-merge reporting portion of delegated PR finalization and should be evaluated with the same upstream guard family. (evidence: RS0002; IMP0009; .harnessops/cache/steward-runs/20260520-040215-980747f.json)

## Research Scans

research scan はまだありません。


## Evaluation

### E0014: E0014: FB0014-hops-github-flow-merge-json-post-merge を評価


- source: `harness-lab/records/eval-cases/E0014-fb0014-hops-github-flow-merge-json-post-merge.md`

- capability: unclassified

- failure_class: unclassified

- manual_eval_yml: `harness-lab/views/eval-results/E0014-manual-score.yml`
- manual_eval_md: `harness-lab/views/eval-results/E0014-manual-score.md`
- scores: impact=4, mechanism_clarity=5, evaluability=5, minimality=4, regression_risk=2, operator_burden=5, anti_theater=5, maintainability=4, privacy_sanitization_risk=5
- notes: Consolidated under the GitHub Flow finalization bundle. Post-merge JSON has direct finalization value because it removes the extra gh pr view call after merge; implementation should separate pre-merge and post-merge fields so successful merges cannot look OPEN.


## Hypotheses

### H0014: H0014: E0014-fb0014-hops-github-flow-merge-json-post-merge の仮説


Source: `harness-lab/records/hypotheses/H0014-e0014-fb0014-hops-github-flow-merge-json-post-merge.md`


# H0014: E0014-fb0014-hops-github-flow-merge-json-post-merge の仮説

## 仮説

Returning post-merge PR state from hops github-flow merge --json will eliminate extra gh pr view calls after a successful merge.

## メカニズム

After merge succeeds, fetch or derive the merged PR state, merge commit, branch deletion result, and checks summary, separating pre-merge and post-merge fields when needed.

## 最小実装

Extend merge JSON output with merged, post_merge_pr, mergeCommit, deletedBranch, and checks summary fields while preserving existing fields for compatibility.

## 代替案: 削除または統合

Leave merge JSON as a pre-merge snapshot and require automation lanes to call gh pr view after every merge.

## 期待される利点

Final reports can be generated directly from HOPS merge output with less duplicated GitHub inspection logic.

## 想定される欠点

A second PR fetch may fail after merge; output needs to preserve merge success while reporting post-merge lookup failure separately.

## 評価計画

Use mocked merge and post-merge view outputs to assert state MERGED, merge commit SHA, branch deletion status, and compatibility with existing JSON fields.

## 中止基準

Reject if successful merges can be reported as open without an explicit pre_merge field, or if post-merge lookup failure masks merge success.


## Evidence

`harness-lab/views/eval-results/E0014-manual-score.md`

## Guard

- status: not-defined
- path: None

## Links

- issue_url: https://github.com/Nkzono99/runops/issues/88

## Open Questions And Next Action

次の実装または評価ステップは、この dossier と紐づく正規化レコードを更新してから再生成してください。

## Decision Log

### D0014: D0014: needs-more-evidence H0014


Source: `harness-lab/records/decisions/D0014-needs-more-evidence-h0014.md`


# D0014: needs-more-evidence H0014

## 判断

needs-more-evidence

## 理由

Strong upstream candidate, but needs core code and guard evidence for post-merge state and lookup-failure handling.

## 証拠

E0014 manual score; RS0002/IMP0009 consolidation context; supervisor run 20260520-040215-980747f

## 回帰リスク

Low-to-medium: post-merge lookup can fail after a successful merge, so output must preserve merge success and report lookup failure separately.

## フォローアップ

Extend HarnessOps merge JSON with merged/post_merge_pr/mergeCommit/deletedBranch/checks summary fields and guard compatibility with existing JSON.

## 回帰ガード

harnessops-core:tests/test_cli/test_github_flow.py::test_merge_json_includes_post_merge_state
