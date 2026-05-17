<!-- harnessops により生成; source records が正本 -->
# 手動評価結果: E0015

送信元: `harness-lab/records/eval-cases/E0015-fb0015-steward-lane-artifacts-need-durable-schema.md`

## スコア

- impact: 4
- mechanism_clarity: 4
- evaluability: 4
- minimality: 3
- regression_risk: 3
- operator_burden: 4
- anti_theater: 4
- maintainability: 3
- privacy_sanitization_risk: 5

## メモ

Priority-lane evidence supports the problem: run 20260518 used structured artifacts.meta_scan as a handoff from open-meta to invention and priority, while current review context only surfaces RS0003 after it is promoted. The proposed fix is evaluable with steward-run fixtures for required fields, malformed artifact rejection, and expiry/promotion behavior. Adoption should wait for HarnessOps core implementation because an artifact store can become a second source of truth if schema, expiry, and promotion boundaries are not enforced.

## 評価ケース

- capability: steward_lane_handoff
- failure_class: transient_lane_artifact_loss
- source_feedback: FB0015
