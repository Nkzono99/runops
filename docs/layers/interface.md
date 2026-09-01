# Interface Layer

Interface Layer は、Agent、harness、人間 operator が runops の project state に触る
境界です。

ここでいう interface は「人間が日常的に CLI を覚えて叩く画面」ではありません。
通常の研究運用では、人間は Agent に研究意図と確認を渡し、Agent が runops の
interface を使って Execution Kernel や Experiment Layer を更新します。

現在の bounded context は **Execution Kernel**、**Research Workspace**、
**Agent Gateway**、**Operator/Developer utilities** の 4 つです。レイヤの並びは

```text
core -> application -> interfaces/infrastructure
```

であり、Interface Layer は application use case を呼ぶ外側です。CLI / MCP が domain
precondition や command vector を再実装してはいけません。

## 位置づけ

runops の CLI は、以下のためにあります。

- Agent が project state を構造化された経路で読み書きする
- harness が高コスト操作や破壊的操作に gate をかける
- 人間 operator が bootstrap、debug、CI、緊急時の確認を行う
- CLI の外側にある会話 UI、skills、rules から core action を呼ぶ

CLI は重要ですが、研究者が日常的に CLI の全体を操作する前提にはしません。
人間向けの主導線は [../get-started-with-agent.md](../get-started-with-agent.md) です。

## 他 Layer との境界

以下は project state の operational Layer です。product context との対応は、
Experiment/Execution → **Execution Kernel**、Analysis/Research/Knowledge →
**Research Workspace**、Interface/Harness → **Agent Gateway**、Upstream/operator →
**Operator/Developer utilities** です。

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

Agent-facing action は `src/runops/application/actions/specs.py` の `ActionSpec` を
machine-readable な契約として持ちます。各 action spec には対応する CLI command
path と MCP tool 名を記録し、テストで Typer の登録済み command と MCP registry
に存在することを確認します。これにより CLI / action facade / MCP metadata の
drift を早期に検出します。

## 原則

