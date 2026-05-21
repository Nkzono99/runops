---
id: IMP0016
record_type: improvement_dossier
created_at: '2026-05-21T04:17:15+09:00'
updated_at: '2026-05-22T04:12:29+09:00'
status: needs-more-evidence
source_type: local-reproduction
scope: harnessops-core
maturity: investigated
relation: extends
promotion_level: core-workflow
source_feedback: FB0016
eval_cases:
- E0016
hypotheses:
- H0016
decisions:
- D0016
research_scans: []
classification:
  capability: target_intent_context
  failure_class: steward_target_context_inference
guard:
  status: candidate
  path: harnessops-core:tests/test_steward/test_target_intent_context.py::test_pre_lane_context_digest_cites_target_owned_gates
investigation:
- created_at: '2026-05-21T04:17:55+09:00'
  kind: workflow-design
  summary: 'Priority review connected RS0005 to a concrete upstream workflow gap: runops documents target-owned context surfaces and gates, but autonomous steward lanes only receive lane-local summaries unless a supervisor passes those target facts explicitly. In a runops source checkout, runo context --json correctly fails without runops.toml, so a HOPS pre-lane digest must treat project context as an optional target-owned input and cite fallback docs/rules rather than persisting inferred target memory.'
  evidence_ref: RS0005; uv run runo context --json ProjectNotFoundError in source checkout; README.md:94-121; docs/agent-user-guide.md:20,70,144-166,197; docs/layers/interface.md:51-55,109-110,127,154-159; docs/mcp.md:35-46,142-143; .codex/rules/commands.md:13
- created_at: '2026-05-22T04:12:28+09:00'
  kind: codebase
  summary: 'Open-meta mode-map idea extends pre-lane target intent: README/docs split agent work across experiment operations, paper-support exports, harness maintenance, and upstream feedback, but no concise mode map tells an autonomous lane which posture and safety gates apply before acting.'
  evidence_ref: README.md:163-174;docs/agent-user-guide.md:28-44;docs/mcp.md:133-143
links:
  issue_url:
---

# IMP0016: FB0016: Pre-lane target intent context for steward lanes

## Status

- status: needs-more-evidence
- maturity: investigated
- source_type: local-reproduction
- scope: harnessops-core
- relation: extends
- promotion_level: core-workflow
- source_feedback: `FB0016`
- linked_records: `FB0016`, `E0016`, `H0016`, `D0016`

## Source Observation

Source: `harness-lab/records/feedback/FB0016-pre-lane-target-intent-context-for-steward-lanes.md`

# FB0016: Pre-lane target intent context for steward lanes

## 概要

Autonomous steward lanes currently infer target intent, memory boundaries, and human gates from scattered target docs and lane-local handoff text. RS0005 captured the need to evaluate a read-only pre-lane context contract sourced from target-owned context surfaces such as runo context --json and documented command gates.

## 再現

Daily steward run 20260521-040240-b6fdb3d produced RS0005 after open-meta and invention observed that priority lanes need target intent and human-gate evidence before implementation; runops already exposes target context via runo context --json and docs.

## 期待する上流変更

HarnessOps should evaluate a narrow pre-lane target intent digest contract that cites target-owned sources for project role, memory boundaries, command authority, and human gates before autonomous lanes make release, submit, cancel, delete, or persistent-memory decisions.

## Target Capability

- capability: target_intent_context
- failure_class: steward_target_context_inference

## Investigation

- 2026-05-21T04:17:55+09:00 [workflow-design] Priority review connected RS0005 to a concrete upstream workflow gap: runops documents target-owned context surfaces and gates, but autonomous steward lanes only receive lane-local summaries unless a supervisor passes those target facts explicitly. In a runops source checkout, runo context --json correctly fails without runops.toml, so a HOPS pre-lane digest must treat project context as an optional target-owned input and cite fallback docs/rules rather than persisting inferred target memory. (evidence: RS0005; uv run runo context --json ProjectNotFoundError in source checkout; README.md:94-121; docs/agent-user-guide.md:20,70,144-166,197; docs/layers/interface.md:51-55,109-110,127,154-159; docs/mcp.md:35-46,142-143; .codex/rules/commands.md:13)
- 2026-05-22T04:12:28+09:00 [codebase] Open-meta mode-map idea extends pre-lane target intent: README/docs split agent work across experiment operations, paper-support exports, harness maintenance, and upstream feedback, but no concise mode map tells an autonomous lane which posture and safety gates apply before acting. (evidence: README.md:163-174;docs/agent-user-guide.md:28-44;docs/mcp.md:133-143)

## Research Scans

research scan はまだありません。


## Evaluation

