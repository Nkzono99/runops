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
| 時系列の作業記録 | `runo research append --kind ... --subject ...` → `research/journal/` |
| durable Result | `runo research new-result` → edit → `runo research seal` |
| inactive result | `runo research archive RNNNN` |
| temporary work | `.runops/work/<goal-id>/` |

`runo research status`で該当budgetだけを確認し、選んだtransitionを実行して
`runo research check`でDoneを検証する。journal rotationはCLIの自動処理を優先し、必要時だけ
`runo research rotate --force`を使う。

Resultの人向け説明は`README.md`一枚、実体は`artifacts/`に置く。`artifacts/` に Markdown を作らない。
同じ論理データのCSV / JSON / Markdown重複も作らない。

Resultはclaimごとのevidence inclusion / exclusion edgeを所有する。Runの`review_status`を
evidence selectionとして使わない。seal前に`runo research check-result`、seal後にも同commandで
source receiptを検証する。included Run / Run-owned artifactはcompleted相当、理由付きreview、
identity hashes、source commit / executable hash / version、baseline、input snapshotを要求し、
dirty sourceはdiff参照も確認する。T IDと`.runops/test-runs/**`はscientific evidenceとして指定しない。
sealには`--selection-reason`を必須とし、includeしたRun-owned outputを`purge-work`で削除しない。

永続的な研究 prose は `research/CURRENT.md`、`research/journal/*.md`、各 Result
の `README.md` だけに置く。別名の note も新規作成しない。provisional prose は
`.runops/work/`、時系列はjournal、現在判断はCURRENT、durable narrativeはResult READMEへ置く。
