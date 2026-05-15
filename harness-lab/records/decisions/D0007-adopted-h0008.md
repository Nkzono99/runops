---
id: D0007
record_type: decision
created_at: '2026-05-15T15:42:32+09:00'
status: adopted
source: H0008
evidence:
  summary: E0008 manual score records the implementation and validation evidence. src/runops/mcp/tools.py reports paper_request_duplicate_id as an error, returns valid=false, no toml_snippet, no append next action, and suggested_request_id. tests/test_mcp/test_tools.py covers the duplicate-id regression; docs/mcp.md and docs/paper-requests.md document the behavior.
  guard_path: tests/test_mcp/test_tools.py::test_paper_request_draft_warns_on_duplicate_id; uv run runo mcp check
---

# D0007: adopted H0008

## 判断

adopted

## 理由

Duplicate paper request ids are now blocking validation errors in the draft MCP tool instead of appendable warnings.

## 証拠

E0008 manual score records the implementation and validation evidence. src/runops/mcp/tools.py reports paper_request_duplicate_id as an error, returns valid=false, no toml_snippet, no append next action, and suggested_request_id. tests/test_mcp/test_tools.py covers the duplicate-id regression; docs/mcp.md and docs/paper-requests.md document the behavior.

## 回帰リスク

Low. The change narrows an unsafe preview path while preserving auto-id generation when request_id is omitted and preserving existing enum validation.

## フォローアップ

Keep duplicate-id behavior aligned with paperops handoff expectations; do not return append snippets for known-invalid draft candidates.

## 回帰ガード

tests/test_mcp/test_tools.py::test_paper_request_draft_warns_on_duplicate_id; uv run runo mcp check
