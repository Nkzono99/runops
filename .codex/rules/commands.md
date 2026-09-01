# 主要コマンド一覧

全コマンドは引数省略時にカレントディレクトリをデフォルトとする。
この一覧では推奨 CLI 名の `runo` を使う。`runops` も互換 alias として同じコマンドを実行できる。

## プロジェクト管理

| コマンド | 説明 |
|---------|------|
| `runo init [SIMS...] [--yes] [--with-refs]` | Project 初期化 (対話型がデフォルト、refs mirror は opt-in) |
| `runo setup [URL] [--with-refs]` | 既存プロジェクトを clone + 環境セットアップ (refs mirror は opt-in) |
| `runo doctor` | 環境検査 |
| `runo context --json` | Agent 向け project context を JSON で取得。Run namespace を完全走査できない場合は `namespace_available=false` と nullable count、diagnostic を返す |
| `runo triage [PATH] [--json]` | 新しい実験を作る前に active Experiment、Run、review backlog、古い TestAttempt、Result、壊れた state、24時間以上残る staging を read-only 点検。Run namespace を完全走査できない場合は件数を正常扱いせず diagnostic を返す |
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
| `runo runs create CASE [--dest DIR] [--label LABEL] [--experiment E...] [--purpose PURPOSE] [--created-by ACTOR]` | case から単一 Run を生成。新規 project では active Experiment が必須 |
| `runo runs sweep [DIR] [--offset N] [--limit N] [--json]` | survey を lazy 展開し、候補数・point ref・plan hash・概算 cost を表示する read-only plan。`--dry-run` は同じ挙動の互換 alias |
| `runo runs sweep [DIR] --apply (--point REF)... --expect-plan HASH` | preview で選んだ point だけを materialize。`REF` は `p0001` または point hash |
| `runo runs sweep [DIR] --apply --all --expect-plan HASH` | 全候補を明示選択して materialize。Survey / Experiment の hard budget を越える場合は拒否 |
| `runo runs submit [RUN]` | run を sbatch で投入 (`-qn`, `--qos`, `--afterok` 対応) |
| `runo runs submit --all [DIR] [--yes]` | ready plan を一括投入。survey は structured experiment gate 必須 (`--yes` は確認のみ省略) |
| `runo runs clone [RUN] [--dest DIR] [--set key=value] [--experiment E...] [--purpose PURPOSE]` | completed 相当の source から immutable Run を複製・派生。`--set` 使用時は source case から input/job を再生成 |
| `runo runs extend [RUN] [--dest DIR] [--nstep N] [--experiment E...] [--purpose PURPOSE] [--run]` | completed 相当の snapshot から継続 Run を生成。`--run` は新規作成時だけ submit |
| `runo runs retry [RUN] [--plan]` | failed/cancelled run の retry 準備 (`--plan` は状態を戻さず記録のみ) |
| `runo runs review [RUN] --reason WHY [--reviewed-by ACTOR]` | terminal Run を確認済みにする。Result の evidence 選択とは独立 |
| `runo runs regenerate [RUN] --dry-run` | 記録済み case + params と frozen `input/` の差分を read-only 表示。Run identity を守るため in-place 更新は拒否し、変更は `runs clone --set` で新しい Run にする |
| `runo runs relabel [RUNS...] [--dry-run] [--yes]` | inactive な旧 run directory へ manifest の display name 由来 label を付与 |

`runs sweep` は引数なしでも directory を作らず、Run ID も消費しない。materialize には
`--apply`、`--point` または `--all` のどちらか一方、直前の preview が表示した
`--expect-plan` の 3 条件が必要である。`survey.toml`、base case、case 配下の file、
`simulators.toml`、`launchers.toml`、`site.toml` が変わると plan hash が変わり、古い
plan は拒否される。

## Experiment admission

