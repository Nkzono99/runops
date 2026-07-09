# Notes Reports Index

この directory は、日次 note が肥大化した内容を整理済み report として読む入口です。
新しい report を追加したら、この README の reading order または entry points を
更新してください。

## Recommended Reading Order

1. `<topic>.md`
   - 現在の判断や解析 story に戻るための短い入口。

## Machine-Readable Entry Points

- `analysis/cross_run/<comparison_id>/README.md`
- `analysis/cross_run/<comparison_id>/data/`
- `analysis/cross_run/<comparison_id>/figures/`
- `analysis/cross_run/<comparison_id>/reports/`

## Source Material Entry Points

- `materials/README.md`
- `materials/index.toml`

## Figures

- 代表図は Markdown image (`![caption](relative/path.png)`) として report 本文に
  埋め込みます。リンク一覧だけで代替しません。
- report 専用の図は `notes/reports/figures/` に置きます。
- run-local / cross-run analysis から来る図は、元の
  `runs/<run>/analysis/figures/` または `analysis/cross_run/<comparison_id>/figures/`
  へ相対 path で参照します。

## Heavy / Recovery-Only Material

通常の再開では通読しない長文ログ、旧版 report、full artifact list は
`notes/reports/archive/` または `notes/history/YYYY/*-full-log.md` に置き、
この README から必要時だけ到達できるようにしてください。

## Current Organization Policy

- 日次 note は append-only の時系列ログとして残す。
- 同じ story が複数 entry にまたがる場合は、`notes/reports/<topic>.md` へ昇格する。
- `research/agenda.md` には現在判断、active question、next action だけを残す。
- 詳細 artifact list は report 本文ではなく `analysis/cross_run/<comparison_id>/data/`
  や source index に寄せる。
- 旧版の長文 report は `notes/reports/archive/` に退避し、元の path には短い入口を残す。
