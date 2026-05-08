# 主要コマンド一覧

全コマンドは引数省略時にカレントディレクトリをデフォルトとする。
この一覧では推奨 CLI 名の `runo` を使う。`runops` も互換 alias として同じコマンドを実行できる。

## プロジェクト管理

| コマンド | 説明 |
|---------|------|
| `runo init [SIMS...] -y` | Project 初期化 (対話型がデフォルト) |
| `runo setup [URL]` | 既存プロジェクトを clone + 環境セットアップ |
| `runo doctor` | 環境検査 |
| `runo context --json` | Agent 向け project context を JSON で取得 |
| `runo migrate list/show/apply` | project-state migration の確認・適用 |
| `runo config show` | 設定表示 |
| `runo config add-simulator` | シミュレータ追加 (対話型) |
| `runo config add-launcher` | ランチャー追加 (対話型) |
| `runo update-harness` | ハーネスファイル再生成 |
| `runo update-refs` | refs/ リポジトリ更新 + ナレッジインデックス再生成 |

## Case / Run 操作

| コマンド | 説明 |
|---------|------|
| `runo case new CASE [--minimal] [--survey]` | case のスキャフォールド生成 |
| `runo runs create CASE` | case から単一 run を生成 |
| `runo runs sweep [DIR] [--dry-run]` | survey.toml からパラメータ直積で全 run 生成 |
| `runo runs submit [RUN]` | run を sbatch で投入 (`-qn`, `--qos`, `--afterok` 対応) |
| `runo runs submit --all [DIR]` | created な run を一括投入 |
| `runo runs clone` | run 複製・派生 |
| `runo runs extend` | スナップショットから継続 run 生成 |
| `runo runs retry [RUN] [--plan]` | failed/cancelled run の retry 準備 (`--plan` は状態を戻さず記録のみ) |

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
| `runo analyze new-comparison NAME [--source PATH]` | cross-run 比較 workspace (`analysis/cross_run/`) を作成 |
| `runo notes append TITLE [BODY]` | lab notebook に追記 |
| `runo notes list` | active/history の lab notebook 日付一覧 |
| `runo notes show [DATE]` | active/history から指定日の lab notebook を表示 |
| `runo notes archive [--older-than 7d]` | 古い日次 notebook を `notes/history/YYYY/` に移動 |
| `runo knowledge save` | 知見を .runops/insights/ に保存 |
| `runo knowledge add-fact` | 構造化 fact を追加 |
| `runo knowledge list` / `show` / `facts` | 知見の表示 |
| `runo knowledge source attach/detach/sync/render/status` | 外部知識ソース管理 |

## ライフサイクル管理

| コマンド | 説明 |
|---------|------|
| `runo runs archive [RUN]` | run アーカイブ (completed のみ) |
| `runo runs purge-work [RUN]` | work/ 内の不要ファイル削除 (archived のみ) |
| `runo runs cancel [RUN]` | scancel + sync (submitted/running を停止) |
| `runo runs delete [RUN]` | run ディレクトリ削除 (created/cancelled/failed のみ) |
