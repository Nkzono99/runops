---
name: research-workspace
description: Use when the requested outcome is one bounded research-memory transition such as append, rotate, promote, archive, or validation.
---

# research memoryを一つの要求状態へ移す

## 実行契約

- **Goal**: 指定された研究記憶を適切な層へappend、rotate、promote、archiveする
- **Done**: 更新先、保持したsource、結果IDまたはarchive状態、check結果を報告できる
- **Budget**: 一つのmemory transitionと対象artifact。設定済みline / byte budget内
- **Invariant**: evidenceを削除・要約置換せず、AIが重要度を推測して自動昇格しない

## Storage routing

| memory | canonical location / command |
|---|---|
| 現在の問い・判断・次の一手 | `research/CURRENT.md`（50 行目安。時系列やartifact 一覧を置かない） |
| 時系列の作業記録 | `runo research append` → `research/journal/` |
| durable result | `runo research new-result` → `research/results/RNNNN-*/` |
| inactive result | `runo research archive RNNNN` |
| temporary work | `.runops/work/<goal-id>/` |

`runo research status`で該当budgetだけを確認し、選んだtransitionを実行して
`runo research check`でDoneを検証する。journal rotationはCLIの自動処理を優先し、必要時だけ
`runo research rotate --force`を使う。

resultの人向け説明は`README.md`一枚、実体は`artifacts/`に置く。`artifacts/` に Markdown を作らない。
同じ論理データのCSV / JSON / Markdown重複も作らない。
