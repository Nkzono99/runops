<!-- harnessops により生成; source records が正本 -->
# 手動評価結果: E0002

送信元: `harness-lab/records/eval-cases/E0002-fb0002-lab-dossier-invalid-source-shows-traceback.md`

## スコア

- impact: 3
- mechanism_clarity: 5
- evaluability: 5
- minimality: 5
- regression_risk: 2
- operator_burden: 4
- anti_theater: 5
- maintainability: 4
- privacy_sanitization_risk: 5

## メモ

Current behavior is confirmed failing: hops lab dossier --from RS0001 prints a rich traceback for an expected user error. The proposed fix is narrow and testable in HarnessOps core by adding a no-traceback CliRunner guard for RS research-scan input. Adoption is blocked until the upstream fix is implemented and the guard test passes; avoid broad ValueError handling that could hide internal corruption.

## 評価ケース

- capability: lab_cli_error_handling
- failure_class: expected_user_error_traceback
- source_feedback: FB0002
