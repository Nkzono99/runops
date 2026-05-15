---
id: IMP0007
record_type: improvement_dossier
created_at: '2026-05-15T14:53:39+09:00'
updated_at: '2026-05-15T14:54:10+09:00'
status: adopted
source_type: local-implementation
scope: runops-target
maturity: adopted
relation: new
promotion_level: target-feature
source_feedback: FB0007
eval_cases:
- E0007
hypotheses:
- H0007
decisions:
- D0006
research_scans: []
classification:
  capability: unclassified
  failure_class: unclassified
guard:
  status: implemented
  path: tests/test_mcp/test_tools.py::test_paper_request_draft_accepts_empty_queue; tests/test_mcp/test_tools.py::test_paper_request_draft_uses_next_id_for_existing_queue; tests/test_mcp/test_tools.py::test_paper_request_draft_warns_on_duplicate_id; tests/test_mcp/test_tools.py::test_paper_request_draft_reports_invalid_enums; tests/test_mcp/test_server.py; uv run runo mcp check
investigation:
- created_at: '2026-05-15T14:54:10+09:00'
  kind: implementation-sync
  summary: 'Implemented issue #75 with runops.paper.request.draft as a plan-only MCP tool. The tool validates required fields and type/priority/status enums, generates a non-colliding PAPER-REQ id when omitted, warns on duplicate ids, returns target path and TOML snippet, and does not mutate files, create runs, expand surveys, or submit jobs.'
  evidence_ref: 'issue #75; src/runops/mcp/tools.py; src/runops/mcp/registry.py; src/runops/mcp/server.py; tests/test_mcp/test_tools.py; tests/test_mcp/test_server.py; docs/mcp.md; docs/paper-requests.md'
links:
  issue_url: https://github.com/Nkzono99/runops/issues/75
---

# IMP0007: FB0007: paper request の draft/validate MCP を追加して paperops handoff を安全化する

## Status

- status: adopted
- maturity: adopted
- source_type: local-implementation
- scope: runops-target
- relation: new
- promotion_level: target-feature
- source_feedback: `FB0007`
- linked_records: `FB0007`, `E0007`, `H0007`, `D0006`

## Source Observation

Source: `harness-lab/records/feedback/FB0007-paper-request-draft-validate-mcp-paperops-handoff.md`

# FB0007: paper request の draft/validate MCP を追加して paperops handoff を安全化する

## 概要

GitHub issue: https://github.com/Nkzono99/runops/issues/75
author: Nkzono99
labels: enhancement
created_at: 2026-05-15T04:02:03Z
updated_at: 2026-05-15T04:02:03Z

## Issue本文
## 背景

paperops 側では `refs/links.toml` と `notes/research-requests.md` から runops project へ追加解析・図表・追加実験要望を戻す導線を作っている。runops #69 で `research/paper_requests.toml` と read/plan MCP は整ったが、paperops 側が request を作る時点では runops schema / enum / id 形式を複製する必要がある。

paperops から直接ファイルを書き換える前に、runops 側で candidate request を検証し、TOML snippet と保存先を返せる read/plan 系 entrypoint があると、schema drift と手作業ミスを減らせる。

## 提案

- MCP に paper request draft/validate 用の非破壊 tool を追加する。
  - 候補名: `runops.paper.request.draft` または `runops.paper.request.validate`
  - safety は `plan` または `read`。file mutation / run creation / job submit はしない。
- 入力例:
  - `paper_id`, `source_link`, `type`, `title`, `paper_context`, `desired_artifact`, `priority`, `related_runs`, `related_surveys`, `human_gate`
  - 任意で `request_id`。未指定なら既存 queue と衝突しない候補 id を返す。
- 出力例:
  - normalized request object
  - `research/paper_requests.toml` に追記できる TOML snippet
  - target path / existing queue status / duplicate id warnings
  - schema validation errors / enum mismatch warnings
- 既存 `runops.paper.requests.list` と `runops.paper.request.plan` は維持する。

## 受け入れ基準

- paperops が runops schema を再実装せずに request handoff の preview/validation を行える。
- empty queue、既存 queue、duplicate id、invalid type/status/priority のテストがある。
- MCP conformance で mutating/external/destructive tool として扱われない。
- docs に paperops からの handoff 手順が追記される。

## 再現

送信元フィードバックバンドルを参照してください。

## 期待する上流変更

送信元フィードバックバンドルを参照してください。

## Target Capability