| コマンド | 説明 |
|---------|------|
| `runo experiments create TITLE --question QUESTION --intent INTENT --exit CRITERION [--exit ...] --expires-at ISO (--baseline-run R... | --baseline-reason WHY) [BUDGET OPTIONS] [--review-due ISO] [--created-by ACTOR] [--path PATH]` | 一つの問い、baseline、有限 budget、有効期限、exit criteria を持つ active Experiment を作る |
| `runo experiments list [PATH] [--json]` | Experiment の lifecycle / decision / title を一覧表示 |
| `runo experiments inspect EXPERIMENT [--path PATH] [--json]` | Experiment の問い、baseline、budget、exit criteria を表示 |
| `runo experiments review EXPERIMENT --decision DECISION --reason WHY [--outcome OUTCOME] [--successor E...] [--path PATH]` | active Experiment の判断を記録。`main` / `followup` Survey は `decision=expand` が必要 |
| `runo experiments close EXPERIMENT --decision DECISION --outcome OUTCOME --reason WHY [--successor E...] [--path PATH]` | Experiment を閉じる。Run の移動・削除は行わない |

`INTENT` は `explore|confirm|validate|reproduce`。主要 budget option は
`--max-planned-points`, `--max-materialized-runs`, `--max-active-runs`,
`--max-core-hours`, `--max-unreviewed-runs`。baseline Run と baseline 不要理由は
同時指定できず、どちらか一方が必須である。`--expires-at` は作成時より未来の UTC offset
付き ISO-8601 timestamp が必須で、到達後は新しい formal Run を作れない。`review` の decision は
`expand|revise|stop|accept`、outcome は
`unknown|supported|refuted|inconclusive|invalid`。`close` は
`revise|stop|accept` と `unknown` 以外の outcome を要求する。

## Smoke / debug TestAttempt

| コマンド | 説明 |
|---------|------|
| `runo test smoke CASE [--path PATH] [--profile NAME] [IDENTITY OPTIONS] [--cache-ttl-hours H] [--rerun]` | `.runops/test-runs/T.../` に smoke TestAttempt を prepare。Run ID を消費せず submit もしない |
| `runo test debug CASE [--path PATH] [--profile NAME] [IDENTITY OPTIONS] [--cache-ttl-hours H] [--rerun]` | debug TestAttempt を同じ分離 namespace に prepare |
| `runo test list [PATH] [--json]` | TestAttempt receipt だけを一覧表示 |
| `runo test record T... --result passed\|failed\|skipped [--observation TEXT] [--path PATH]` | TestAttempt に terminal result を記録 |
| `runo test clean --older-than-days N [--path PATH]` | 指定日数以上の terminal TestAttempt だけを削除。古い active attempt、input/receipt drift、cleanup tombstone の差し替えがあれば全体を拒否 |

cache identity option は `--source-commit`, `--executable-hash`, `--adapter`,
`--adapter-version`。cache reuse には source commit、executable hash、adapter version が
すべて必要で、TTL 内の同一 `passed` receipt に hit した場合は CLI に `SKIPPED` と表示して
既存 TestAttempt を返す。既存 receipt は `passed` のままで、新しい T ID・directory・receipt を
作らない。record/cache reuse は保存済み input を再ハッシュし、receipt の `input_hash` と
異なる attempt を更新・再利用しない。`--rerun` は reuse を無効にする。

## モニタリング

