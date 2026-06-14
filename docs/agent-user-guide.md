# runops Agent ユーザーガイド

runops プロジェクトにおける Agent の作業ガイド。
project 側では `.runops/knowledge/runops/agent-user-guide.md` と
`.runops/knowledge/enabled/imports.md` に package 同梱の guide が生成される。

## runops の基本原則

- **run ディレクトリが主単位**: すべての操作は run_id または run ディレクトリを基点
- **manifest.toml が正本**: run の状態・由来・provenance はすべて manifest.toml に記録
- **cwd ベース**: 全コマンドはカレントディレクトリをデフォルトターゲット
- **case は `runo case new` で生成**: case.toml を手書きしない
- **run は `runo runs create` / `runo runs sweep` で生成**: run ディレクトリを手で作らない

## コマンドクイックリファレンス

| 操作 | コマンド |
|------|---------|
| version 確認 | `runo --version` |
| プロジェクト状況把握 | `runo context --json` (`research_agenda` / latest note を含む) |
| 推奨 plugin metadata 確認 | `runo plugins --check` / `runo plugins --json` |
| project health check | `runo lint --scope structure,analysis,knowledge,plugins` |
| case テンプレート生成 | `runo case new <name>` |
| 最小 case テンプレート生成 | `runo case new <name> --minimal` |
| survey 付き case 生成 | `runo case new <name> --survey` |
| run 生成 | `runo runs create <case>` |
| survey 全 run 生成 | `runo runs sweep <survey>` |
| sweep 内容を確認だけ | `runo runs sweep <survey> --dry-run` |
| job 投入 | `runo runs submit` |
| 全 run 一括投入 | `runo runs submit --all` (`--yes` で確認省略) |
| キュー上書き / QOS / 依存ジョブ | `runo runs submit -qn <queue>` / `--qos <qos>` / `--afterok <job_id>` |
| 状態確認 (単一/複数/survey 一括) | `runo runs status [RUNS...]` |
| Slurm 同期 (単一/複数/survey 一括) | `runo runs sync [RUNS...]` (bulk: created + terminal state は silent skip) |
| ログ確認 | `runo runs log` |
| エラーログ | `runo runs log -e` |
| 実行中ジョブ一覧 / 自動更新 | `runo runs jobs` / `runo runs jobs -w 30` |
| 複数 run の進捗ダッシュボード | `runo runs dashboard runs/<survey>` (`-w 30`, `--all` 対応) |
| run 一覧 (複数 PATH 可) | `runo runs list [PATHS...]` |
| run 停止 (scancel + sync) | `runo runs cancel` |
| run のハード削除 (created/failed/cancelled) | `runo runs delete` |
| 解析 | `runo analyze summarize` |
| 集計 | `runo analyze collect` |
| survey plot 作成 | `runo analyze plot <survey> --recipe <recipe>` / `--x <column> --y <column>` |
| cross-run 比較 workspace 作成 | `runo analyze new-comparison <name> --source <run-or-survey>` |
| 論文向け export | `runo analyze export <run-or-survey> --paper <paper-id>` |
| lab notebook に追記 | `runo notes append "<title>" "<body>"` |
| lab notebook 日付一覧 (active/history) | `runo notes list` |
| lab notebook 内容表示 (active/history) | `runo notes show [DATE\|today\|latest]` |
| 古い日次 notebook の整理 | `runo notes archive --older-than 7d` |
| 知見保存 (curated) | `runo knowledge save` |
| 知見一覧 | `runo knowledge list` |
| 知見表示 | `runo knowledge show <name>` |
| 構造化 fact 一覧 | `runo knowledge facts` |
| fact 追加 | `runo knowledge add-fact` |
| 外部知識ソース一覧 | `runo knowledge source list` |
| 外部知識ソース同期 | `runo knowledge source sync` |

## TOML ファイル体系

- `runops.toml` — プロジェクト定義
- `simulators.toml` — シミュレータ設定
- `launchers.toml` — ランチャー設定
- `campaign.toml` — 研究意図・計画
- `cases/**/case.toml` — ケース定義
- `runs/**/survey.toml` — パラメータサーベイ定義
- `runs/**/Rxxxx/manifest.toml` — run メタデータ (自動生成、手動編集禁止)

