---
id: H0006
record_type: hypothesis
created_at: '2026-05-15T04:10:15+09:00'
status: proposed
target_capability: paper_request_contract
source_eval_case: E0006
---

# H0006: E0006-fb0006-paper-draft-runops-research-agenda-contract の仮説

## 仮説

The implemented paper request contract resolves FB0006 by giving paper drafts a stable read/plan interface back into runops research agenda work without triggering run creation, survey expansion, or job submission.

## メカニズム

A documented paper request schema and template define stable ids, request kinds, priorities, statuses, source links, and related run/survey references; MCP tools list requests and produce plans that point back to research/agenda.md or proposals while remaining non-mutating.

## 最小実装

Use the PR #72 implementation for docs/paper-requests.md, project scaffold template, runops.paper.requests.list, runops.paper.request.plan, docs/mcp.md, and focused tests, plus PR #73's empty queue guard.

## 代替案: 削除または統合

Keep paper-to-runops follow-up as prose notes only, but then additional analysis and experiment needs lack stable ids or a safe read/plan API.

## 期待される利点

Paper-facing agents can track additional analysis, figure, evidence-gap, export, and experiment requests without bypassing human-gated runops workflows.

## 想定される欠点

This creates another project-side planning artifact that must not become an implicit execution queue.

## 評価計画

Use E0006 manual score plus tests for request listing, planning, empty queues, scaffold output, MCP server registration, runo mcp tools --json, and runo mcp check.

## 中止基準

Reopen if request planning mutates files, submits jobs, lacks stable ids, or treats experiment requests as automatic execution.
