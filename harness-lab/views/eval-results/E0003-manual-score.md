<!-- harnessops により生成; source records が正本 -->
# 手動評価結果: E0003

送信元: `harness-lab/records/eval-cases/E0003-fb0003-project-side-feedback-source-repositories-need-a-role-scoped-interface.md`

## スコア

- impact: 3
- mechanism_clarity: 5
- evaluability: 5
- minimality: 5
- regression_risk: 1
- operator_burden: 5
- anti_theater: 5
- maintainability: 5
- privacy_sanitization_risk: 5

## メモ

External fix verified: harnessops#12 is closed with v0.1.8 resolution notes, installed harnessops 0.1.9 generates a feedback-source project bridge without lab/propose/decide commands, and upstream main includes tests/test_agent_harness_contract.py::test_generated_bridge_scopes_feedback_source_interface.

## 評価ケース

- capability: role_scoped_agent_bridge
- failure_class: project_feedback_interface_too_broad
- source_feedback: FB0003
