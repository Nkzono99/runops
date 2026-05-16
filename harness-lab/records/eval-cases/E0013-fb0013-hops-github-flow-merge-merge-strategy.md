---
id: E0013
record_type: eval_case
created_at: '2026-05-17T04:09:15+09:00'
status: active
capability: unclassified
failure_class: unclassified
source_feedback: FB0013
---

# E0013: FB0013-hops-github-flow-merge-merge-strategy を評価

## フィクスチャ

- source_feedback: `harness-lab/records/feedback/FB0013-hops-github-flow-merge-merge-strategy.md`
- fixture_dir: `harness-lab/records/eval-cases/fixtures/E0013`
- observation: GitHub issue: https://github.com/Nkzono99/runops/issues/87
author: Nkzono99
labels: enhancement, codex
created_at: 2026-05-16T05:07:29Z
updated_at: 2026-05-16T05:07:29Z

## タスク

`unclassified` の `unclassified` を減らす最小変更を設計または実装し、次の再現条件が解消されるか評価してください。

送信元フィードバックバンドルを参照してください。

## 期待される挙動

送信元フィードバックバンドルを参照してください。

## 合格基準

- `unclassified` の再現条件が検出または防止される。
- 提案または実装される変更が source feedback の期待変更に対応している。
- `hops lab eval --case E0013 --manual` の score と notes で採用判断に必要な証拠を説明できる。
- 非公開プロジェクト詳細を追加で要求しない。

## 不合格基準

- `unclassified` の再現条件を見逃す。
- source feedback の期待変更と無関係な改善案になる。
- 評価が yml score へ記録されず、採用判断の証拠として追えない。
- 再現または判断に非公開文脈が必要になる。
