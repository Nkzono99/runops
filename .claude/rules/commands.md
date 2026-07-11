# 主要コマンド一覧

全コマンドは引数省略時にカレントディレクトリをデフォルトとする。
この一覧では推奨 CLI 名の `runo` を使う。`runops` も互換 alias として同じコマンドを実行できる。

## プロジェクト管理

| コマンド | 説明 |
|---------|------|
| `runo init [SIMS...] [--yes] [--with-refs]` | Project 初期化 (対話型がデフォルト、refs mirror は opt-in) |
| `runo setup [URL] [--with-refs]` | 既存プロジェクトを clone + 環境セットアップ (refs mirror は opt-in) |
| `runo doctor` | 環境検査 |
| `runo context --json` | Agent 向け project context を JSON で取得 |
| `runo plugins [--json] [--check] [--strict]` | project / simulator / site に基づく推奨 Codex plugins を表示・メタデータ検査 |
| `runo lint [PATH] [--scope ...]` | project state と推奨 plugin metadata の health check |
| `runo migrate list` | project-state migration 一覧 |
| `runo migrate show MIGRATION [NUMBER]` | migration の詳細表示 |
| `runo migrate apply MIGRATION [NUMBER]` | migration の適用 |
| `runo mcp serve --transport stdio` | MCP provider を stdio で起動 |
| `runo mcp serve --transport streamable-http` | MCP provider を Streamable HTTP で起動 |
| `runo mcp check` | MCP registry / safety contract の軽量検査 |
| `runo mcp tools --json` | MCP tool metadata を JSON で表示 |
| `runo mcp resources --json` | MCP resources metadata を JSON で表示 (現状は空) |
| `runo mcp prompts --json` | MCP prompts metadata を JSON で表示 (現状は空) |
| `runo config show` | 設定表示 |
| `runo config add-simulator` | シミュレータ追加 (対話型) |
| `runo config add-launcher` | ランチャー追加 (対話型) |
| `runo update [--yes]` | シミュレータパッケージのアップグレード (`--force` は hidden compatibility alias) |
| `runo update-harness [--plan] [--apply-chain]` | ハーネスファイル再生成 / versioned chain 更新 |
| `runo update-refs` | 任意 refs mirror 更新 + ナレッジインデックス再生成 |

## Case / Run 操作

| コマンド | 説明 |
|---------|------|
| `runo case new CASE [--minimal] [--survey]` | case のスキャフォールド生成 |
| `runo runs create CASE` | case から単一 run を生成 |
| `runo runs sweep [DIR] [--dry-run]` | survey.toml からパラメータ直積で全 run 生成 |
| `runo runs submit [RUN]` | run を sbatch で投入 (`-qn`, `--qos`, `--afterok` 対応) |
| `runo runs submit --all [DIR] [--yes]` | ready plan を一括投入。survey は structured experiment gate 必須 (`--yes` は確認のみ省略) |
| `runo runs clone [RUN] [--dest DIR] [--set key=value]` | run 複製・派生。`--set` 使用時は source case から input/job を再生成 |
| `runo runs extend` | スナップショットから継続 run 生成 |
| `runo runs retry [RUN] [--plan]` | failed/cancelled run の retry 準備 (`--plan` は状態を戻さず記録のみ) |
| `runo runs regenerate [RUN] [--dry-run]` | run の `input/` を記録済み case + params から再生成 |

## モニタリング

| コマンド | 説明 |
|---------|------|
| `runo runs status [RUNS...]` | run 状態確認 (複数指定可) |
| `runo runs sync [RUNS...]` | Slurm 状態を manifest に反映 (複数 run 時はサマリ表示) |
| `runo runs log [RUN]` | 最新 job の stdout/stderr 表示 + 進捗% |
| `runo runs jobs [PATH] [--watch SECS]` | 実行中ジョブ一覧 |
| `runo runs dashboard [TARGETS...] [--watch SECS]` | 複数 run の進捗表 |
| `runo runs history [PATH]` | 投入履歴表示 |
| `runo runs list [PATHS...]` | run 一覧表示 |

