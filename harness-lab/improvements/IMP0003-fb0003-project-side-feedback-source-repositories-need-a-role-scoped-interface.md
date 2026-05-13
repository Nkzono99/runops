---
id: IMP0003
record_type: improvement_dossier
created_at: '2026-05-13T22:41:47+09:00'
updated_at: '2026-05-14T04:13:41+09:00'
status: adopted
source_type: external-resolution
scope: harnessops-core
maturity: adopted
relation: new
promotion_level: target-lab-case
source_feedback: FB0003
eval_cases:
- E0003
hypotheses:
- H0003
decisions:
- D0002
research_scans: []
classification:
  capability: role_scoped_agent_bridge
  failure_class: project_feedback_interface_too_broad
guard:
  status: implemented
  path: harnessops-core:tests/test_agent_harness_contract.py::test_generated_bridge_scopes_feedback_source_interface
investigation:
- created_at: '2026-05-14T04:12:47+09:00'
  kind: external-resolution
  summary: 'HarnessOps issue #12 was closed as resolved in v0.1.8: feedback-source/local-and-feedback repos now receive a project-side interface focused on lifecycle and feedback capture/export, while lab/eval/propose/decide guidance stays in upstream/meta lab repos. Installed harnessops 0.1.9 reproduces the scoped project bridge and upstream main carries tests/test_agent_harness_contract.py::test_generated_bridge_scopes_feedback_source_interface.'
  evidence_ref: https://github.com/Nkzono99/harnessops/issues/12#issuecomment-4442791945
links:
  issue_url: https://github.com/Nkzono99/harnessops/issues/12
---

# IMP0003: FB0003: Project-side feedback-source repositories need a role-scoped interface

## Status

- status: adopted
- maturity: adopted
- source_type: external-resolution
- scope: harnessops-core
- relation: new
- promotion_level: target-lab-case
- source_feedback: `FB0003`
- linked_records: `FB0003`, `E0003`, `H0003`, `D0002`

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

- 2026-05-14T04:12:47+09:00 [external-resolution] HarnessOps issue #12 was closed as resolved in v0.1.8: feedback-source/local-and-feedback repos now receive a project-side interface focused on lifecycle and feedback capture/export, while lab/eval/propose/decide guidance stays in upstream/meta lab repos. Installed harnessops 0.1.9 reproduces the scoped project bridge and upstream main carries tests/test_agent_harness_contract.py::test_generated_bridge_scopes_feedback_source_interface. (evidence: https://github.com/Nkzono99/harnessops/issues/12#issuecomment-4442791945)

## Research Scans

research scan はまだありません。


## Evaluation

### E0003: E0003: FB0003-project-side-feedback-source-repositories-need-a-role-scoped-interface を評価


- source: `harness-lab/records/eval-cases/E0003-fb0003-project-side-feedback-source-repositories-need-a-role-scoped-interface.md`

- capability: role_scoped_agent_bridge

- failure_class: project_feedback_interface_too_broad

- manual_eval_yml: `harness-lab/views/eval-results/E0003-manual-score.yml`
- manual_eval_md: `harness-lab/views/eval-results/E0003-manual-score.md`
- scores: impact=3, mechanism_clarity=5, evaluability=5, minimality=5, regression_risk=1, operator_burden=5, anti_theater=5, maintainability=5, privacy_sanitization_risk=5
- notes: External fix verified: harnessops#12 is closed with v0.1.8 resolution notes, installed harnessops 0.1.9 generates a feedback-source project bridge without lab/propose/decide commands, and upstream main includes tests/test_agent_harness_contract.py::test_generated_bridge_scopes_feedback_source_interface.


## Hypotheses

### H0003: H0003: E0003-fb0003-project-side-feedback-source-repositories-need-a-role-scoped-interface の仮説


Source: `harness-lab/records/hypotheses/H0003-e0003-fb0003-project-side-feedback-source-repositories-need-a-role-scoped-interface.md`


# H0003: E0003-fb0003-project-side-feedback-source-repositories-need-a-role-scoped-interface の仮説

## 仮説

Upstream HarnessOps role-scoped agent bridge resolves FB0003 by giving feedback-source project repositories only lifecycle and feedback capture/export guidance.

## メカニズム

The bridge generator selects a project-side body and feedback-source skill allowlist for feedback-source/local-and-feedback modes, while upstream/meta lab modes keep lab, eval, propose, and decide guidance.

## 最小実装

No runops code change is needed in this target repo; sync the local lab record to the upstream resolution and rely on harnessops v0.1.8+ update-harness for stale project bridges.

## 代替案: 削除または統合

Leave project repos with the generic lab bridge guidance and rely on agents to infer role boundaries from project.toml, which keeps the privacy/adoption boundary ambiguous.

## 期待される利点

Project repositories get a smaller, role-appropriate interface that reduces accidental harness-lab/adoption work in private feedback-source repos.

## 想定される欠点

Existing project repos with stale generated bridge files still need update-harness before they receive the scoped guidance.

## 評価計画

Verify harnessops#12 is closed, installed harnessops 0.1.9 generates a feedback-source bridge without lab/propose/decide commands, and upstream guard test test_generated_bridge_scopes_feedback_source_interface covers the behavior.

## 中止基準

Reopen if a feedback-source generated bridge again includes lab/eval/propose/decide guidance, or if the skill allowlist omits required feedback capture/export commands.


## Evidence

`harness-lab/views/eval-results/E0003-manual-score.md`

## Guard

- status: implemented
- path: harnessops-core:tests/test_agent_harness_contract.py::test_generated_bridge_scopes_feedback_source_interface

## Links

- issue_url: https://github.com/Nkzono99/harnessops/issues/12

## Open Questions And Next Action

次の実装または評価ステップは、この dossier と紐づく正規化レコードを更新してから再生成してください。

## Decision Log

### D0002: D0002: adopted H0003


Source: `harness-lab/records/decisions/D0002-adopted-h0003.md`


# D0002: adopted H0003

## 判断

adopted

## 理由

Upstream HarnessOps now role-scopes generated project bridges, matching FB0003's expected change.

## 証拠

harnessops#12 closed as resolved in v0.1.8; installed harnessops 0.1.9 project bridge omits lab/propose/decide commands; upstream guard tests/test_agent_harness_contract.py::test_generated_bridge_scopes_feedback_source_interface asserts the scoped behavior.

## 回帰リスク

Low for runops: this is local lab state sync only. Residual risk is stale generated bridge files in already initialized project repositories until update-harness is run.

## フォローアップ

Project repositories with stale generated HarnessOps bridge files should run uvx --refresh-package harnessops --from harnessops hops update-harness --agent-bridge.

## 回帰ガード

harnessops-core:tests/test_agent_harness_contract.py::test_generated_bridge_scopes_feedback_source_interface
