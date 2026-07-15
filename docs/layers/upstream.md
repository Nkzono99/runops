# Upstream Integration Layer

生成 project と runops 本体の変更を混ぜないための境界です。

- project 固有の `campaign.toml`, `research/`, `cases/`, `runs/` は project に残す。
- 汎用 CLI / core / adapter / template の修正は別の runops source checkout で行う。
- local patch の正本はその checkout の branch / commit とする。
- project での確認結果は `runo research append` で残す。
- issue / PR には private path、未公開 result、site 固有情報を含めない。

| 判定 | 次の動き |
|---|---|
| `local-only` | project 側に残す |
| `feedback-issue` | project 固有情報を除いた issue 下書きを作る |
| `draft-pr` | 設計レビュー用 draft PR |
| `ready-pr` | テスト済み通常 PR |

生成された `AGENTS.md` / skills の改善は、runops checkout の
`src/runops/templates/` に戻します。更新時は `runo update-harness --plan` と
`--apply-chain` を使い、project-state migration は `runo migrate` または
`runo research migrate-legacy --dry-run` で別に確認します。