- capability: unclassified
- failure_class: unclassified

## Investigation

- 2026-05-15T14:54:10+09:00 [implementation-sync] Implemented issue #75 with runops.paper.request.draft as a plan-only MCP tool. The tool validates required fields and type/priority/status enums, generates a non-colliding PAPER-REQ id when omitted, warns on duplicate ids, returns target path and TOML snippet, and does not mutate files, create runs, expand surveys, or submit jobs. (evidence: issue #75; src/runops/mcp/tools.py; src/runops/mcp/registry.py; src/runops/mcp/server.py; tests/test_mcp/test_tools.py; tests/test_mcp/test_server.py; docs/mcp.md; docs/paper-requests.md)

## Research Scans

research scan はまだありません。


## Evaluation

### E0007: E0007: FB0007-paper-request-draft-validate-mcp-paperops-handoff を評価


- source: `harness-lab/records/eval-cases/E0007-fb0007-paper-request-draft-validate-mcp-paperops-handoff.md`

- capability: unclassified

- failure_class: unclassified

- manual_eval_yml: `harness-lab/views/eval-results/E0007-manual-score.yml`
- manual_eval_md: `harness-lab/views/eval-results/E0007-manual-score.md`
- scores: impact=4, mechanism_clarity=5, evaluability=5, minimality=4, regression_risk=2, operator_burden=4, anti_theater=5, maintainability=4, privacy_sanitization_risk=5
- notes: Implemented runops.paper.request.draft as a plan-only MCP tool. It normalizes paper request candidates, generates a non-colliding request id, validates required fields and type/priority/status enums, warns on duplicate ids, returns target path and TOML snippet, and never mutates files or submits jobs. Tests cover empty queue, existing queue, duplicate id, invalid type/status/priority, server wiring, and MCP conformance. Validation passed: ruff format --check src/ tests/, ruff check src/ tests/, mypy src/, pytest -q, runo mcp check, and hops doctor --check-overlay --check-records.


## Hypotheses

### H0007: H0007: E0007-fb0007-paper-request-draft-validate-mcp-paperops-handoff の仮説


Source: `harness-lab/records/hypotheses/H0007-e0007-fb0007-paper-request-draft-validate-mcp-paperops-handoff.md`


# H0007: E0007-fb0007-paper-request-draft-validate-mcp-paperops-handoff の仮説

## 仮説

評価ケースを失敗させた最小の上流挙動を変更し、`E0007` の `unclassified` を改善する。

## メカニズム

採用前に、提案変更が作用するメカニズムを明示してください。曖昧なプロセス追加や文書追加だけでは証拠として不十分です。

## 最小実装

紐づく評価ケースで評価できる最も狭い変更を実装してください。複雑さを減らせるなら、新しい抽象より削除または統合を優先します。

## 代替案: 削除または統合

新しい挙動を追加する前に、既存のルール、プロファイル、スキル、テンプレートを削除、統合、厳格化できないか評価してください。

## 期待される利点

紐づく評価ケース `E0007` が、運用者負担を減らし、プロジェクト固有文脈を上流へ漏らさずに通る。

## 想定される欠点

想定される欠点: ルーティング摩擦、偽陽性、保守負担が増える可能性。採用にはこの点の明示的な確認が必要です。

## 評価計画

`hops eval --case E0007 --manual` を実行し、採用判断を作る前に多軸スコアを記録する。

## 中止基準

紐づく評価ケースを改善しない、プライバシーリスクを増やす、または失敗クラスを減らさずにガバナンス構造だけを追加する場合、この仮説を却下または保留する。


## Evidence

`harness-lab/views/eval-results/E0007-manual-score.md`

## Guard

- status: implemented
- path: tests/test_mcp/test_tools.py::test_paper_request_draft_accepts_empty_queue; tests/test_mcp/test_tools.py::test_paper_request_draft_uses_next_id_for_existing_queue; tests/test_mcp/test_tools.py::test_paper_request_draft_warns_on_duplicate_id; tests/test_mcp/test_tools.py::test_paper_request_draft_reports_invalid_enums; tests/test_mcp/test_server.py; uv run runo mcp check

## Links

- issue_url: https://github.com/Nkzono99/runops/issues/75

## Open Questions And Next Action

次の実装または評価ステップは、この dossier と紐づく正規化レコードを更新してから再生成してください。

## Decision Log

### D0006: D0006: adopted H0007


Source: `harness-lab/records/decisions/D0006-adopted-h0007.md`


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
