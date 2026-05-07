# runops Agent ユーザーガイド

runops プロジェクトにおける Agent の作業ガイド。
現時点の標準ハーネスは Claude Code で、プロジェクトの `CLAUDE.md` から `@docs/agent-user-guide.md` で参照される。

## runops の基本原則

- **run ディレクトリが主単位**: すべての操作は run_id または run ディレクトリを基点
- **manifest.toml が正本**: run の状態・由来・provenance はすべて manifest.toml に記録
- **cwd ベース**: 全コマンドはカレントディレクトリをデフォルトターゲット
- **case は `runo case new` で生成**: case.toml を手書きしない
- **run は `runo runs create` / `runo runs sweep` で生成**: run ディレクトリを手で作らない

## コマンドクイックリファレンス

| 操作 | コマンド |
|------|---------|
| プロジェクト状況把握 | `runo context --json` |
| case テンプレート生成 | `runo case new <name>` |
| 最小 case テンプレート生成 | `runo case new <name> --minimal` |
| survey 付き case 生成 | `runo case new <name> --survey` |
| run 生成 | `runo runs create <case>` |
| survey 全 run 生成 | `runo runs sweep <survey>` |
| sweep 内容を確認だけ | `runo runs sweep <survey> --dry-run` |
| job 投入 | `runo runs submit` |
| 全 run 一括投入 | `runo runs submit --all` |
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
| 論文向け export | `runo analyze export <run-or-survey> --paper <paper-id>` |
| lab notebook に追記 | `runo notes append "<title>" "<body>"` |
| lab notebook 日付一覧 | `runo notes list` |
| lab notebook 内容表示 | `runo notes show [DATE\|today\|latest]` |
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

## notes / materials / generated context

実験で残す情報は、見える作業場 (`notes/`, `materials/`) を中心に管理する。
Agent 自身の memory には保存しない。

| 種類 | 性質 | 書き先 | コマンド |
|---|---|---|---|
| 再開可能な時系列の lab notebook (準備の意思決定, 観察, 仮説, TODO) | append-only, chronological | `notes/YYYY-MM-DD.md` | `runo notes append` |
| 長文 refined レポート | refined, 改稿可 | `notes/reports/<topic>.md` | (直接編集) |
| 論文・manual・図・snippet | visible source material | `materials/` | (直接編集) |
| 整理済の名前付き知見 | advanced, durable, 上書き可 | `.runops/insights/<name>.md` | `runo knowledge save` |
| 機械可読 atomic claim | advanced, atomic | `.runops/facts.toml` | `runo knowledge add-fact` |

- 「結果をまとめて」「知見を記録して」等の整理済情報 → まず `notes/reports/` に
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
- `runo runs submit` は破壊的操作ではないが、HPC 資源・queue・quota に影響する。
  Agent には許可するが、実行前に dry-run 結果、対象 run、queue、資源量を提示する
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
| シミュレータドキュメント | `.runops/knowledge/`, `refs/` | パラメータ設計時 |
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

詳細な仕様は [knowledge-layer.md](knowledge-layer.md) を参照。

## Simulator Adapter のガイド

各シミュレータは `refs/<repo>/docs/agent-*.md` に固有のガイドを置く。
CLAUDE.md から `@import` で参照されるため、シミュレータ固有のパラメータ設定・
トラブルシューティング・ベストプラクティスはそちらを参照すること。
