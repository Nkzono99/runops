---
id: D0003
record_type: decision
created_at: '2026-05-15T04:09:00+09:00'
status: adopted
source: H0004
evidence:
  summary: 'E0004 manual score records passed validation; code evidence in src/runops/mcp/tools.py and src/runops/mcp/server.py; docs/mcp.md documents both tools; tests/test_mcp/test_tools.py covers valid and broken manifests; GitHub issue #67 is closed after PR #72.'
  guard_path: tests/test_mcp/test_tools.py::test_publication_exports_list_and_inspect_manifest; tests/test_mcp/test_tools.py::test_publication_exports_list_reports_broken_manifest; tests/test_mcp/test_server.py
---

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
