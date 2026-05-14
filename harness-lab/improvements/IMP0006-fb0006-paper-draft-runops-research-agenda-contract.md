---
id: IMP0006
record_type: improvement_dossier
created_at: '2026-05-15T04:10:01+09:00'
updated_at: '2026-05-15T04:12:06+09:00'
status: adopted
source_type: local-implementation
scope: runops-target
maturity: adopted
relation: new
promotion_level: target-feature
source_feedback: FB0006
eval_cases:
- E0006
hypotheses:
- H0006
decisions:
- D0005
research_scans: []
classification:
  capability: paper_request_contract
  failure_class: missing_paper_to_runops_request_contract
guard:
  status: implemented
  path: tests/test_mcp/test_tools.py; tests/test_mcp/test_server.py; tests/test_cli/test_init.py
investigation:
- created_at: '2026-05-15T04:10:01+09:00'
  kind: implementation-sync
  summary: 'PR #72 implemented the paper request contract requested by FB0006 with docs, schema/template support, and read/plan MCP tools; PR #73 fixed the empty paper request queue regression so missing or empty research/paper_requests.toml returns an empty read model instead of failing.'
  evidence_ref: 'PR #72; PR #73; issue #69; docs/paper-requests.md; docs/mcp.md; src/runops/templates/project/research/paper_requests.toml; src/runops/mcp/tools.py; tests/test_mcp/test_tools.py; tests/test_cli/test_init.py'
links:
  issue_url: https://github.com/Nkzono99/runops/issues/69
---

# IMP0006: FB0006: paper draft からの追加解析・追加実験要望を runops research agenda に取り込む contract を設計する

## Status

- status: adopted
- maturity: adopted
- source_type: local-implementation
- scope: runops-target
- relation: new
- promotion_level: target-feature
- source_feedback: `FB0006`
- linked_records: `FB0006`, `E0006`, `H0006`, `D0005`

## Source Observation

Source: `harness-lab/records/feedback/FB0006-paper-draft-runops-research-agenda-contract.md`

# FB0006: paper draft からの追加解析・追加実験要望を runops research agenda に取り込む contract を設計する

## 概要

GitHub issue: https://github.com/Nkzono99/runops/issues/69
author: Nkzono99
labels: なし
created_at: 2026-05-14T01:53:22Z
updated_at: 2026-05-14T01:53:22Z

## Issue本文
## 背景

paperops の執筆中に、結果セクションや図表設計から「この追加解析が必要」「この条件の run を追加したい」「この export は placeholder 扱い」などの需要が出る。これを runops project 側の research agenda / case / survey design に戻すための軽い contract が欲しい。

## 提案

- paper-facing request schema を設計する。
  - 例: `analysis_request`, `figure_request`, `experiment_request`, `evidence_gap`, `export_request`
  - fields: id, title, paper_context, desired_artifact, source_link, related_runs/surveys, priority, status
- runops 側で import 先を決める。
  - 候補: `research/agenda.md`, `research/proposals/`, または structured TOML/JSONL
- MCP または CLI に read/plan entrypoint を追加するか検討する。
  - 初期は read/plan のみでよい。
  - 実際の run creation / survey expansion は既存 `create-run` / `setup-campaign` flow に委ねる。
- paperops の link registry から runops project link と request を対応づけられるようにする。

## 受け入れ基準

- request schema の docs と例がある。
- paperops 側の `refs/links.toml` / notes から参照できる stable id を持つ。
- runops project 内で未処理・処理中・完了を追える。
- 追加実験の実行そのものは明示操作に残し、MCP 経由で勝手に submit しない。

## 再現

送信元フィードバックバンドルを参照してください。

## 期待する上流変更

送信元フィードバックバンドルを参照してください。

## Target Capability

- capability: paper_request_contract
- failure_class: missing_paper_to_runops_request_contract

## Investigation

- 2026-05-15T04:10:01+09:00 [implementation-sync] PR #72 implemented the paper request contract requested by FB0006 with docs, schema/template support, and read/plan MCP tools; PR #73 fixed the empty paper request queue regression so missing or empty research/paper_requests.toml returns an empty read model instead of failing. (evidence: PR #72; PR #73; issue #69; docs/paper-requests.md; docs/mcp.md; src/runops/templates/project/research/paper_requests.toml; src/runops/mcp/tools.py; tests/test_mcp/test_tools.py; tests/test_cli/test_init.py)

## Research Scans

research scan はまだありません。


## Evaluation

### E0006: E0006: FB0006-paper-draft-runops-research-agenda-contract を評価


- source: `harness-lab/records/eval-cases/E0006-fb0006-paper-draft-runops-research-agenda-contract.md`

- capability: paper_request_contract

- failure_class: missing_paper_to_runops_request_contract

- manual_eval_yml: `harness-lab/views/eval-results/E0006-manual-score.yml`
- manual_eval_md: `harness-lab/views/eval-results/E0006-manual-score.md`
- scores: impact=3, mechanism_clarity=5, evaluability=5, minimality=4, regression_risk=2, operator_burden=4, anti_theater=5, maintainability=4, privacy_sanitization_risk=5
- notes: Implemented the paper request contract with docs, schema, scaffold template, and read/plan MCP tools: runops.paper.requests.list and runops.paper.request.plan. The tools do not mutate files or submit jobs. Validation passed: ruff check src/ tests/, mypy src/, pytest, pytest --cov=runops --cov-branch --cov-report=term-missing --cov-fail-under=80, and runo mcp check.


## Hypotheses

### H0006: H0006: E0006-fb0006-paper-draft-runops-research-agenda-contract の仮説


Source: `harness-lab/records/hypotheses/H0006-e0006-fb0006-paper-draft-runops-research-agenda-contract.md`


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


## Evidence

`harness-lab/views/eval-results/E0006-manual-score.md`

## Guard

- status: implemented
- path: tests/test_mcp/test_tools.py; tests/test_mcp/test_server.py; tests/test_cli/test_init.py

## Links

- issue_url: https://github.com/Nkzono99/runops/issues/69

## Open Questions And Next Action

次の実装または評価ステップは、この dossier と紐づく正規化レコードを更新してから再生成してください。

## Decision Log

### D0005: D0005: adopted H0006


Source: `harness-lab/records/decisions/D0005-adopted-h0006.md`


# D0005: adopted H0006

## 判断

adopted

## 理由

PR #72 implemented the paper request contract and read/plan MCP tools, PR #73 fixed empty request queues, and issue #69 is closed.

## 証拠

E0006 manual score records passed validation; docs/paper-requests.md and docs/mcp.md document the contract; src/runops/mcp/tools.py exposes runops.paper.requests.list and runops.paper.request.plan; tests cover the request read/plan behavior and empty queue guard; GitHub issue #69 is closed after PR #72 and PR #73.

## 回帰リスク

Low to medium. The tools are read/plan only, but the planning contract must remain clearly separated from run creation, survey expansion, and Slurm submission.

## フォローアップ

Keep paper request tests, MCP registry checks, and docs aligned; do not add execution semantics to paper request MCP tools without a separate gated design.

## 回帰ガード

tests/test_mcp/test_tools.py; tests/test_mcp/test_server.py; tests/test_cli/test_init.py
