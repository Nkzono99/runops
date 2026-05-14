---
id: E0005
record_type: eval_case
created_at: '2026-05-14T11:15:05+09:00'
status: active
capability: mcp_analysis_result_inspection
failure_class: missing_paper_facing_analysis_artifact_inspect
source_feedback: FB0005
---

# E0005: FB0005-mcp-analysis-artifacts-survey-summary-paper-inspect を評価

## フィクスチャ

- source_feedback: `harness-lab/records/feedback/FB0005-mcp-analysis-artifacts-survey-summary-paper-inspect.md`
- fixture_dir: `harness-lab/records/eval-cases/fixtures/E0005`
- observation: GitHub issue: https://github.com/Nkzono99/runops/issues/68
author: Nkzono99
labels: なし
created_at: 2026-05-14T01:53:14Z
updated_at: 2026-05-14T01:53:14Z

## タスク

`mcp_analysis_result_inspection` の `missing_paper_facing_analysis_artifact_inspect` を減らす最小変更を設計または実装し、次の再現条件が解消されるか評価してください。

送信元フィードバックバンドルを参照してください。

## 期待される挙動

送信元フィードバックバンドルを参照してください。

## 合格基準

- `missing_paper_facing_analysis_artifact_inspect` の再現条件が検出または防止される。
- 提案または実装される変更が source feedback の期待変更に対応している。
- `hops eval --case E0005 --manual` の score と notes で採用判断に必要な証拠を説明できる。
- 非公開プロジェクト詳細を追加で要求しない。

## 不合格基準

- `missing_paper_facing_analysis_artifact_inspect` の再現条件を見逃す。
- source feedback の期待変更と無関係な改善案になる。
- 評価が yml score へ記録されず、採用判断の証拠として追えない。
- 再現または判断に非公開文脈が必要になる。
