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
runo analyze new-comparison <name> --source <run-or-survey> # analysis workspace
runo research new-result <claim-topic>                       # canonical durable Result
```

個々の Run に閉じる成果は Run directory に置きます。`new-comparison` は既存の横断解析
workspace として使えますが、その legacy comparison manifest は canonical seal の対象では
ありません。残す claim は `research new-result` で作り、Run / artifact evidence を明示して
`runo research seal` します。一時試行や goal の大量出力は
`.runops/work/<goal-id>/` に置き、明示昇格するまで active result にしません。

人間向け narrative は Result README 以外へ分散させず、`artifacts/` には Markdown を
作りません。artifact index、再現 command、根拠、限界は README と manifest から辿れる
ようにします。

TestAttempt の T ID と `.runops/test-runs/**` は smoke/debug evidence であり、scientific
Result evidence にはできません。
