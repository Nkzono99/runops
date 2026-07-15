# Analysis Layer

Analysis Layer は run-local summary、survey 集計、cross-run result を扱います。

| 種類 | 場所 |
|---|---|
| run-local summary | `runs/**/analysis/` |
| survey table/plot | `<survey>/summary/` |
| cross-run comparison | `research/results/RNNNN-<id>/` |
| comparison data/figure/script | result の `artifacts/` |
| interpretation | result の `README.md` 1 枚 |

```bash
runo analyze summarize <run>
runo analyze collect <survey>
runo analyze plot <survey>
runo analyze new-comparison <name> --source <run-or-survey>
```

個々の run に閉じる成果は run directory に置きます。複数 run/survey をまたぐ解析は
`new-comparison` で durable result として作ります。一時試行や goal の大量出力は
`.runops/work/<goal-id>/` に置き、明示昇格するまで active result にしません。

人間向け narrative は result README 以外へ分散させず、`artifacts/` には Markdown を
作りません。artifact index、再現 command、根拠、限界は README と manifest から辿れる
ようにします。
