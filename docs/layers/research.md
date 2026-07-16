# Research Layer

Research Layer は active research memory を量で制限し、AI の重要度推測に依存せず
長期再開可能にする層です。

```text
research/
  CURRENT.md
  journal/active.md
  journal/archive/JNNNN.md
  results/RNNNN-topic/{README.md,manifest.toml,artifacts/}
  archive/results/
.runops/work/<goal-id>/
```

`CURRENT.md` は現在の問い、判断、次の一手だけを置く入口です。journal は append-only
で、日数ではなく文字数により原文のまま rotation します。結果は人が残すと決めた
ものだけ `results/` に昇格し、説明を README 1 枚へ集約します。

`CURRENT.md` は既定 50 行を目安にし、path 参照 10 件、日付・時刻で始まる見出し 3 件を
越えると warning を出します。これは通常作業を止める hard gate ではありません。
時系列は `runo research append`、残す詳細解析は `results/`、網羅的な artifact provenance は
export/source index に置き、`CURRENT.md` を日誌や inventory に戻さないでください。

```bash
runo research status
runo research append "<title>" "<body>"
runo research new-result <topic>
runo research archive R0001-topic
runo research check
```

`artifacts/` に Markdown を置かず、同じ論理データの形式違いコピーを避けます。
AI は既存 evidence を削除または要約置換しません。archive は可逆で、purge はありません。

旧構成は `runo research migrate-legacy --dry-run` で移動一覧を確認してから適用し、
必要なら `--restore` で戻します。