## 解析・知見

| コマンド | 説明 |
|---------|------|
| `runo analyze summarize [RUN]` | run 解析 summary 生成 |
| `runo analyze collect [DIR]` | survey 集計 |
| `runo analyze plot [DIR]` | survey 集計結果の可視化 |
| `runo analyze export [RUN\|SURVEY] --paper PAPER` | paper-facing export bundle を作成 |
| `runo analyze new-comparison NAME [--source PATH]` | cross-run 比較 workspace (`analysis/cross_run/`) を作成 |
| `runo analyze new-story NAME [--id ID] [--title TITLE] [--source PATH]` | story acceptance audit workspace (`analysis/stories/`) を作成。relative source は project root 基準 |
| `runo analyze audit-story [STORY_DIR]` | story の要求 step と artifact index を照合し `audit.json` / `audit.md` を生成 |
| `runo notes append TITLE [BODY]` | lab notebook に追記 |
| `runo notes list` | active/history の lab notebook 日付一覧 |
| `runo notes show [DATE]` | active/history から指定日の lab notebook を表示 |
| `runo notes archive [--older-than 7d]` | 古い日次 notebook を `notes/history/YYYY/` に移動 |
| `runo knowledge save NAME` | 知見を `.runops/insights/` に保存 |
| `runo knowledge list` | 知見一覧 |
| `runo knowledge show NAME` | 指定知見を表示 |
| `runo knowledge add-fact CLAIM` | 構造化 fact を追加 |
| `runo knowledge facts` | fact 一覧・検索 |
| `runo knowledge promote-fact FACT_ID` | imported candidate fact を local curated fact へ昇格 |
| `runo knowledge source list` | 外部知識ソース一覧 |
| `runo knowledge source attach SOURCE_TYPE NAME URL_OR_PATH` | 外部知識ソース追加 |
| `runo knowledge source detach NAME` | 外部知識ソース削除 |
| `runo knowledge source sync [SOURCE_NAME]` | 外部知識ソース同期 |
| `runo knowledge source render` | knowledge import 表示を再生成 |
| `runo knowledge source status` | 外部知識ソース状態表示 |
| `runo knowledge profile enable SOURCE_NAME PROFILE_NAMES...` | source profile を有効化 |
| `runo knowledge profile disable SOURCE_NAME PROFILE_NAMES...` | source profile を無効化 |

## Experiment workflow

| コマンド | 説明 |
|---------|------|
| `runo experiment new NAME [--from SPEC] [--dry-run] [--yes] [--json]` | schema 2 ledger と proposal を原子的に作成。`--json` は `--yes` がない限り plan のみ返す |
| `runo experiment show [EXPERIMENT] [--json]` | ledger、survey、run、artifact から導出した phase と次の操作を表示 |
| `runo experiment check [EXPERIMENT] [--json]` | experiment の参照整合性を検査。error があれば exit 1 |

## Demo replay

| コマンド | 説明 |
|---------|------|
| `runo demo import-codex-session SESSION_LOG --out PATH` | Codex session JSONL を正規化 event JSONL へ変換 |
| `runo demo render-replay EVENTS --out PATH` | event JSONL から self-contained replay HTML を生成 |
| `runo demo build-codex-replay [SESSION_LOG] --out PATH` | session import と replay HTML 生成を一括実行 |

## ライフサイクル管理

| コマンド | 説明 |
|---------|------|
| `runo runs archive [RUNS...] [--keep-in-place] [--move-to DIR]` | run アーカイブ (completed のみ。既定で `runs/_archive/` へ移動) |
| `runo runs purge-work [RUN]` | work/ 内の不要ファイル削除 (archived のみ) |
| `runo runs cancel [RUN]` | scancel + sync (submitted/running を停止) |
| `runo runs delete [RUN]` | run ディレクトリ削除 (created/cancelled/failed のみ) |
