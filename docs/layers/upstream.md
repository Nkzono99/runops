# Upstream Integration Layer

Upstream Integration Layer は、生成 project と runops 本体をつなぐ境界です。
runops local patch、`feedback-runops` / HarnessOps feedback、PR、`update-runops`
で迷った場合はこの文書を正本とします。

## 目的

通常の生成 project には `tools/runops/` を置かず、runops CLI は
`uvx --from runops runo ...` で実行します。project `.venv/` は simulator package、
解析依存、runtime tool 用です。Agent の確認入口は `.runops/knowledge/runops/`、
`uvx --from runops runo context --json`、`uvx --from runops runo --help`、
package metadata です。

runops 本体の修正が必要な場合は、project とは別の source checkout で扱います。
この層の目的は、次の 4 つを分けることです。

- current project で今すぐ必要な local patch
- 汎用化できる runops upstream 改善
- project 固有なので upstream に入れない変更
- runops 更新時に project 側へ適用する migration

## 基本方針

- local patch の正本は別 checkout 内の Git branch / commit とする。
- project 側の研究状態や harness override を runops 本体の変更と混ぜない。
- current project での確認結果は `notes/YYYY-MM-DD.md` に残す。
- 互換性を切る変更は `docs/migrations/` に migration item として残す。
  v0 系では後方互換 layer を長く維持せず、migration guide による移行を優先する。
- 長期化して複数 patch が並ぶ場合だけ、`notes/reports/runops-local-patches.md`
  のような project-local index を作ってよい。
- `runo update-harness` は runops source checkout を pull しない。現在 `uvx` で
  実行中の package を正として project harness を再生成し、`.runops/harness.lock`
  に適用済み runops version を記録する。
- HarnessOps が利用できる環境では、`runo init` / `runo setup` は project 側
  overlay 初期化を連鎖し、`runo update-harness` は overlay 更新を連鎖する。
  HarnessOps 管理ファイルは runops が直接書かず、すべて HarnessOps CLI に委譲する。
  生成 guidance で直接呼ぶ場合は PATH 上の `hops` に依存せず
  `uvx --from harnessops hops ...` を使う。

## 標準フロー

1. current project で runops 本体の bug / 不足機能 / harness 摩擦を見つける。
2. `patch-runops` skill で project 外の runops source checkout に branch を作る。
3. source checkout 内で実装し、必要なテストを走らせる。
4. 必要な場合だけ current project の `.venv` に一時 install して実挙動を確認する。
5. 結果を `notes/YYYY-MM-DD.md` に残す。
6. upstream disposition を分類する。
7. 必要なら `feedback-runops` で HarnessOps record / issue 下書き、draft PR、ready PR に進める。

## Upstream Disposition

| 判定 | 意味 | 次の動き |
|------|------|----------|
| `local-only` | project 固有 | project 側に残す |
| `feedback-issue` | 一部汎用 / 設計が必要 / draft PR には早い | `feedback-runops` で HarnessOps record / issue 下書き |
| `draft-pr` | 実装案も見せたいが設計レビューが必要 | draft PR |
| `ready-pr` | 小さく汎用でテスト済み | 通常 PR |

`feedback-runops` は PR の弱い代替ではありません。local patch や運用上の摩擦を
HarnessOps の record とサニタイズ済み upstream 設計下書きに変換するための
中間レイヤーです。

## Upstream に入れないもの

project 側の生成物や研究状態を、そのまま runops 本体に入れない。

- `.agents/skills/*`
- `.claude/skills/*`
- `AGENTS.md`
- `CLAUDE.md`
- `research/*`
- `notes/*`
- `campaign.toml`
- `cases/*`
- `runs/*`

汎用化する場合は、source template / command / docs に戻します。

| project 側で見つけたもの | upstream に戻す場所 |
|--------------------------|---------------------|
| `.agents/skills/foo/SKILL.md` / `.claude/skills/foo/SKILL.md` | runops checkout の `src/runops/templates/skills/foo/SKILL.md` |
| `AGENTS.md` / `CLAUDE.md` 改善 | runops checkout の `src/runops/templates/harness/` |
| `research/` scaffold 改善 | runops checkout の `src/runops/templates/scaffold/research/` |
| `notes/` scaffold 改善 | runops checkout の `src/runops/templates/scaffold/notes/` |
| CLI / core / adapter / launcher bug | runops checkout の `src/runops/` |
| docs gap | runops checkout の `docs/` |

## `update-runops`

`update-runops` は `uvx` で最新の runops package を実行し、
`runo update-harness --plan` で project 側の generated harness と generated knowledge の
versioned upgrade chain を確認してから、`runo update-harness --apply-chain` で
exact version を順に踏んで再生成します。

Harness 更新後は release note / migration guide と `runo migrate list` を確認します。
該当 item がある場合は、定型 migration なら `runo migrate apply <id> --dry-run`
で確認してから `runo migrate apply <id>` で適用します。CLI 未対応または判断が
必要なものは `migrate-runops` skill に渡し、適用 / skip / defer を
`notes/YYYY-MM-DD.md` に残します。

Migration guide にない破壊的変更や schema rewrite を推測で実行しない。
guide が不足している場合は `feedback-runops` で docs gap として HarnessOps に記録します。

## SemVer と migration

runops が private / pre-public な v0 系である間は、古い CLI option、内部 API、
project file format の互換 shim を長く維持しません。

- `0.x`: breaking change は許容する。ただし project-state に影響するものは
  `docs/migrations/v0.md` に移行方法を書く。
- `1.x` 以降: CLI、project schema、manifest、analysis artifact schema を
  public contract とみなし、breaking change は major version bump と migration guide を必要とする。
- patch release: 原則として移行不要な bug fix に限定する。

## Issue / PR に入れる情報

`feedback-runops` の HarnessOps record / issue 下書き、または PR には、必要に応じて次を含めます。

- 問題の短い説明
- current project で困った workflow
- 再現手順
- 期待する挙動
- 実際の挙動
- workaround
- local branch / commit
- どこまで project 固有で、どこから汎用か
- private path / unpublished result を含まないことの確認

## 他レイヤとの関係

- Harness Layer の改善は template に戻す。
- Experiment / Execution Kernel / Analysis / Research / Knowledge Layer の project 状態は upstream に直接入れない。
- upstream 化した改善は、次回 `runo update-harness` / `update-runops` で project 側に戻る。
