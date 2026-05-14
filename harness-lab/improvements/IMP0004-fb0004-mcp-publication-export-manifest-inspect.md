---
id: IMP0004
record_type: improvement_dossier
created_at: '2026-05-15T04:08:36+09:00'
updated_at: '2026-05-15T04:12:03+09:00'
status: adopted
source_type: local-implementation
scope: runops-target
maturity: adopted
relation: new
promotion_level: target-feature
source_feedback: FB0004
eval_cases:
- E0004
hypotheses:
- H0004
decisions:
- D0003
research_scans: []
classification:
  capability: mcp_publication_export_inspection
  failure_class: missing_publication_export_manifest_inspect
guard:
  status: implemented
  path: tests/test_mcp/test_tools.py::test_publication_exports_list_and_inspect_manifest; tests/test_mcp/test_tools.py::test_publication_exports_list_reports_broken_manifest; tests/test_mcp/test_server.py
investigation:
- created_at: '2026-05-15T04:08:36+09:00'
  kind: implementation-sync
  summary: 'PR #72 implemented read-only MCP publication export inspection for FB0004: runops.publication.exports.list and runops.publication.export.inspect read existing exports/papers manifests, preserve empty-list behavior, and report broken manifests through envelope warnings/errors.'
  evidence_ref: 'PR #72; issue #67; src/runops/mcp/tools.py; src/runops/mcp/server.py; docs/mcp.md; tests/test_mcp/test_tools.py::test_publication_exports_list_and_inspect_manifest; tests/test_mcp/test_tools.py::test_publication_exports_list_reports_broken_manifest'
links:
  issue_url: https://github.com/Nkzono99/runops/issues/67
---

# IMP0004: FB0004: MCP から publication export 一覧と manifest を inspect できるようにする

## Status

- status: adopted
- maturity: adopted
- source_type: local-implementation
- scope: runops-target
- relation: new
- promotion_level: target-feature
- source_feedback: `FB0004`
- linked_records: `FB0004`, `E0004`, `H0004`, `D0003`

## Source Observation

Source: `harness-lab/records/feedback/FB0004-mcp-publication-export-manifest-inspect.md`

# FB0004: MCP から publication export 一覧と manifest を inspect できるようにする

## 概要

GitHub issue: https://github.com/Nkzono99/runops/issues/67
author: Nkzono99
labels: なし
created_at: 2026-05-14T01:53:06Z
updated_at: 2026-05-14T01:53:06Z

## Issue本文
## 背景

paperops の paper draft link registry から runops project を参照し、論文に使う export bundle を discovery / inspect したい。runops には `runo analyze export <run-or-survey> --paper <paper-id>` と `exports/papers/<paper-id>/<export-name>/manifest.json` が既にあるため、MCP 側では既存成果物を read/inspect する薄い入口が欲しい。

## 提案

- `runops.publication.exports.list` を追加する。
  - 入力: `project_root`, optional `paper_id`, optional `limit`
  - 出力: export id, paper id, export name, target kind, source run ids, created_at, manifest path, README path, warning count
- `runops.publication.export.inspect` を追加する。
  - 入力: `project_root`, `export` または `paper_id` + `name`
  - 出力: `manifest.json` の要約、files[], source metadata, warnings
- safety は read/inspect。file mutation は行わない。
- `runo mcp tools --json`, `runo mcp check`, tests を更新する。

## paperops からの利用イメージ

paper draft 側は `refs/links.toml` の `kind = "runops_project"` link を解決し、MCP 経由で利用可能な export を列挙する。論文側に取り込む証拠は export manifest / files の参照に寄せる。

## 受け入れ基準

- export が無い project でも空配列で成功する。
- `paper_id` filter が効く。
- 壊れた manifest は warnings/errors として envelope に表現し、MCP protocol error にしない。
- docs/mcp.md に tool が追記される。

## 再現

送信元フィードバックバンドルを参照してください。

## 期待する上流変更

送信元フィードバックバンドルを参照してください。

## Target Capability

- capability: mcp_publication_export_inspection
- failure_class: missing_publication_export_manifest_inspect

## Investigation

- 2026-05-15T04:08:36+09:00 [implementation-sync] PR #72 implemented read-only MCP publication export inspection for FB0004: runops.publication.exports.list and runops.publication.export.inspect read existing exports/papers manifests, preserve empty-list behavior, and report broken manifests through envelope warnings/errors. (evidence: PR #72; issue #67; src/runops/mcp/tools.py; src/runops/mcp/server.py; docs/mcp.md; tests/test_mcp/test_tools.py::test_publication_exports_list_and_inspect_manifest; tests/test_mcp/test_tools.py::test_publication_exports_list_reports_broken_manifest)

