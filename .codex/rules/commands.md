# 主要コマンド一覧

全コマンドは引数省略時にカレントディレクトリをデフォルトとする。

## プロジェクト管理

| コマンド | 説明 |
|---------|------|
| `runops init [SIMS...] -y` | Project 初期化 (対話型がデフォルト) |
| `runops setup [URL]` | 既存プロジェクトを clone + 環境セットアップ |
| `runops doctor` | 環境検査 |
| `runops context --json` | Agent 向け project context を JSON で取得 |
| `runops config show` | 設定表示 |
| `runops config add-simulator` | シミュレータ追加 (対話型) |
| `runops config add-launcher` | ランチャー追加 (対話型) |
| `runops update-harness` | ハーネスファイル再生成 |
| `runops update-refs` | refs/ リポジトリ更新 + ナレッジインデックス再生成 |

## Case / Run 操作

| コマンド | 説明 |
|---------|------|
| `runops case new CASE [--minimal] [--survey]` | case のスキャフォールド生成 |
| `runops runs create CASE` | case から単一 run を生成 |
| `runops runs sweep [DIR] [--dry-run]` | survey.toml からパラメータ直積で全 run 生成 |
| `runops runs submit [RUN]` | run を sbatch で投入 (`-qn`, `--qos`, `--afterok` 対応) |
| `runops runs submit --all [DIR]` | created な run を一括投入 |
| `runops runs clone` | run 複製・派生 |
| `runops runs extend` | スナップショットから継続 run 生成 |

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
| `runops notes append TITLE [BODY]` | lab notebook に追記 |
| `runops notes list` | lab notebook 日付一覧 |
| `runops notes show [DATE]` | 指定日の lab notebook を表示 |
| `runops knowledge save` | 知見を .runops/insights/ に保存 |
| `runops knowledge add-fact` | 構造化 fact を追加 |
| `runops knowledge list` / `show` / `facts` | 知見の表示 |
| `runops knowledge source attach/detach/sync/render/status` | 外部知識ソース管理 |

## ライフサイクル管理

| コマンド | 説明 |
|---------|------|
| `runops runs archive [RUN]` | run アーカイブ (completed のみ) |
| `runops runs purge-work [RUN]` | work/ 内の不要ファイル削除 (archived のみ) |
| `runops runs cancel [RUN]` | scancel + sync (submitted/running を停止) |
| `runops runs delete [RUN]` | run ディレクトリ削除 (created/cancelled/failed のみ) |
