---
id: E0015
record_type: eval_case
created_at: '2026-05-18T04:21:13+09:00'
status: active
capability: steward_lane_handoff
failure_class: transient_lane_artifact_loss
source_feedback: FB0015
---

# E0015: FB0015-steward-lane-artifacts-need-durable-schema を評価

## フィクスチャ

- source_feedback: `harness-lab/records/feedback/FB0015-steward-lane-artifacts-need-durable-schema.md`
- fixture_dir: `harness-lab/records/eval-cases/fixtures/E0015`
- observation: Daily steward lanes now pass structured open-meta artifacts through the run ledger, but those artifacts have no first-class schema, expiry, or promotion lifecycle. RS0003 captured the research scan; this feedback turns it into an evaluable upstream HOPS improvement packet.

## タスク

`steward_lane_handoff` の `transient_lane_artifact_loss` を減らす最小変更を設計または実装し、次の再現条件が解消されるか評価してください。

Run 20260518-040139-5c4808b stored artifacts.meta_scan in the steward ledger and later lanes depended on it; review queue can show RS0003, but current eval/dossier flow is feedback-centric rather than research-scan-centric.

## 期待される挙動

HarnessOps should define a narrow steward lane artifact lifecycle: schema-checked artifacts in the run ledger or managed cache, explicit expiry/promotion rules, lint/review visibility, and no requirement to promote every broad scan to a permanent improvement dossier.

## 合格基準

- `transient_lane_artifact_loss` の再現条件が検出または防止される。
- 提案または実装される変更が source feedback の期待変更に対応している。
- `hops lab eval --case E0015 --manual` の score と notes で採用判断に必要な証拠を説明できる。
- 非公開プロジェクト詳細を追加で要求しない。

## 不合格基準

- `transient_lane_artifact_loss` の再現条件を見逃す。
- source feedback の期待変更と無関係な改善案になる。
- 評価が yml score へ記録されず、採用判断の証拠として追えない。
- 再現または判断に非公開文脈が必要になる。
