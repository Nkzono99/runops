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
| `runo runs create CASE [--label LABEL]` | case から単一 run を生成。label は directory suffix と display name に使う |
| `runo runs sweep [DIR] [--dry-run]` | survey.toml から全 run を生成。semantic label と directory preview を決定的に生成 |
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
| `runo runs sync [RUNS...]` | Slurm 状態を manifest に反映。terminal transition では bounded readiness と次 command も返す |
| `runo runs log [RUN]` | 最新 job の stdout/stderr 表示 + 進捗% |
| `runo runs jobs [PATH] [--watch SECS]` | 実行中ジョブ一覧 |
| `runo runs dashboard [TARGETS...] [--watch SECS] [--all]` | 複数 run の進捗表。`--all` では cached analysis / next action も表示 |
| `runo runs history [PATH]` | 投入履歴表示 |
| `runo runs list [PATHS...] [--include-archived]` | run 一覧と cached analysis / next action を表示。既定では archived / purged と archived bundle 配下を除外 |

## 解析・知見

| コマンド | 説明 |
|---------|------|
| `runo analyze summarize [RUN]` | run 解析 summary 生成 |
| `runo analyze collect [DIR]` | survey 集計 |
| `runo analyze plot [DIR]` | survey 集計結果の可視化 |
| `runo analyze export [RUN\|SURVEY] --paper PAPER [--accept-incomplete-reason WHY]` | paper-facing export bundle を作成。incomplete を accepted にする場合は理由必須 |
| `runo analyze new-story NAME [--id ID] [--title TITLE] [--source PATH]` | story acceptance audit workspace (`analysis/stories/`) を作成。relative source は project root 基準 |
| `runo analyze audit-story [STORY_DIR]` | story の要求 step と artifact index を照合し `audit.json` / `audit.md` を生成 |
| `runo research status [PATH]` | active research の文字数・件数・bytes を表示 |
| `runo research check [PATH]` | budget と配置規則を検査 |
| `runo research append TITLE BODY` | bounded journal に追記し必要なら自動 rotation |
| `runo research rotate [PATH] [--force]` | journal を原文のまま numbered archive へ移す |
| `runo research new-result NAME` | README 1 枚と artifacts/ を持つ result を作成 |
| `runo research archive RESULT_ID` | active result を可逆 archive |
| `runo research restore RESULT_ID` | archived result を復元 |
| `runo research migrate-legacy [--dry-run|--restore]` | 旧 research/notes/analysis/HarnessOps 構成を可逆移行 |
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

## Demo replay

| コマンド | 説明 |
|---------|------|
| `runo demo import-codex-session SESSION_LOG --out PATH` | Codex session JSONL を正規化 event JSONL へ変換 |
| `runo demo render-replay EVENTS --out PATH` | event JSONL から self-contained replay HTML を生成 |
| `runo demo build-codex-replay [SESSION_LOG] --out PATH` | session import と replay HTML 生成を一括実行 |

## ライフサイクル管理

| コマンド | 説明 |
|---------|------|
| `runo runs archive [RUNS...] [--keep-in-place] [--move-to DIR] [--bundle] [--adopt-archived]` | 通常は completed run を archive。`--bundle` は親ディレクトリ全体を移動し、配下 run state を保持。`--adopt-archived` は同じ親から個別 archive 済みの run を検証して bundle へ採用 |
| `runo runs restore RUN [--bundle]` | 通常は archived run を復元。`--bundle` は親ディレクトリ全体を archive 前の場所へ復元 |
| `runo runs purge-work [RUN] [--discard-incomplete --reason WHY]` | work/ 内の不要ファイル削除。既知の non-ready output を破棄する場合は理由必須 |
| `runo runs cancel [RUN]` | scancel + sync (submitted/running を停止) |
| `runo runs delete [RUN]` | run ディレクトリ削除 (created/cancelled/failed のみ) |
