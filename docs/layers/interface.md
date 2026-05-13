# Interface Layer

Interface Layer は、Agent、harness、人間 operator が runops の project state に触る
境界です。

ここでいう interface は「人間が日常的に CLI を覚えて叩く画面」ではありません。
通常の研究運用では、人間は Agent に研究意図と確認を渡し、Agent が runops の
interface を使って Execution Kernel や Experiment Layer を更新します。

## 位置づけ

runops の CLI は、以下のためにあります。

- Agent が project state を構造化された経路で読み書きする
- harness が高コスト操作や破壊的操作に gate をかける
- 人間 operator が bootstrap、debug、CI、緊急時の確認を行う
- CLI の外側にある会話 UI、skills、rules から core action を呼ぶ

CLI は重要ですが、研究者が日常的に CLI の全体を操作する前提にはしません。
人間向けの主導線は [../get-started-with-agent.md](../get-started-with-agent.md) です。

## 他 Layer との境界

| Layer | Interface Layer から見た関係 |
|-------|------------------------------|
| Experiment Layer | `campaign.toml`、case、survey を生成・検証する入口 |
| Execution Kernel | run 生成、submit、sync、status、manifest 更新の入口 |
| Analysis Layer | summarize / collect / plot / export の入口 |
| Research Layer | agenda / notebook / report へ判断を戻す入口 |
| Knowledge Layer | notes、facts、external source、rendered context を扱う入口 |
| Harness Layer | permissions、skills、rules、confirmation gate を介して interface を制御 |
| Upstream Integration Layer | update、migration、local patch、feedback issue を扱う入口 |

`src/runops/cli/` は実装上の module です。Interface Layer はそれより広く、
CLI command、Agent-facing action facade、project harness、確認フローを含む
運用上の境界として扱います。

Agent-facing action は `src/runops/core/actions/specs.py` の `ActionSpec` を
machine-readable な契約として持ちます。各 action spec には対応する CLI command
path と MCP tool 名を記録し、テストで Typer の登録済み command と MCP registry
に存在することを確認します。これにより CLI / action facade / MCP metadata の
drift を早期に検出します。

## 原則

- **正本は Interface Layer ではなく各 Layer に置く**  
  CLI output や会話ログを正本にしない。run 状態は `manifest.toml`、
  研究判断は `research/agenda.md`、実験設計は case / survey に戻す。

- **生成物を直接編集しない**  
  `manifest.toml`、run `input/`、`submit/job.sh`、`work/` は interface 経由で
  作る。直接編集は再現性と provenance を壊す。

- **高コスト操作は gate を通す**  
  bulk submit、retry、cancel、delete、migration は Agent が対象と理由を提示し、
  人間が確認する。

- **人間が CLI を覚えなくてよい導線を保つ**  
  CLI reference は operator/debug 用に残すが、README と get-started は
  Agent-first に保つ。

## Bootstrap Interface

新規 project:

```bash
uvx --from runops runo init
uvx --from runops runo doctor
```

既存 project:

```bash
uvx --from runops runo setup https://github.com/user/my-project.git
cd my-project
uvx --from runops runo doctor
```

ここまで終わったら、CLI を順番に叩くのではなく Agent に研究内容を渡します。

## Command Surface

日常的な CLI コマンド名は `runo` です。既存スクリプトとの互換性のため、
`runops` コマンドも同じ CLI を指す stable alias として残しています。

全コマンドは、引数省略時にカレントディレクトリをデフォルトターゲットとします。

### Project

| コマンド | 説明 |
|---------|------|
| `runo init [SIMS...] [-y]` | プロジェクトの初期化。対話型がデフォルト |
| `runo setup [URL]` | 既存 runops project の clone + セットアップ |
| `runo doctor [PATH]` | 環境検査。設定、sbatch、run_id 一意性、環境検出を確認 |
| `runo context [DIR]` | Agent 向け project context の要約を表示 |
| `runo context --json` | Agent 向け context を JSON で取得 |
| `runo lint [PATH] [--scope ...] [--json]` | project state の health check |
| `runo migrate list/show/apply` | project-state migration を確認・適用 |
| `runo config show` | 設定表示 |
| `runo config add-simulator` | シミュレータ追加 |
| `runo config add-launcher` | ランチャー追加 |
| `runo update` | シミュレータパッケージのアップグレード |
| `runo update-harness --plan/apply-chain` | project 側 Agent harness / managed scaffold を versioned chain で再生成 |
| `runo update-refs [SIMS...]` | refs/ リポジトリ更新 + knowledge index 再生成 |
| `runo mcp serve --transport stdio` | local MCP provider を stdio で起動 |
| `runo mcp serve --transport streamable-http` | local MCP provider を HTTP で起動 |
| `runo mcp check` | MCP tool registry / safety contract の軽量検査 |

