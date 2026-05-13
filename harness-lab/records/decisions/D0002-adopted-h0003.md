---
id: D0002
record_type: decision
created_at: '2026-05-14T04:13:32+09:00'
status: adopted
source: H0003
evidence:
  summary: harnessops#12 closed as resolved in v0.1.8; installed harnessops 0.1.9 project bridge omits lab/propose/decide commands; upstream guard tests/test_agent_harness_contract.py::test_generated_bridge_scopes_feedback_source_interface asserts the scoped behavior.
  guard_path: harnessops-core:tests/test_agent_harness_contract.py::test_generated_bridge_scopes_feedback_source_interface
---

# D0002: adopted H0003

## 判断

adopted

## 理由

Upstream HarnessOps now role-scopes generated project bridges, matching FB0003's expected change.

## 証拠

harnessops#12 closed as resolved in v0.1.8; installed harnessops 0.1.9 project bridge omits lab/propose/decide commands; upstream guard tests/test_agent_harness_contract.py::test_generated_bridge_scopes_feedback_source_interface asserts the scoped behavior.

## 回帰リスク

Low for runops: this is local lab state sync only. Residual risk is stale generated bridge files in already initialized project repositories until update-harness is run.

## フォローアップ

Project repositories with stale generated HarnessOps bridge files should run uvx --refresh-package harnessops --from harnessops hops update-harness --agent-bridge.

## 回帰ガード

harnessops-core:tests/test_agent_harness_contract.py::test_generated_bridge_scopes_feedback_source_interface
