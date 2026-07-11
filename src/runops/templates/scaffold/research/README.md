# research/ — 研究判断の台帳

`research/` は、project の **現在の高レベルな研究判断** を隔離して置く場所です。
時系列の作業ログではなく、実行管理ログでもありません。

- `agenda.md` — mutable な現在の研究判断の正本
- `paper_requests.toml` — paper draft から戻る解析・図表・追加実験要望
- `experiments.toml` — candidate comparison と pilot/full gate の機械正本
- `proposals/` — 高コスト・方向転換・新 model など、実行前に残す任意の判断記録
- `reviews/` — 主要結果・意外な失敗・pause/kill/pivot などの checkpoint snapshot

本文は日本語で書きます。コード、コマンド、変数名、run_id、ファイルパス、
エラーメッセージは英語または実際の表記のまま残します。

## 他レイヤーとの関係

| 場所 | 役割 | 更新方針 |
|------|------|----------|
| `campaign.toml` | 研究目的・仮説・変数・観測量 | 研究憲章として慎重に編集 |
| `notes/YYYY-MM-DD.md` | 日次 lab notebook | append-only |
| `notes/reports/` | 整理済み long-form report | 改稿可 |
| `research/agenda.md` | 現在の研究判断 | mutable |
| `research/paper_requests.toml` | paper draft 由来の要望 | structured queue |
| `research/proposals/` | 実行前の重い判断 | 必要時に新規作成 |
| `research/reviews/` | 過去判断の snapshot | checkpoint ごとに新規作成 |
| `.runops/` | runops の機械状態・curated knowledge | runops command / skill で管理 |

## `agenda.md` の目的

`agenda.md` は TODO リストではなく、判断の台帳です。次の Agent / 人間が
同じ研究判断の地点から再開できるように、次を短く保ちます。

**agenda.md is not an artifact ledger.**
Do not put chronological notes or artifact inventories back into agenda.md.
時系列の作業ログは `notes/YYYY-MM-DD.md`、整理済み report の入口は
`notes/reports/README.md`、複数 run 比較の機械的 artifact は
`analysis/cross_run/<comparison_id>/` に分けます。

- 今、何を信じているか
- その根拠はどこにあるか
- 何が未解決か
- なぜ次にそれをやるのか
- 何が出たら判断を変えるのか
- 何を今はやらないのか

## proposal / review を作る条件

普段は `agenda.md` だけで十分です。次の場合だけ `proposals/` や `reviews/` を
使います。

`proposals/` を作る目安:

- production sweep
- 新しい physical model family
- 高コストな rerun
- campaign-level assumption の変更
- report / paper レベルの主張

`reviews/` を作る目安:

- 主要 result が出た
- failed / surprising run が出た
- 同じ story が 3 件以上の note に分散した
- pivot / pause / kill を決めた

## Pilot → review → expand

production / large survey は次の順で進めます。

1. `research-director` で proposal、falsification、pilot、stop / expand criterion を定義
2. `survey-design` で pilot point と full matrix candidate を分離
3. `run-all` で pilot だけを投入
4. `review-pilot` で `research/reviews/<date>-<topic>.md` を作成
5. review と agenda の decision がともに `EXPAND` の場合だけ remaining run を full submit

survey-backed bulk submit は `survey.toml [research]` の `experiment_id` / `stage` と
`experiments.toml` を機械検査する。full stage は EXPAND と review path が必須。

`--yes` は CLI prompt を省略するだけで、この research gate は省略しません。

## Human gate

次の判断には human gate が必要です。

- 新しい campaign-level goal
- 新しい physical model family
- production sweep
- 高コストな rerun
- 重要 result の archive / purge / delete
- 外部発表・論文化レベルの claim

## runops への feedback

研究上の未解決事項は `Feedback To runops` に入れません。そこには、
runops 本体に戻すべき繰り返しの摩擦、missing command、docs gap、bug、
改善案だけを書きます。共有するときは `feedback-runops` skill で HarnessOps に
記録し、サニタイズ済み issue 下書きを作ります。

## paper request

paper draft から「追加解析が必要」「この条件の run を追加したい」
「この export は placeholder 扱い」などの要望が出た場合は、
`paper_requests.toml` に structured request として置けます。これは自動実行の
指示ではなく、`agenda.md` や必要な proposal に戻すための handoff です。

追加実験の run creation / survey expansion / submit は、必ず別の明示操作として
扱います。