- **正本は Interface Layer ではなく各 Layer に置く**  
  CLI output や会話ログを正本にしない。run 状態は `manifest.toml`、
  研究判断は `research/CURRENT.md`、実験設計は case / survey に戻す。

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
uvx --from runops runo plugins --check
```

既存 project:

```bash
uvx --from runops runo setup https://github.com/user/my-project.git
cd my-project
uvx --from runops runo doctor
uvx --from runops runo plugins --check
```

ここまで終わったら、CLI を順番に叩くのではなく Agent に研究内容を渡します。

## Command Surface

日常的な CLI コマンド名は `runo` です。既存スクリプトとの互換性のため、
`runops` コマンドも同じ CLI を指す stable alias として残しています。

全コマンドは、引数省略時にカレントディレクトリをデフォルトターゲットとします。
以下は日常運用で使う主要導線の抜粋です。全 command path、required positional
argument、主要 safety option は [`.codex/rules/commands.md`](../../.codex/rules/commands.md)、
parser の完全な option は各 command の `--help` を正本とします。

### Project

| コマンド | 説明 |
|---------|------|
| `runo init [SIMS...] [-y] [--with-refs]` | プロジェクトの初期化。対話型がデフォルト、refs mirror は opt-in |
| `runo setup [URL] [--with-refs]` | 既存 runops project の clone + セットアップ。refs mirror は opt-in |
| `runo doctor [PATH]` | 環境検査。設定、sbatch、run_id 一意性、環境検出、推奨 plugin metadata を確認 |
| `runo context [DIR]` | Agent 向け project context の要約を表示 |
| `runo context --json` | Agent 向け context を JSON で取得 |
| `runo plugins [DIR] [--json] [--check] [--strict]` | project / simulator / site 由来の推奨 Codex plugin inventory を表示・検査 |
| `runo lint [PATH] [--scope ...] [--json]` | project state と推奨 plugin metadata の health check |
| `runo migrate list/show/apply` | project-state migration を確認・適用 |
| `runo config show` | 設定表示 |
| `runo config add-simulator` | シミュレータ追加 |
| `runo config add-launcher` | ランチャー追加 |
| `runo update [--yes]` | シミュレータパッケージのアップグレード。`--yes` が確認省略の正規 option |
| `runo update-harness [--plan] [--apply-chain]` | project 側 Agent harness / managed scaffold を versioned chain で再生成 |
| `runo update-refs [SIMS...]` | 任意 refs mirror 更新 + knowledge index 再生成 |
| `runo mcp serve --transport stdio` | local MCP provider を stdio で起動 |
| `runo mcp serve --transport streamable-http` | local MCP provider を HTTP で起動 |
| `runo mcp check` | MCP tool registry / safety contract の軽量検査 |
| `runo mcp tools --json` | MCP tool metadata を JSON で表示 |
| `runo mcp resources --json` | MCP resources metadata を JSON で表示 (現状は空) |
| `runo mcp prompts --json` | MCP prompts metadata を JSON で表示 (現状は空) |

`runo update --force` は既存 script 用の hidden compatibility alias で、`--yes` と
同じ semantics です。新しい手順や文書では `--yes` を使います。

MCP provider は Agent / host 向けの edge interface です。read / inspect / plan tool
だけを初期公開し、submit / cancel / delete などの external / destructive tool は
デフォルトで公開しません。詳細は [../mcp.md](../mcp.md) を参照してください。

### Run Creation / Submission

| コマンド | 説明 |
|---------|------|
| `runo experiments create/list/inspect/review/close` | bounded question の admission、WIP、decision を管理 |
| `runo case new CASE [--minimal] [--survey]` | 新規 case のスキャフォールド生成 |
| `runo runs create CASE [--label LABEL] [--experiment E...]` | active Experiment 内で単一 Run を生成 |
| `runo runs sweep [DIR] [--offset N] [--limit N]` | lazy candidate と plan hash を read-only preview。`--dry-run` は同じ挙動 |
| `runo runs sweep DIR --apply --point REF... --expect-plan HASH` | selected point だけを materialize |
| `runo runs sweep DIR --apply --all --expect-plan HASH` | 全点を明示選択。hard budget 超過は拒否 |
| `runo runs submit [RUN]` | run を sbatch で投入 (`-qn`, `--qos`, `--afterok` 対応) |
| `runo runs submit --all [DIR] [--yes]` | ready plan の run を確認付きで一括投入 (`--yes` で確認省略) |
| `runo runs clone [RUN] [--dest DIR] [--set key=value] [--experiment E...] [--purpose PURPOSE]` | completed 相当の source から immutable Run を複製・派生。`--set` 使用時は source case から input/job を再生成 |
| `runo runs extend [RUN] [--dest DIR] [--nstep N] [--experiment E...] [--purpose PURPOSE] [--run]` | completed 相当の snapshot から継続 Run を生成。`--run` は新規作成時だけ submit |
| `runo runs retry [RUN] [--plan]` | failed / cancelled run の retry 準備 |
| `runo runs regenerate [RUN] --dry-run` | frozen input と現在の case の差分を read-only 表示。変更は clone で新しい Run にする |
| `runo test smoke|debug CASE` | smoke/debug を T ID namespace に prepare。Run / submit ではない |

`runo runs submit --all` は HPC 資源・queue・quota に影響する高コスト操作です。
Agent との会話上で対象 run、queue、資源量を確認済みの場合だけ `--yes` を使います。
production / large survey では、`--yes` は研究上の確認を省略しません。対象、概算資源量、
根拠となる pilot Result を人が確認し、owning Experiment を `decision=expand` にしてから
remaining run を full submit します。

candidate preview は directory budget を消費しません。materialize は `--apply`、
`--point|--all`、exact `--expect-plan` の gate を必須とし、`--all` を推測して選びません。

### Monitoring

| コマンド | 説明 |
|---------|------|
| `runo runs status [RUNS...]` | run の状態確認。run_id / run dir / survey dir を複数渡せる |
| `runo runs sync [RUNS...]` | Slurm 状態を反映し、terminal run では bounded readiness と次 command も返す |
| `runo runs log [RUN]` | 最新 job の stdout/stderr 表示 + 進捗% |
| `runo runs jobs [PATH] [--watch SECS]` | プロジェクト内の実行中ジョブ一覧 |
| `runo runs dashboard [TARGETS...] [--watch SECS] [--all]` | 複数 run の進捗を表示。`--all` では cached analysis / next action も表示 |
| `runo runs history [PATH]` | 投入履歴表示 |
| `runo runs list [PATHS...] [--status S] [--experiment E] [--purpose P] [--review-status R] [--storage-tier T] [--storage-form F] [--include-archived]` | run と cached analysis / next action の一覧。既定では archived / purged を除外 |
| `runo runs review [RUN] --reason WHY` | terminal outcome の確認。Result evidence selection とは独立 |
| `runo triage [PATH] [--json]` | active work、review/cleanup backlog、壊れた state、古い staging を read-only 点検 |

`runo runs status` は表示用で、正本更新は `runo runs sync` が行います。
bulk sync では created run と terminal state の run は silent skip されます。
sync が completed transition で返した readiness は current attempt の
`status/readiness.json` に cache されるため、Agent は通常 `sync → status → log` を
定型的に全実行せず、sync result の `recommended_command` へ直接進めます。
`runs list`、`runs dashboard --all`、MCP `runops.run.list` は cache-only の bulk view
です。cache miss は `unknown / deep_validate` として見せますが、一覧取得中に run ごとの
deep evaluation は起動しません。`--status archived|purged`、storage filter、
`--include-archived` は all discovery を選び、それ以外は active traversal を維持します。
`runs jobs --watch` / `runs dashboard --watch` は CLI が一定間隔で問い合わせ直す
polling view です。常駐 Web/API と push 配信を持つ persistent real-time dashboard
service ではありません。

### Analysis / Lifecycle

| コマンド | 説明 |
|---------|------|
| `runo analyze summarize [RUN]` | Adapter による run 解析 summary 生成 |
| `runo analyze collect [DIR]` | survey 内の run から集計データ生成 |
| `runo analyze plot [DIR]` | survey 集計結果の可視化 |
| `runo analyze export [RUN\|SURVEY] --paper PAPER [--accept-incomplete-reason WHY]` | paper-facing export。incomplete acceptance は理由必須 |
| `runo analyze new-comparison NAME [--source PATH]` | cross-run 比較 workspace を作成 |
| `runo analyze new-story NAME [--id ID] [--title TITLE] [--source PATH]` | strict source/schema の story acceptance workspace を作成 |
| `runo analyze audit-story [STORY_DIR]` | source artifact を照合し `audit.json` / `audit.md` を生成 |
| `runo runs cancel [RUN]` | submitted/running な run を `scancel` + `sync` で停止 |
| `runo runs archive [RUNS...] [--keep-in-place] [--move-to DIR] [--bundle] [--adopt-archived]` | 通常は completed run を archived にする。managed project の `--move-to` は同一 filesystem の `runs/_archive/**` 内だけを許可する。`--bundle` は親と全内容を移動し、各 run state を保持。`--adopt-archived` は一致する個別 archive 済み run を検証して採用 |
| `runo runs restore RUN [--bundle]` | 通常は archived run を completed に戻す。`--bundle` は親と全内容を元のパスへ戻す |
| `runo runs purge-work [RUN] [--discard-incomplete --reason WHY]` | archived run の work 削除。既知 non-ready output の破棄は理由必須 |
| `runo runs delete [RUN]` | created / cancelled / failed run を削除 |

completed / archived run には `delete` を使わず、`archive` → `purge-work` の経路を使います。
bundle archive は run state と直交し、submitted / running を含む親は移動しません。
既存 archive destination は原則拒否し、`--adopt-archived` 指定時だけ同じ親・相対 path の
archived / purged run を採用します。所有不明 path や source 側の衝突があれば変更しません。
`runs/_archive/` 自体は Git 管理対象から外さず、active run と同じ `.gitignore` 規則で
`work/`、`status/`、cache / scratch のみを除外します。

### Notes / Knowledge

| コマンド | 説明 |
|---------|------|
| `runo research status/check` | active research の量と layout を検査 |
| `runo research append TITLE BODY` | bounded journal に timestamped entry を追記 |
| `runo research rotate [--force]` | journal を原文のまま numbered archive へ移動 |
| `runo research new-result NAME` | durable result workspace を作成 |
| `runo research check-result RESULT` | Result evidence / seal integrity を read-only 検査 |
| `runo research seal RESULT --claim ... --outcome ... --selection-reason WHY --evidence-* ...` | 理由付き Result-local evidence と immutable receipt を固定 |
| `runo research archive/restore ID` | result を可逆移動 |
| `runo research migrate-legacy` | 旧 workspace を preview 付きで可逆移行 |
| `runo knowledge save NAME` | 知見を `.runops/insights/` に保存 |
| `runo knowledge list` | 知見一覧表示 |
| `runo knowledge show NAME` | 知見の詳細表示 |

T ID と `.runops/test-runs/**` は scientific Result evidence にできません。case / survey
`notes.md` と Run `analysis/notes.md` は legacy narrative slot として lint warning の対象です。
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
             |
             +-> completed  (restore)
```

Slurm の観測結果によっては `submitted -> completed` のように途中状態を飛び越す
遷移が発生します。