## notes / materials / research / generated context

実験で残す情報は、見える作業場 (`notes/`, `materials/`, `research/`) を中心に管理する。
Agent 自身の memory には保存しない。

| 種類 | 性質 | 書き先 | コマンド |
|---|---|---|---|
| 再開可能な時系列の lab notebook (準備の意思決定, 観察, 仮説, TODO) | append-only, chronological | `notes/YYYY-MM-DD.md`, `notes/history/YYYY/YYYY-MM-DD.md` | `runo notes append`, `runo notes archive` |
| 長文 refined レポート | refined, 改稿可 | `notes/reports/<topic>.md` | (直接編集) |
| 現在の高レベルな研究判断 | mutable decision ledger | `research/agenda.md` | `/research-agenda` / `$research-agenda` |
| 論文・manual・図・snippet | visible source material | `materials/` | (直接編集) |
| 整理済の名前付き知見 | advanced, durable, 上書き可 | `.runops/insights/<name>.md` | `runo knowledge save` |
| 機械可読 atomic claim | advanced, atomic | `.runops/facts.toml` | `runo knowledge add-fact` |

- 「結果をまとめて」「知見を記録して」等の整理済情報 → まず `notes/reports/` に
- 「今の見立て」「active question」「paused/killed」「次に何をなぜやるか」 → `research/agenda.md` に
- `runo context --json` の `research_agenda` は agenda の存在、現在判断の preview、
  next action 数を返す。詳しい判断は `research/agenda.md` を直接読む
- 「今やってる作業のメモ」「途中経過」「議論の流れ」「準備フェーズの意思決定」 → `runo notes append` で lab notebook に
- 参照 PDF / manual / snippet → `materials/` に
- 機械的に再利用したい atomic な知見だけ `.runops/insights/` / `facts.toml` に昇格

`/note` skill は **準備フェーズから使う**。campaign 設計, case 設計,
survey 設計, run 生成, 投入の各タイミングで意思決定の理由・トレードオフ・
却下した代替案を `notes/YYYY-MM-DD.md` に残しておくと、後の `/learn`
(curated 化) の素材として再利用できる。短くてよいが、`Context:` と
`Evidence:` を置き、model 名だけ・figure path だけで前提を推測させない。
図を生成したら原則 Markdown image として埋め込み、`Observation:` と
`Interpretation:` を分ける。

## runops 本体の local patch

current project で runops 本体の修正が今すぐ必要な場合は、`patch-runops`
skill で project 外の runops source checkout を使う。local patch の正本は
その checkout 内の Git branch / commit とし、設計が必要な upstream 候補は
`feedback-runops` で HarnessOps に記録し、サニタイズ済み issue 下書きにする。詳細は
[Upstream Integration Layer](layers/upstream.md) を参照。

runops 自体を更新するときは `update-runops` skill を使う。Harness scaffold は
`uvx --from runops runo update-harness --plan` で chain を確認し、
`uvx --from runops runo update-harness --apply-chain` で exact version を順に踏んで適用する。
更新後に project 側の file format、manifest、analysis artifact などの移行が必要なら、
release note / migration guide を読み、定型 migration は
`runo migrate apply M0-0001 --dry-run` → `runo migrate apply M0-0001` で適用する。
CLI 未対応または判断が必要なものは `migrate-runops` skill で扱い、適用 / skip / defer を
`notes/YYYY-MM-DD.md` に記録する。
更新後や大きな handoff 前は `runo lint` で project state と推奨 plugin metadata の読みやすさを確認する。

Python package の構造整理、module 分割、循環 import 解消、packaging 整理などは
`python-package-refactor` skill を使う。`scripts/` と `references/` 付きで
project harness に展開され、API surface snapshot、import smoke、quality gate
plan を取りながら小さい refactor batch に分けて進める。

```bash
# 準備フェーズで意思決定を残す
runo notes append "Series A 設計" - <<'EOF'
独立軸: vti = 1..19 eV (10 点). 4σ CFL で 19 eV が上限.
固定: vflow=400 km/s. 没案: vflow も振る → 資源不足.
EOF

# 後で日付一覧 → 内容を確認
runo notes list
runo notes show 2026-04-08
runo notes show today    # 今日
runo notes show latest   # 一番新しい日
runo notes archive --older-than 7d

# /learn 時に notes を素材として読み込む
runo notes show latest | head -100
```

