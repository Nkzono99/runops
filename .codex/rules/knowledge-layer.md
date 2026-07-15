# 知識層 (Knowledge Layer)

研究作業の active memory は、日数ではなく量で上限を持つ。

| 種類 | 保存先 | 規則 |
|---|---|---|
| 現在判断 | `research/CURRENT.md` | mutable。既定 20,000 Unicode 文字以内 |
| 時系列ログ | `research/journal/active.md` | append-only。既定 64,000 文字で原文のまま `archive/JNNNN.md` へ rotation |
| 残す解析 | `research/results/RNNNN-topic/` | narrative は `README.md` 1 枚、実体は `artifacts/` |
| 一時作業 | `.runops/work/<goal-id>/` | provisional、Git 管理しない |
| 人間提供資料 | `materials/` | source material。解析結果の置き場にしない |
| 機械的再利用知識 | `.runops/insights/`, `.runops/facts.toml` | advanced curated store |

`artifacts/` 以下に Markdown を置かない。同じ論理データを CSV/JSON/Markdown の
複数形式で重複保存しない。AI は重要度を推測して evidence を削除・要約置換せず、
人が選んだ結果だけ `runo research new-result` で昇格する。

```bash
runo research status
runo research append "<title>" "<body>"
runo research rotate --force
runo research new-result <topic>
runo research archive R0001-topic
runo research restore R0001-topic
runo research migrate-legacy --dry-run
runo research check
```

旧 `notes/`、`analysis/cross_run/`、分散 Markdown、HarnessOps metadata は
`runo research migrate-legacy` で内容を変更せず recovery archive へ移す。移行は
`--restore` で戻せる。削除・purge はこの workflow に含めない。
