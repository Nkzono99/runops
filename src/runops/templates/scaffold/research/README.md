# research/ — 研究判断の台帳

`research/` は、project の **現在の高レベルな研究判断** を隔離して置く場所です。
時系列の作業ログではなく、実行管理ログでもありません。

- `agenda.md` — mutable な現在の研究判断の正本
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
| `research/proposals/` | 実行前の重い判断 | 必要時に新規作成 |
| `research/reviews/` | 過去判断の snapshot | checkpoint ごとに新規作成 |
| `.runops/` | runops の機械状態・curated knowledge | runops command / skill で管理 |

## `agenda.md` の目的

`agenda.md` は TODO リストではなく、判断の台帳です。次の Agent / 人間が
同じ研究判断の地点から再開できるように、次を短く保ちます。

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
改善案だけを書きます。Issue 化するときは `feedback-runops` skill を使います。