## ハーネスのガード

`runo init` は `.claude/settings.json` と `.claude/hooks/` も生成し、
Claude Code 向けに project 内の保護ルールを設定する。

- 直接編集してよいのは主に `campaign.toml`、`cases/**`、`runs/**/survey.toml`、通常の docs
- 直接編集してはいけないのは `runs/**/manifest.toml`、`input/**`、`submit/**`、`work/**`、`SITE.md`
- `.runops/insights/` と `.runops/facts.toml` は `runo knowledge save` / `add-fact` を使う
- `notes/YYYY-MM-DD.md` は `runo notes append` 経由で append-only に追記する (既存 entry を書き換えない)
- `runo notes archive` は古い日次 notebook だけを `notes/history/YYYY/` に移し、`notes/reports/` には触れない
- `runo runs submit` は破壊的操作ではないが、HPC 資源・queue・quota に影響する。
  Agent には許可するが、実行前に dry-run 結果、対象 run、queue、資源量を提示する。
  `--all` は CLI 側でも確認し、会話上で明示確認済みの場合だけ `--yes` を使う
- `runo runs cancel` は harness 上 allow 扱いだが、実行前に対象 run と理由は報告する

## 状態遷移

```
created → submitted → running → completed
created/submitted/running → failed
submitted/running → cancelled
completed → archived → purged
```

`runo runs cancel` は `submitted` / `running` の run に対して `scancel` と
`runo runs sync` をまとめて実行し、`cancelled` 状態に遷移させる安全な経路。
`runo runs archive` は `completed` run を `archived` にし、既定で
`runs/_archive/` に移動する。パスを保ちたい場合は `--keep-in-place` を使う。
`runo runs delete` はライフサイクル外の操作で、`created` / `cancelled` / `failed`
の run ディレクトリを直接削除する (`completed` / `archived` の run には使えないので
`archive` → `purge-work` を使うこと)。

## 知識の活用

作業開始時に知識層を読んで、既知の制約や過去の知見を把握する。

| 情報 | 場所 | 読むタイミング |
|------|------|---------------|
| 研究意図・仮説 | `campaign.toml` | 作業開始時 |
| 作業ログ・レポート | `notes/` | 作業開始時・解析後 |
| source material | `materials/` | 設計・読解・解析時 |
| 構造化 fact (制約・依存性) | `.runops/facts.toml` | 必要な場合のパラメータ設計・検証時 |
| 実験知見 (Markdown) | `.runops/insights/` | 必要な場合の作業開始時・解析後 |
| シミュレータドキュメント | simulator/environment plugin, `runo plugins --json` の `delegated_capabilities`, `.runops/knowledge/`, 任意の `refs/` fallback mirror | パラメータ設計時 |
| 実行環境 | `.runops/environment.toml` | job 設定・launcher 選択時 |
| 外部共有知識 | `refs/knowledge/` | 必要に応じて |

### 読む

```bash
runo knowledge list                     # 知見の一覧
runo knowledge list -s emses -t constraint  # フィルタ付き
runo knowledge show <name>              # 知見の全文表示
runo knowledge facts                    # 構造化 fact の一覧
runo knowledge facts --scope emses -c high  # フィルタ付き
```

### 書く

知見の保存は `/learn` スキル経由で行う。Agent 自身の memory には保存しない。

```bash
runo knowledge save <name> -t <type> -s <simulator> -m "<内容>"
runo knowledge add-fact "<claim>" -t <type> -s <simulator> -c <confidence>
```

レイヤーごとの正本は [layers/README.md](layers/README.md) から参照する。

## Simulator Adapter のガイド

各シミュレータ固有のガイドは、まず `runo plugins --json` の
`delegated_capabilities` で委譲先 plugin を確認し、simulator/environment plugin と
`.runops/knowledge/enabled/imports.md` を参照する。`runo init --with-refs` などで
`refs/<repo>/docs/agent-*.md` が存在する場合は、ローカル mirror の fallback として
参照する。
