---
id: E0003
record_type: eval_case
created_at: '2026-05-14T04:12:57+09:00'
status: active
capability: role_scoped_agent_bridge
failure_class: project_feedback_interface_too_broad
source_feedback: FB0003
---

# E0003: FB0003-project-side-feedback-source-repositories-need-a-role-scoped-interface を評価

## フィクスチャ

- source_feedback: `harness-lab/records/feedback/FB0003-project-side-feedback-source-repositories-need-a-role-scoped-interface.md`
- fixture_dir: `harness-lab/records/eval-cases/fixtures/E0003`
- observation: runops project directories initialize HarnessOps with profile=runops-project, which is feedback-source mode and writes harness-feedback/. In that role agents mainly need feedback capture/export plus lifecycle checks, but the generic agent bridge exposes broader harness-lab/eval/propose commands that belong to target or meta repositories. This blurs the boundary between project-side private feedback capture and upstream adoption decisions.

## タスク

`role_scoped_agent_bridge` の `project_feedback_interface_too_broad` を減らす最小変更を設計または実装し、次の再現条件が解消されるか評価してください。

In runops, runo init delegates to hops init --profile runops-project --with-agent-bridge. The runops-project profile is mode=feedback-source with path=harness-feedback, while the generated HarnessOps bridge lists lab capture/dossier/investigate/classify/new-eval-case/propose/eval/decide commands as general guidance.

## 期待される挙動

HarnessOps should provide a project-side minimal interface or role-scoped bridge for feedback-source repositories, exposing init/doctor/update-harness/migrate and feedback commands while keeping lab/eval/propose/decide guidance scoped to upstream-lab or meta-lab repositories.

## 合格基準

- `project_feedback_interface_too_broad` の再現条件が検出または防止される。
- 提案または実装される変更が source feedback の期待変更に対応している。
- `hops eval --case E0003 --manual` の score と notes で採用判断に必要な証拠を説明できる。
- 非公開プロジェクト詳細を追加で要求しない。

## 不合格基準

- `project_feedback_interface_too_broad` の再現条件を見逃す。
- source feedback の期待変更と無関係な改善案になる。
- 評価が yml score へ記録されず、採用判断の証拠として追えない。
- 再現または判断に非公開文脈が必要になる。
