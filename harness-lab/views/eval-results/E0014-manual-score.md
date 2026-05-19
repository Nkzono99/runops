<!-- harnessops により生成; source records が正本 -->
# 手動評価結果: E0014

送信元: `harness-lab/records/eval-cases/E0014-fb0014-hops-github-flow-merge-json-post-merge.md`

## スコア

- impact: 4
- mechanism_clarity: 5
- evaluability: 5
- minimality: 4
- regression_risk: 2
- operator_burden: 5
- anti_theater: 5
- maintainability: 4
- privacy_sanitization_risk: 5

## メモ

Consolidated under the GitHub Flow finalization bundle. Post-merge JSON has direct finalization value because it removes the extra gh pr view call after merge; implementation should separate pre-merge and post-merge fields so successful merges cannot look OPEN.

## 評価ケース

- capability: unclassified
- failure_class: unclassified
- source_feedback: FB0014
