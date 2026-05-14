---
id: D0005
record_type: decision
created_at: '2026-05-15T04:10:28+09:00'
status: adopted
source: H0006
evidence:
  summary: 'E0006 manual score records passed validation; docs/paper-requests.md and docs/mcp.md document the contract; src/runops/mcp/tools.py exposes runops.paper.requests.list and runops.paper.request.plan; tests cover the request read/plan behavior and empty queue guard; GitHub issue #69 is closed after PR #72 and PR #73.'
  guard_path: tests/test_mcp/test_tools.py; tests/test_mcp/test_server.py; tests/test_cli/test_init.py
---

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
