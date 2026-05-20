---
id: H0016
record_type: hypothesis
created_at: '2026-05-21T04:18:31+09:00'
status: proposed
target_capability: target_intent_context
source_eval_case: E0016
---

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
