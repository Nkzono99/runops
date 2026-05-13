---
id: H0003
record_type: hypothesis
created_at: '2026-05-14T04:13:14+09:00'
status: proposed
target_capability: role_scoped_agent_bridge
source_eval_case: E0003
---

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