MCP provider は Agent / host 向けの edge interface です。read / inspect / plan tool
だけを初期公開し、submit / cancel / delete などの external / destructive tool は
デフォルトで公開しません。詳細は [../mcp.md](../mcp.md) を参照してください。

### Run Creation / Submission

| コマンド | 説明 |
|---------|------|
| `runo case new CASE [--minimal] [--survey]` | 新規 case のスキャフォールド生成 |
| `runo runs create CASE` | case から単一 run を生成 |
| `runo runs sweep [DIR] [--dry-run]` | `survey.toml` からパラメータ直積で run を一括生成 |
| `runo runs submit [RUN]` | run を sbatch で投入 (`-qn`, `--qos`, `--afterok` 対応) |
| `runo runs submit --all [DIR] [--yes]` | created な run を確認付きで一括投入 (`--yes` で確認省略) |
| `runo runs clone [RUN] [--dest DIR] [--set key=value]` | run 複製・派生。`--set` 使用時は source case から input/job を再生成 |
| `runo runs extend` | スナップショットから継続 run を生成 |
| `runo runs retry [RUN] [--plan]` | failed / cancelled run の retry 準備 |
| `runo runs regenerate [RUN] [--dry-run]` | run の `input/` を記録済み case + params から再生成 |

`runo runs submit --all` は HPC 資源・queue・quota に影響する高コスト操作です。
Agent との会話上で対象 run、queue、資源量を確認済みの場合だけ `--yes` を使います。

### Monitoring

| コマンド | 説明 |
|---------|------|
| `runo runs status [RUNS...]` | run の状態確認。run_id / run dir / survey dir を複数渡せる |
| `runo runs sync [RUNS...]` | Slurm 状態を `manifest.toml` に反映 |
| `runo runs log [RUN]` | 最新 job の stdout/stderr 表示 + 進捗% |
| `runo runs jobs [PATH] [--watch SECS]` | プロジェクト内の実行中ジョブ一覧 |
| `runo runs dashboard [TARGETS...] [--watch SECS] [--all]` | 複数 run の進捗を 1 つの表で表示 |
| `runo runs history [PATH]` | 投入履歴表示 |
| `runo runs list [PATHS...]` | run の一覧表示。複数 PATH、状態、タグでフィルタ可能 |

`runo runs status` は表示用で、正本更新は `runo runs sync` が行います。
bulk sync では created run と terminal state の run は silent skip されます。

### Analysis / Lifecycle

| コマンド | 説明 |
|---------|------|
| `runo analyze summarize [RUN]` | Adapter による run 解析 summary 生成 |
| `runo analyze collect [DIR]` | survey 内の run から集計データ生成 |
| `runo analyze plot [DIR]` | survey 集計結果の可視化 |
| `runo analyze export [RUN\|SURVEY] --paper PAPER` | paper-facing export bundle を作成 |
| `runo analyze new-comparison NAME [--source PATH]` | cross-run 比較 workspace を作成 |
| `runo runs cancel [RUN]` | submitted/running な run を `scancel` + `sync` で停止 |
| `runo runs archive [RUNS...] [--keep-in-place] [--move-to DIR]` | completed run を archived にし、既定で `runs/_archive/` へ移動 |
| `runo runs purge-work [RUN]` | archived run の `work/` 内不要ファイル削除 |
| `runo runs delete [RUN]` | created / cancelled / failed run を削除 |

completed / archived run には `delete` を使わず、`archive` → `purge-work` の経路を使います。

### Notes / Knowledge

| コマンド | 説明 |
|---------|------|
| `runo notes append TITLE [BODY]` | 今日の `notes/YYYY-MM-DD.md` に timestamped entry を追記 |
| `runo notes list [-n N]` | 最近の lab notebook 日付一覧 |
| `runo notes show [DATE\|today\|latest]` | 指定日の lab notebook を表示 |
| `runo notes archive [--older-than 7d]` | 古い日次 notebook を `notes/history/YYYY/` に移動 |
| `runo knowledge save NAME` | 知見を `.runops/insights/` に保存 |
| `runo knowledge list` | 知見一覧表示 |
| `runo knowledge show NAME` | 知見の詳細表示 |
| `runo knowledge add-fact CLAIM` | 構造化された知識を `facts.toml` に追加 |
| `runo knowledge facts` | local facts と imported candidate facts の一覧表示 |
| `runo knowledge source list` | 外部知識ソース一覧表示 |
| `runo knowledge source attach TYPE NAME URL` | 外部知識ソースを接続 |
| `runo knowledge source sync [NAME]` | 知識ソース同期 |
| `runo knowledge source render` | 有効な profile から `imports.md` を生成 |

## Run State

```
created -> submitted -> running -> completed
created/submitted/running -> failed
submitted/running -> cancelled
completed -> archived -> purged
```

Slurm の観測結果によっては `submitted -> completed` のように途中状態を飛び越す
遷移が発生します。