### E0016: E0016: FB0016-pre-lane-target-intent-context-for-steward-lanes を評価


- source: `harness-lab/records/eval-cases/E0016-fb0016-pre-lane-target-intent-context-for-steward-lanes.md`

- capability: target_intent_context

- failure_class: steward_target_context_inference

- manual_eval_yml: `harness-lab/views/eval-results/E0016-manual-score.yml`
- manual_eval_md: `harness-lab/views/eval-results/E0016-manual-score.md`
- scores: impact=4, mechanism_clarity=4, evaluability=4, minimality=4, regression_risk=3, operator_burden=3, anti_theater=4, maintainability=4, privacy_sanitization_risk=4
- notes: RS0005 and priority review show a recurring autonomous-lane gap: target intent, command gates, and memory boundaries are available in target-owned docs and project context surfaces, but not as a narrow pre-lane contract. The candidate is evaluable with fixtures where runo context --json succeeds, fails without runops.toml, and docs/rules provide fallback gate evidence. Implementation should remain read-only and non-authoritative to avoid creating a second target memory inside HOPS.


## Hypotheses

### H0016: H0016: E0016-fb0016-pre-lane-target-intent-context-for-steward-lanes の仮説


Source: `harness-lab/records/hypotheses/H0016-e0016-fb0016-pre-lane-target-intent-context-for-steward-lanes.md`


# H0016: E0016-fb0016-pre-lane-target-intent-context-for-steward-lanes の仮説

## 仮説

Providing autonomous steward lanes with a read-only pre-lane target intent digest will reduce unsafe or speculative target-context inference without turning HOPS records into project memory.

## メカニズム

Before lane execution, collect a narrow digest from target-owned sources: project role and overlay mode from .harnessops/project.toml, available project context from runo context --json when a runops.toml project exists, configured agent docs/rules, and explicit high-cost or destructive command gates. Attach source references and mark missing context as unknown instead of inferred.

## 最小実装

In HarnessOps core, add a pre-lane context contract for daily steward runs that records cited target-owned facts in the run ledger or lane input, handles unavailable target context explicitly, and exposes the digest through review context without writing persistent project decisions into HOPS lab records.

## 代替案: 削除または統合

Keep relying on lane prompts and AGENTS/skill text only. This avoids a new contract, but leaves each lane to rediscover target intent and makes human-gate evidence inconsistent across autonomous runs.

## 期待される利点

Lanes can cite the same target-owned authority before release, submit, cancel, delete, memory, or issue actions; supervisors get a reviewable artifact; target repositories avoid duplicated durable memory.

## 想定される欠点

A poorly scoped digest could become metadata theater or a stale second source of truth if it copies decisions instead of citing target-owned sources and unknowns.

## 評価計画

Use steward-run fixtures for a runops project with runo context --json, a source checkout without runops.toml, and docs-defined gates. Assert the digest cites sources, represents unknowns, blocks or flags gated actions without evidence, and is available to invention/priority lanes.

## 中止基準

Reject if the design persists target decisions as HOPS truth, requires direct overlay edits, exposes private project details beyond cited source snippets, or cannot distinguish missing project context from permission to proceed.


## Evidence

`harness-lab/views/eval-results/E0016-manual-score.md`

## Guard

- status: candidate
- path: harnessops-core:tests/test_steward/test_target_intent_context.py::test_pre_lane_context_digest_cites_target_owned_gates

## Links

- issue_url: 未設定

## Open Questions And Next Action

次の実装または評価ステップは、この dossier と紐づく正規化レコードを更新してから再生成してください。

## Decision Log

### D0016: D0016: needs-more-evidence H0016


Source: `harness-lab/records/decisions/D0016-needs-more-evidence-h0016.md`


# D0016: needs-more-evidence H0016

## 判断

needs-more-evidence

## 理由

The workflow problem is clear and cross-lane, and RS0005 plus E0016 define an evaluable mechanism, but this target repo run has not implemented or validated the HarnessOps core pre-lane context contract.

## 証拠

RS0005; FB0016; E0016 manual score; H0016; priority review observed runo context --json fails without runops.toml in source checkout and docs/rules contain target-owned human-gate evidence.

## 回帰リスク

Medium. A digest could become a stale second source of truth or leak target-private context unless it stays read-only, source-cited, and explicit about unknowns.

## フォローアップ

Implement the HarnessOps core pre-lane target intent context contract with fixtures for project context success, source-checkout missing context, and docs-defined human gates; then rerun review context and decide adoption.

## 回帰ガード

harnessops-core:tests/test_steward/test_target_intent_context.py::test_pre_lane_context_digest_cites_target_owned_gates