| コマンド | 説明 |
|---------|------|
| `runo runs status [RUNS...]` | run 状態確認 (複数指定可) |
| `runo runs sync [RUNS...]` | Slurm 状態を manifest に反映。terminal transition では bounded readiness と次 command も返す |
| `runo runs log [RUN]` | 最新 job の stdout/stderr 表示 + 進捗% |
| `runo runs jobs [PATH] [--watch SECS]` | 実行中ジョブ一覧 |
| `runo runs dashboard [TARGETS...] [--watch SECS] [--all]` | 複数 run の進捗表。`--all` では cached analysis / next action も表示 |
| `runo runs history [PATH]` | 投入履歴表示 |
| `runo runs list [PATHS...] [--status S] [--tag T] [--experiment E] [--purpose P] [--review-status R] [--storage-tier T] [--storage-form F] [--include-archived]` | run 一覧と cached analysis / next action を表示。既定では archived / purged と archived bundle 配下を除外 |

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
| `runo research append TITLE BODY [--kind KIND] [--subject ID]` | bounded journal に追記し必要なら自動 rotation。subject で Experiment / Survey / Run に紐付け可能 |
| `runo research rotate [PATH] [--force]` | journal を原文のまま numbered archive へ移す |
| `runo research new-result NAME [--path PATH]` | README 1 枚、manifest.toml、artifacts/ を持つ canonical Result を作成 |
| `runo research check-result RESULT [--path PATH] [--json]` | Result layout、evidence、seal receipt を変更せず検査 |
| `runo research seal RESULT --claim CLAIM --outcome OUTCOME --selection-reason WHY (--evidence-run R...\|--evidence-path PATH)... [--path PROJECT]` | 理由付き Result-local include edge と content hash を記録して immutable seal を作る |
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
| `runo runs archive [RUNS...] [--all] [--yes/-y] [--keep-in-place] [--move-to DIR] [--bundle] [--adopt-archived]` | 通常は completed run を archive。managed project の `--move-to` は同一 filesystem の `runs/_archive/**` 内だけを許可する。`--bundle` は親ディレクトリ全体を移動し、配下 run state を保持。`--adopt-archived` は同じ親から個別 archive 済みの run を検証して bundle へ採用 |
| `runo runs restore RUN [--bundle]` | 通常は archived run を復元。`--bundle` は親ディレクトリ全体を archive 前の場所へ復元 |
| `runo runs purge-work [RUN] [--yes] [--discard-incomplete --reason WHY]` | work/ 内の不要ファイル削除。既知の non-ready output を破棄する場合は理由必須。sealed Result が対象 path evidence を参照していれば拒否 |
| `runo runs cancel [RUNS...] [--yes/-y]` | scancel + sync (submitted/running を停止) |
| `runo runs delete [RUN] [--yes]` | run ディレクトリ削除 (created/cancelled/failed のみ) |

archive / restore / purge は lifecycle state だけでなく、直交する storage metadata も更新する。
individual archive の directory / `--all` discovery は managed project の canonical `runs/`
active view に限定し、`research/results` の manifest と cold bundle child を対象にしない。
生成時は `tier=hot, form=full`、archive は `tier=cold`、restore は `tier=hot`、
purge-work は `tier=cold, form=compacted` となる。`archived` と `cold`、`purged` と
`compacted` は同義ではなく、state と storage は別軸として読む。
archive / restore / purge は Run lock を共有し、bundle 操作は child Run lock を path 順に
取得してから対象と state を再検査する。
purge-work は対象を同一 filesystem の tombstone へ全件退避してから metadata を確定し、
途中失敗時は全件 rollback する。確定後の tombstone 削除だけが失敗した場合は
`cleanup_pending` を返し、purged state を巻き戻さない。個別 archive / restore、purge、
通常 bundle archive / restore は source parent の `.runops-bundle-{archive,restore}-*.receipt.toml`
v1 に root/scaffold identity、child directory/tree identity、manifest exact pre/postimage と marker
image を move 前に固定する。中断後は完全一致する receipt 所有 phase だけを forward-complete し、
drift 時は rollback、上書き、move、cleanup を行わない。bundle adoption も durable receipt を持ち、中断後に同じ command を再実行すると receipt、
digest、現在の topology を再検査して rollback または forward-complete する。
個別 archive / restore は manifest/state の exact preimage または deterministic postimage だけを
受理し、同じ Run ID/state でも他 field が変化していれば rollback や receipt cleanup も行わない。
purge receipt は commit 前後の canonical manifest digest、target tree digest、tombstone / target
root の device/inode も固定する。commit 前は完全な tree digest、commit 後の cleanup retry は
root identity を検証し、部分的な `rmtree` 失敗を再開しつつ同名 directory の差し替えを拒否する。
CLI は receipt のない `purged` Run を拒否し、検証済み pending receipt がある同一 path / Run ID
retry だけを forward recovery へ通す。sealed Result の reverse scan は seal content hash と
README/evidence receipt を検証し、改竄時は fail closed とする。
個別 archive / restore の Run ID 再実行と archive の directory / `--all` 再実行は、
通常 discovery より先に receipt の Run ID と元 source scope を検証して移動済み Run を再列挙する。
pending transaction は `runo triage` が表示し、自動削除しない。