## Research Scans

research scan はまだありません。


## Evaluation

### E0004: E0004: FB0004-mcp-publication-export-manifest-inspect を評価


- source: `harness-lab/records/eval-cases/E0004-fb0004-mcp-publication-export-manifest-inspect.md`

- capability: mcp_publication_export_inspection

- failure_class: missing_publication_export_manifest_inspect

- manual_eval_yml: `harness-lab/views/eval-results/E0004-manual-score.yml`
- manual_eval_md: `harness-lab/views/eval-results/E0004-manual-score.md`
- scores: impact=4, mechanism_clarity=5, evaluability=5, minimality=4, regression_risk=2, operator_burden=4, anti_theater=5, maintainability=4, privacy_sanitization_risk=5
- notes: Implemented read-only MCP publication export tools: runops.publication.exports.list and runops.publication.export.inspect. Validation passed: ruff check src/ tests/, mypy src/, pytest, pytest --cov=runops --cov-branch --cov-report=term-missing --cov-fail-under=80, and runo mcp check.


## Hypotheses

### H0004: H0004: E0004-fb0004-mcp-publication-export-manifest-inspect の仮説


Source: `harness-lab/records/hypotheses/H0004-e0004-fb0004-mcp-publication-export-manifest-inspect.md`


# H0004: E0004-fb0004-mcp-publication-export-manifest-inspect の仮説

## 仮説

The implemented read-only publication export MCP tools resolve FB0004 by exposing existing export manifests without creating or mutating files.

## メカニズム

The MCP layer registers list and inspect tools that scan exports/papers, parse manifest.json when present, and return structured Ops MCP envelopes; broken manifests become tool-level warnings/errors instead of protocol failures.

## 最小実装

Use the existing PR #72 implementation: runops.publication.exports.list, runops.publication.export.inspect, registry/server entries, docs/mcp.md, and focused MCP tool tests.

## 代替案: 削除または統合

Keep publication export discovery in CLI-only workflows, but paper-facing hosts would then need to inspect project files directly and duplicate manifest parsing.

## 期待される利点

Paper-facing agents can discover publication bundles through a read-only, typed interface and avoid mutating project state.

## 想定される欠点

The tool surface adds another MCP endpoint family that must stay aligned with publication manifest shape.

## 評価計画

Use E0004 manual score plus tests covering listing, inspect, empty exports, broken manifests, server registration, runo mcp tools --json, and runo mcp check.

## 中止基準

Reopen if the tools create files, hide broken manifests as protocol errors, omit empty export handling, or drift from documented manifest fields.


## Evidence

`harness-lab/views/eval-results/E0004-manual-score.md`

## Guard

- status: implemented
- path: tests/test_mcp/test_tools.py::test_publication_exports_list_and_inspect_manifest; tests/test_mcp/test_tools.py::test_publication_exports_list_reports_broken_manifest; tests/test_mcp/test_server.py

## Links

- issue_url: https://github.com/Nkzono99/runops/issues/67

## Open Questions And Next Action

次の実装または評価ステップは、この dossier と紐づく正規化レコードを更新してから再生成してください。

## Decision Log

### D0003: D0003: adopted H0004


Source: `harness-lab/records/decisions/D0003-adopted-h0004.md`


# D0003: adopted H0004

## 判断

adopted

## 理由

PR #72 implemented the requested read-only publication export list/inspect MCP tools and issue #67 is closed.

## 証拠

E0004 manual score records passed validation; code evidence in src/runops/mcp/tools.py and src/runops/mcp/server.py; docs/mcp.md documents both tools; tests/test_mcp/test_tools.py covers valid and broken manifests; GitHub issue #67 is closed after PR #72.

## 回帰リスク

Low. The implementation is read-only and scoped to MCP inspection, with residual risk limited to publication manifest schema drift.

## フォローアップ

Keep runo mcp check and MCP registry/server tests as guards; revisit if publication manifest shape changes.

## 回帰ガード

tests/test_mcp/test_tools.py::test_publication_exports_list_and_inspect_manifest; tests/test_mcp/test_tools.py::test_publication_exports_list_reports_broken_manifest; tests/test_mcp/test_server.py
