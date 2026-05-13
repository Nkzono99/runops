---
id: IMP0003
record_type: improvement_dossier
created_at: '2026-05-13T22:41:47+09:00'
updated_at: '2026-05-13T22:41:50+09:00'
status: active
source_type: observation
scope: harnessops-core
maturity: raw
relation: new
promotion_level: target-lab-case
source_feedback: FB0003
eval_cases: []
hypotheses: []
decisions: []
research_scans: []
classification:
  capability: role_scoped_agent_bridge
  failure_class: project_feedback_interface_too_broad
guard:
  status: not-defined
  path:
investigation: []
links:
  issue_url: https://github.com/Nkzono99/harnessops/issues/12
---

# IMP0003: FB0003: Project-side feedback-source repositories need a role-scoped interface

## Status

- status: active
- maturity: raw
- source_type: observation
- scope: harnessops-core
- relation: new
- promotion_level: target-lab-case
- source_feedback: `FB0003`
- linked_records: `FB0003`

## Source Observation

Source: `harness-lab/records/feedback/FB0003-project-side-feedback-source-repositories-need-a-role-scoped-interface.md`

# FB0003: Project-side feedback-source repositories need a role-scoped interface

## 概要

runops project directories initialize HarnessOps with profile=runops-project, which is feedback-source mode and writes harness-feedback/. In that role agents mainly need feedback capture/export plus lifecycle checks, but the generic agent bridge exposes broader harness-lab/eval/propose commands that belong to target or meta repositories. This blurs the boundary between project-side private feedback capture and upstream adoption decisions.

## 再現

In runops, runo init delegates to hops init --profile runops-project --with-agent-bridge. The runops-project profile is mode=feedback-source with path=harness-feedback, while the generated HarnessOps bridge lists lab capture/dossier/investigate/classify/new-eval-case/propose/eval/decide commands as general guidance.

## 期待する上流変更

HarnessOps should provide a project-side minimal interface or role-scoped bridge for feedback-source repositories, exposing init/doctor/update-harness/migrate and feedback commands while keeping lab/eval/propose/decide guidance scoped to upstream-lab or meta-lab repositories.

## Target Capability

- capability: role_scoped_agent_bridge
- failure_class: project_feedback_interface_too_broad

## Investigation

調査メモはまだありません。

## Research Scans

research scan はまだありません。


## Evaluation

評価ケースはまだありません。


## Hypotheses

仮説はまだありません。


## Evidence

評価結果はまだありません。

## Guard

- status: not-defined
- path: None

## Links

- issue_url: https://github.com/Nkzono99/harnessops/issues/12

## Open Questions And Next Action

次の実装または評価ステップは、この dossier と紐づく正規化レコードを更新してから再生成してください。

## Decision Log

判断レコードはまだありません。
