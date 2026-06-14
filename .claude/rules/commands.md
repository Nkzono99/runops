# 主要コマンド一覧

全コマンドは引数省略時にカレントディレクトリをデフォルトとする。

## プロジェクト管理

| コマンド | 説明 |
|---------|------|
| `runops init [SIMS...] -y [--with-refs]` | Project 初期化 (対話型がデフォルト、refs mirror は opt-in) |
| `runops setup [URL] [--with-refs]` | 既存プロジェクトを clone + 環境セットアップ (refs mirror は opt-in) |
| `runops doctor` | 環境検査 |
| `runops context --json` | Agent 向け project context を JSON で取得 |
| `runops plugins [--json] [--check] [--strict]` | project / simulator / site に基づく推奨 Codex plugins を表示・メタデータ検査 |
| `runops lint [PATH] [--scope ...]` | project state と推奨 plugin metadata の health check |
| `runops migrate list/show/apply` | project-state migration の確認・適用 |
| `runops mcp serve --transport stdio` | MCP provider を stdio で起動 |
| `runops mcp serve --transport streamable-http` | MCP provider を Streamable HTTP で起動 |
| `runops mcp check` | MCP registry / safety contract の軽量検査 |
| `runops mcp tools --json` | MCP tool metadata を JSON で表示 |
| `runops mcp resources --json` | MCP resources metadata を JSON で表示 (現状は空) |
| `runops mcp prompts --json` | MCP prompts metadata を JSON で表示 (現状は空) |
| `runops config show` | 設定表示 |
| `runops config add-simulator` | シミュレータ追加 (対話型) |
| `runops config add-launcher` | ランチャー追加 (対話型) |
| `runops update` | シミュレータパッケージのアップグレード |
| `runops update-harness [--plan] [--apply-chain]` | ハーネスファイル再生成 / versioned chain 更新 |
| `runops update-refs` | 任意 refs mirror 更新 + ナレッジインデックス再生成 |

## Case / Run 操作

| コマンド | 説明 |
|---------|------|
| `runops case new CASE [--minimal] [--survey]` | case のスキャフォールド生成 |
| `runops runs create CASE` | case から単一 run を生成 |
| `runops runs sweep [DIR] [--dry-run]` | survey.toml からパラメータ直積で全 run 生成 |
| `runops runs submit [RUN]` | run を sbatch で投入 (`-qn`, `--qos`, `--afterok` 対応) |
| `runops runs submit --all [DIR] [--yes]` | created な run を確認付きで一括投入 (`--yes` で確認省略) |
| `runops runs clone [RUN] [--dest DIR] [--set key=value]` | run 複製・派生。`--set` 使用時は source case から input/job を再生成 |
| `runops runs extend` | スナップショットから継続 run 生成 |
| `runops runs retry [RUN] [--plan]` | failed/cancelled run の retry 準備 (`--plan` は状態を戻さず記録のみ) |
| `runops runs regenerate [RUN] [--dry-run]` | run の `input/` を記録済み case + params から再生成 |

## モニタリング

| コマンド | 説明 |
|---------|------|
| `runops runs status [RUNS...]` | run 状態確認 (複数指定可) |
| `runops runs sync [RUNS...]` | Slurm 状態を manifest に反映 (複数 run 時はサマリ表示) |
| `runops runs log [RUN]` | 最新 job の stdout/stderr 表示 + 進捗% |
| `runops runs jobs [PATH] [--watch SECS]` | 実行中ジョブ一覧 |
| `runops runs dashboard [TARGETS...] [--watch SECS]` | 複数 run の進捗表 |
| `runops runs history [PATH]` | 投入履歴表示 |
| `runops runs list [PATHS...]` | run 一覧表示 |

## 解析・知見

| コマンド | 説明 |
|---------|------|
| `runops analyze summarize [RUN]` | run 解析 summary 生成 |
| `runops analyze collect [DIR]` | survey 集計 |
| `runops analyze plot [DIR]` | survey 集計結果の可視化 |
| `runops analyze export [RUN\|SURVEY] --paper PAPER` | paper-facing export bundle を作成 |
| `runops analyze new-comparison NAME [--source PATH]` | cross-run 比較 workspace (`analysis/cross_run/`) を作成 |
| `runops notes append TITLE [BODY]` | lab notebook に追記 |
| `runops notes list` | active/history の lab notebook 日付一覧 |
| `runops notes show [DATE]` | active/history から指定日の lab notebook を表示 |
| `runops notes archive [--older-than 7d]` | 古い日次 notebook を `notes/history/YYYY/` に移動 |
| `runops knowledge save` | 知見を .runops/insights/ に保存 |
| `runops knowledge add-fact` | 構造化 fact を追加 |
| `runops knowledge list` / `show` / `facts` | 知見の表示 |
| `runops knowledge source attach/detach/sync/render/status` | 外部知識ソース管理 |

## ライフサイクル管理

| コマンド | 説明 |
|---------|------|
| `runops runs archive [RUNS...] [--keep-in-place] [--move-to DIR]` | run アーカイブ (completed のみ。既定で `runs/_archive/` へ移動) |
| `runops runs purge-work [RUN]` | work/ 内の不要ファイル削除 (archived のみ) |
| `runops runs cancel [RUN]` | scancel + sync (submitted/running を停止) |
| `runops runs delete [RUN]` | run ディレクトリ削除 (created/cancelled/failed のみ) |
