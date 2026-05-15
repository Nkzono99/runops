---
id: D0006
record_type: decision
created_at: '2026-05-15T14:53:10+09:00'
status: adopted
source: H0007
evidence:
  summary: E0007 manual score records the implementation and validation evidence. src/runops/mcp/tools.py exposes runops.paper.request.draft; src/runops/mcp/registry.py and src/runops/mcp/server.py register it as plan-only. tests/test_mcp/test_tools.py covers empty queue, existing queue, duplicate id, and invalid type/status/priority; tests/test_mcp/test_server.py covers server wiring; docs/mcp.md and docs/paper-requests.md document paperops handoff.
  guard_path: tests/test_mcp/test_tools.py; tests/test_mcp/test_server.py; uv run runo mcp check
---

# D0006: adopted H0007

## 判断

adopted

## 理由

Implemented issue #75 with a plan-only MCP draft/validate entrypoint for paper request handoff.

## 証拠

E0007 manual score records the implementation and validation evidence. src/runops/mcp/tools.py exposes runops.paper.request.draft; src/runops/mcp/registry.py and src/runops/mcp/server.py register it as plan-only. tests/test_mcp/test_tools.py covers empty queue, existing queue, duplicate id, and invalid type/status/priority; tests/test_mcp/test_server.py covers server wiring; docs/mcp.md and docs/paper-requests.md document paperops handoff.

## 回帰リスク

Low to medium. The tool is non-mutating and plan-only, but the snippet contract must stay aligned with schemas/paper_requests.json and must not grow execution semantics.

## フォローアップ

Keep paper request schema, docs, MCP registry, and paperops usage aligned. Add a separate gated design before any tool writes paper_requests.toml directly.

## 回帰ガード

tests/test_mcp/test_tools.py; tests/test_mcp/test_server.py; uv run runo mcp check
