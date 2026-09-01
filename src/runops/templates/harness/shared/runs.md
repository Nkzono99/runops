# runs/ ディレクトリ

ここには formal simulation Run が格納される。すべて `runo runs create` または
`runo runs sweep --apply --point|--all --expect-plan` で生成する。引数なしの `sweep` は
read-only plan であり、directory を作らない。

## 構造

```
runs/<path>/Rxxxx/
  manifest.toml      # 正本 (状態・由来・provenance)
  input/             # 入力ファイル (自動生成)
  submit/            # job.sh 等 (自動生成)
  work/              # 実行時出力 (.gitignore 対象)
  analysis/          # 解析結果
```

## ルール

- run ディレクトリ (`Rxxxx/`) を手で作らない
- smoke / debug は `runo test smoke|debug` を使い、`.runops/test-runs/T.../` に分離する
- `manifest.toml` を手動編集しない
- `input/*`, `submit/job.sh` を直接作らない
- 状態確認は `runo runs status`、同期は `runo runs sync`
- run 単体の解析は `runo analyze summarize`、survey 集計は `runo analyze collect`
- 複数 run / survey をまたぐ残す claim は `runo research new-result` で
  `research/results/RNNNN-<id>/` を作り、evidence を seal する
- 試行中の図・メモ・一時解析物は `.runops/work/<goal-id>/` に置く
- 永続的な研究 prose は CURRENT、journal、Result README だけに置き、別名の note も作らない
- terminal outcome は `runo runs review` で確認するが、evidence の採否は Result 側で決める
- Result seal 前に included Run の completed 相当、理由付き review、identity / source / baseline / input snapshot を確認する
- Result seal には `--selection-reason` を付け、includeしたRun-owned outputを`purge-work`で削除しない
- 新しいExperiment/Runを増やす前に`runo triage`でactive work、review backlog、古いTestAttempt/stagingを確認する
