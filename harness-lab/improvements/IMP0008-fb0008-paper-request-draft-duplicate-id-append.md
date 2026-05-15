---
id: IMP0008
record_type: improvement_dossier
created_at: '2026-05-15T15:42:42+09:00'
updated_at: '2026-05-15T15:43:01+09:00'
status: adopted
source_type: local-implementation
scope: runops-target
maturity: adopted
relation: new
promotion_level: target-feature
source_feedback: FB0008
eval_cases:
- E0008
hypotheses:
- H0008
decisions:
- D0007
research_scans: []
classification:
  capability: unclassified
  failure_class: unclassified
guard:
  status: implemented
  path: tests/test_mcp/test_tools.py::test_paper_request_draft_warns_on_duplicate_id; uv run runo mcp check
investigation:
- created_at: '2026-05-15T15:43:01+09:00'
  kind: implementation-sync
  summary: 'Implemented issue #77 by making duplicate request_id a blocking draft validation error. The MCP tool now returns valid=false, empty toml_snippet, no append next action, duplicate_id=true, and suggested_request_id for the next safe id.'
  evidence_ref: 'issue #77; src/runops/mcp/tools.py; tests/test_mcp/test_tools.py::test_paper_request_draft_warns_on_duplicate_id; docs/mcp.md; docs/paper-requests.md'
links:
  issue_url: https://github.com/Nkzono99/runops/issues/77
---

# IMP0008: FB0008: paper_request.draft で duplicate id を append 可能扱いにしない

## Status

- status: adopted
- maturity: adopted
- source_type: local-implementation
- scope: runops-target
- relation: new
- promotion_level: target-feature
- source_feedback: `FB0008`
- linked_records: `FB0008`, `E0008`, `H0008`, `D0007`

## Source Observation

Source: `harness-lab/records/feedback/FB0008-paper-request-draft-duplicate-id-append.md`

# FB0008: paper_request.draft で duplicate id を append 可能扱いにしない

## 概要

GitHub issue: https://github.com/Nkzono99/runops/issues/77
author: Nkzono99
labels: enhancement
created_at: 2026-05-15T06:13:42Z
updated_at: 2026-05-15T06:13:42Z

## Issue本文
## 背景

`runops.paper.request.draft` は paperops から `research/paper_requests.toml` へ追記する前の preview / validation tool として使う想定です。現在、既存 queue と同じ `request_id` を渡した場合に duplicate warning は出ますが、`data.valid = true` のまま `toml_snippet` と `Append the TOML snippet...` next action が返ります。

## 再現

既存 queue に `PAPER-REQ-0001` がある状態で、同じ `request_id="PAPER-REQ-0001"` を指定して `runops.paper.request.draft` を呼ぶと、以下になります。

```text
status=warning
valid=True
duplicate=True
snippet=True
next_actions=[Append the TOML snippet to research/paper_requests.toml]
```

## 問題

この tool は「追記用 TOML snippet」を返すため、duplicate id のまま append 可能に見えると、paperops handoff で queue に重複 id を入れやすくなります。warning だけでは、下流 agent が `toml_snippet` と next action を優先してしまう可能性があります。

## 提案

- duplicate id を validation error にする、または少なくとも `valid=false` / `toml_snippet=""` / append next action なしにする。
- 代替 id 候補を返す場合は `suggested_request_id` などの別フィールドに出す。
- tests で duplicate id 時に snippet が返らないこと、append next action が出ないことを確認する。

## 受け入れ基準

- duplicate id の `paper_request_draft` 結果が、そのまま append してよいように見えない。
- MCP conformance と既存 paper request tests が通る。
- docs に duplicate id 時の扱いが明記される。

## 再現

送信元フィードバックバンドルを参照してください。

## 期待する上流変更

送信元フィードバックバンドルを参照してください。

## Target Capability

- capability: unclassified
- failure_class: unclassified

## Investigation

- 2026-05-15T15:43:01+09:00 [implementation-sync] Implemented issue #77 by making duplicate request_id a blocking draft validation error. The MCP tool now returns valid=false, empty toml_snippet, no append next action, duplicate_id=true, and suggested_request_id for the next safe id. (evidence: issue #77; src/runops/mcp/tools.py; tests/test_mcp/test_tools.py::test_paper_request_draft_warns_on_duplicate_id; docs/mcp.md; docs/paper-requests.md)

## Research Scans

research scan はまだありません。


## Evaluation

### E0008: E0008: FB0008-paper-request-draft-duplicate-id-append を評価


- source: `harness-lab/records/eval-cases/E0008-fb0008-paper-request-draft-duplicate-id-append.md`

- capability: unclassified

- failure_class: unclassified

- manual_eval_yml: `harness-lab/views/eval-results/E0008-manual-score.yml`
- manual_eval_md: `harness-lab/views/eval-results/E0008-manual-score.md`
- scores: impact=3, mechanism_clarity=5, evaluability=5, minimality=5, regression_risk=1, operator_burden=5, anti_theater=5, maintainability=4, privacy_sanitization_risk=5
- notes: Changed runops.paper.request.draft so duplicate request_id is no longer appendable: duplicate id is reported as paper_request_duplicate_id error, data.valid=false, toml_snippet is empty, append next_actions are omitted, and suggested_request_id points to the next non-colliding id. Updated docs and tests. Validation passed: ruff format --check src/ tests/, ruff check src/ tests/, mypy src/, pytest -q, runo mcp check, and hops doctor --check-overlay --check-records.


## Hypotheses

### H0008: H0008: E0008-fb0008-paper-request-draft-duplicate-id-append の仮説


Source: `harness-lab/records/hypotheses/H0008-e0008-fb0008-paper-request-draft-duplicate-id-append.md`


# H0008: E0008-fb0008-paper-request-draft-duplicate-id-append の仮説

## 仮説

評価ケースを失敗させた最小の上流挙動を変更し、`E0008` の `unclassified` を改善する。

## メカニズム

採用前に、提案変更が作用するメカニズムを明示してください。曖昧なプロセス追加や文書追加だけでは証拠として不十分です。

## 最小実装

紐づく評価ケースで評価できる最も狭い変更を実装してください。複雑さを減らせるなら、新しい抽象より削除または統合を優先します。

## 代替案: 削除または統合

新しい挙動を追加する前に、既存のルール、プロファイル、スキル、テンプレートを削除、統合、厳格化できないか評価してください。

## 期待される利点

紐づく評価ケース `E0008` が、運用者負担を減らし、プロジェクト固有文脈を上流へ漏らさずに通る。

## 想定される欠点

想定される欠点: ルーティング摩擦、偽陽性、保守負担が増える可能性。採用にはこの点の明示的な確認が必要です。

## 評価計画

`hops eval --case E0008 --manual` を実行し、採用判断を作る前に多軸スコアを記録する。

## 中止基準

紐づく評価ケースを改善しない、プライバシーリスクを増やす、または失敗クラスを減らさずにガバナンス構造だけを追加する場合、この仮説を却下または保留する。


## Evidence

`harness-lab/views/eval-results/E0008-manual-score.md`

## Guard

- status: implemented
- path: tests/test_mcp/test_tools.py::test_paper_request_draft_warns_on_duplicate_id; uv run runo mcp check

## Links

- issue_url: https://github.com/Nkzono99/runops/issues/77

## Open Questions And Next Action

次の実装または評価ステップは、この dossier と紐づく正規化レコードを更新してから再生成してください。

## Decision Log

### D0007: D0007: adopted H0008


Source: `harness-lab/records/decisions/D0007-adopted-h0008.md`


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
