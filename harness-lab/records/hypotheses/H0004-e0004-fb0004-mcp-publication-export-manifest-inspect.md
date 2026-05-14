---
id: H0004
record_type: hypothesis
created_at: '2026-05-15T04:08:49+09:00'
status: proposed
target_capability: mcp_publication_export_inspection
source_eval_case: E0004
---

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
