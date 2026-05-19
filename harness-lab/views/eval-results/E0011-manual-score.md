<!-- harnessops により生成; source records が正本 -->
# 手動評価結果: E0011

送信元: `harness-lab/records/eval-cases/E0011-fb0011-hops-github-flow-pr-view-checks-watch.md`

## スコア

- impact: 4
- mechanism_clarity: 4
- evaluability: 5
- minimality: 3
- regression_risk: 3
- operator_burden: 5
- anti_theater: 5
- maintainability: 4
- privacy_sanitization_risk: 5

## メモ

Consolidated under the GitHub Flow finalization bundle. View/checks/watch support has high automation impact because finalization lanes currently need direct gh pr view/checks calls; complexity is higher because required-check states and watch timeout behavior must match merge semantics.

## 評価ケース

- capability: unclassified
- failure_class: unclassified
- source_feedback: FB0011
