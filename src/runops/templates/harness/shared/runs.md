# runs/ ディレクトリ

ここには simulation run が格納される。すべて `runo runs create` / `runo runs sweep` で生成。

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
- `manifest.toml` を手動編集しない
- `input/*`, `submit/job.sh` を直接作らない
- 状態確認は `runo runs status`、同期は `runo runs sync`
- 解析は `runo analyze summarize` / `runo analyze collect`
- 試行中の図・メモ・一時解析物は `analysis/scratch/` に置く
- 共有したい図や summary は `analysis/` の curated 出力に昇格する
