# 知識層 (Knowledge Layer)

AI エージェントがシミュレーション実行・解析を自律的に行うための知識管理アーキテクチャ。

## 概要

runops の知識層は 4 つのドメインで構成される:

| ドメイン | 内容 | 管理場所 | 更新契機 |
|----------|------|----------|---------|
| **シミュレータ知識** | パラメータスキーマ、物理的制約、安定性条件、長文 Agent context | simulator/environment plugin, Adapter metadata, `.runops/knowledge/`, 任意の `refs/` mirror | plugin install/update, Adapter 更新, `runo update-refs` (任意 mirror) |
| **外部共有知識** | ラボ共通の解析手法・知識、シミュレータ汎用知識 | `refs/knowledge/` | `runo knowledge source sync` |
| **実行環境知識** | クラスタ構成、パーティション、モジュール | `.runops/environment.toml` | `runo doctor` |
| **研究意図** | 仮説、実験設計、変数定義、観測量 | `campaign.toml` | ユーザーが記述 |
| **人間提供資料** | 論文 PDF、manual、図、snippet、source index | `materials/` | ユーザー / Agent が整理 |

加えて、実験から得られた情報は **見える作業場を中心** に蓄積・共有される:

- **lab notebook**: append-only な時系列ログ — `notes/YYYY-MM-DD.md` (日次ノート), `notes/reports/<topic>.md` (refined long-form)
- **materials**: 人間が持ち込む source material — `materials/papers/`, `materials/manuals/`, `materials/figures/`, `materials/snippets/`
- **research agenda**: 現在の高レベルな研究判断 — `research/agenda.md`
- **advanced structured knowledge**: 機械的に再利用したい知見 — `.runops/insights/<name>.md`, `.runops/facts.toml`

日常運用では `notes/`, `materials/`, `research/` を人間/Agent の共有ワークスペースとする。
`.runops/knowledge/` は `imports.md` などの生成済み Agent context であり、
source of truth ではない。`.runops/insights/` と `.runops/facts.toml` は
互換性を保つ advanced / structured store として残し、機械的に再利用したい
atomic な知見だけを昇格する。

## ディレクトリ構成

```
project/
  runops.toml                # プロジェクト設定 ([knowledge] セクション含む)
  campaign.toml                  # 研究意図
  materials/                     # 人間が持ち込む source material
    README.md
    index.toml                   # optional hand-written/generated index
    papers/
    manuals/
    figures/
    snippets/
  research/                      # 現在の研究判断 (mutable decision ledger)
    README.md
    agenda.md
    proposals/                   # 高コスト・方向転換前の任意 proposal
    reviews/                     # agenda checkpoint の snapshot
  refs/                          # 任意のローカル mirror / 外部知識 mount
    MPIEMSES3D/
      cookbook/                   # simulator cookbook (入力例・設定カタログ)
        COOKBOOK.md
        index.toml
        examples/
        fragments/
      docs/                      # パラメータ詳細、物理的制約
    beach/
    knowledge/                   # 外部知識ソースのマウントポイント
      shared-lab-kb/             # git clone された共有知識リポジトリ
        profiles/
        simulators/
        analysis/
  .runops/
    knowledge/                   # 自動生成 Agent context (gitignore 対象)
      emses.md                   # 任意 refs mirror のドキュメント一覧 + 変更ログ
      beach.md
      enabled/                   # 有効 profile の展開結果
        imports.md               # CLAUDE.md から @import される
      candidates/                # 外部 source 由来の候補 knowledge
        facts/                   # candidate fact transport
    insights/                    # advanced: curated 知見 (Markdown)
      emses_cfl_limit.md         # 安定性の知見
      mag_scan_results.md        # 実験結果サマリー
      heating_mechanism.md       # 物理的考察
    environment.toml             # 実行環境記述
    facts.toml                   # advanced: structured claims
  notes/                         # Lab notebook (chronological, append-only)
    2026-04-08.md                # 日次の作業ノート (`runo notes append`)
    2026-04-09.md
    history/                     # 古い日次 notebook (`runo notes archive`)
      2026/
        2026-03-30.md
    reports/                     # 長文 refined レポート
      cs_vs_vti_scaling.md
    README.md                    # notes / materials / .runops の役割
```

## シミュレータ知識

### Codex plugin recommendation

Adapter や site profile は、選択内容に応じて外部 Codex plugin を推薦できる。
`runo init` / `runo setup` は推薦 plugin と導入手順を表示し、project harness
(`AGENTS.md` / `CLAUDE.md`) にも同じ導線を残す。plugin の install / enable は
ユーザーの Codex 環境に対する操作なので、runops project state には含めない。

例:

- `emses`: `MPIEMSES3D Context`, `emout Context`
- `camphor` site profile: `KUDPC HPC`
- `grand` site profile: `GRAND HPC`

private repo の plugin は GitHub 認証済み環境、local checkout marketplace、または
利用者が自作する environment skill のいずれかで扱う。

### refs/ — 任意のリファレンスミラー

シミュレータ固有の長文 Agent context は、各シミュレータや解析ライブラリの
Codex plugin、または `runo knowledge source attach` で接続する明示的な知識ソースを
優先する。`refs/` は `runo init --with-refs` や手動 clone で用意する任意の
ローカル mirror であり、private repo や開発中 checkout を近くに置きたい場合の
fallback として扱う。

```bash
# 更新
runo init --with-refs     # adapter の doc_repos() を refs/ に clone
runo update-refs          # 全シミュレータの任意 refs mirror
runo update-refs emses    # 特定のシミュレータのみ
runo update-refs --dry-run
```

`update-refs` は:
1. `refs/` 以下に存在する任意 mirror を `git fetch --depth 1` + `git reset` で最新化
2. 変更を検出 (コミットハッシュ比較)
3. `.runops/knowledge/{simulator}.md` に mirror インデックスを再生成

### knowledge/ — 生成済み Agent context

`.runops/knowledge/` は package-provided guide、外部 knowledge source、任意
`refs/` mirror から作る生成済み context である。AI エージェントは
`.runops/knowledge/enabled/imports.md` や plugin skill を先に読み、必要に応じて
`refs/` の実ファイルを fallback として参照する。
`.runops/knowledge/enabled/imports.md` も同じく、外部 source profile を
Agent が読みやすい形へレンダリングした派生物であり、手で編集する正本ではない。

```markdown
# Knowledge Index: emses
Auto-generated by `runo update-refs` on 2026-03-30

## MPIEMSES3D
**Commit**: `abc12345`

### Files
- `refs/MPIEMSES3D/docs/parameters.md`
- `refs/MPIEMSES3D/docs/stability.md`
...

## Change Log
- 2026-03-30: MPIEMSES3D (`abc12345` -> `def67890`)
```

### Adapter のパラメータスキーマ

各 Adapter は `parameter_schema()` で機械可読なパラメータメタデータを提供する:

```python
EmseAdapter.parameter_schema()
# {
#     "tmgrid.dt": {
#         "type": "float",
#         "unit": "1/omega_pe",
#         "description": "Time step in normalized units",
#         "range": [0.0, None],
#         "constraints": ["cfl_condition"],
#         "derived_from": "Must satisfy dt < dx / cv",
#         "interdependencies": ["tmgrid.nx", "plasma.cv"],
#     },
#     ...
# }
```

### パラメータバリデーション

`validate_params()` は run 生成前に物理的整合性をチェックする:

- **EMSES**: CFL 条件、Debye 長解像度、格子整合性、ドメイン分割一貫性
- **BEACH**: 時間刻み安定性、電荷中性、正値チェック

```
$ runo runs create flat_surface
  Warning: CFL ratio dt*cv = 0.95 is close to stability limit (1.0).
  Error: Grid nx=64 is not divisible by MPI decomposition nodes[0]=5.
Error creating run: Parameter validation failed with 1 error(s)
```

## 実行環境知識

### environment.toml

`.runops/environment.toml` に HPC クラスタの情報を記述する。
`runo doctor` 実行時に自動検出・保存される。

```toml
[cluster]
name = "your-hpc"
scheduler = "slurm"
scratch_path = "/scratch/{user}"

[cluster.partitions.default]
max_nodes = 16
max_walltime = "72:00:00"

[cluster.partitions.gpu]
max_nodes = 4
max_walltime = "24:00:00"
gpu = true

[cluster.constraints]
max_jobs_per_user = 100

[modules]
intel2023 = ["intel/2023.2", "intelmpi/2023.2", "hdf5/1.12.2_intel-2023.2-impi"]
```

`runo doctor` は `sinfo` と `module list` を使ってパーティション情報とロード済みモジュールを自動検出する。

## 研究意図 (campaign.toml)

プロジェクトルートに配置し、AI エージェントに「何を調べたいか」を伝える。

```toml
[campaign]
name = "magnetic-angle-dependence"
description = "磁場角度がプラズマ-表面相互作用に与える影響を調査"
hypothesis = "磁力線入射角 45 度付近でイオンフラックスが最大になる"
simulator = "emses"

[variables]
"plasma.wc" = { role = "independent", range = [0.0, 0.5], unit = "omega_pe" }
"plasma.phiz" = { role = "independent", range = [0.0, 90.0], unit = "deg" }
"tmgrid.dt" = { role = "fixed", values = [1.0], reason = "CFL 条件を満たす値" }

[observables]
ion_flux = { source = "work/influx", column = 1, description = "表面へのイオンフラックス" }
surface_potential = { source = "work/volt", column = 1, description = "表面電位" }
```

### 変数のロール

| role | 意味 | 用途 |
|------|------|------|
| `independent` | 実験で走査する変数 | survey.toml の axes に対応 |
| `dependent` | 測定する応答変数 | observables と重複可 |
| `fixed` | 固定値 (変えない) | 条件の明示化 |
| `controlled` | 固定だが将来変更可能 | 拡張用 |

### AI エージェントの活用

エージェントは campaign.toml を読んで:
1. `variables` から survey.toml のパラメータ軸を自動生成
2. `observables` から解析対象を特定
3. `hypothesis` に基づいて結果の解釈・考察を生成

## Simulator Cookbook

simulator repo 側に `cookbook/` ディレクトリを置き、
Agent がパラメータ生成の出発点として使える入力例・設定フラグメントを提供する。

- `cookbook/COOKBOOK.md` — この cookbook の概要と管理ガイド
- `cookbook/index.toml` — 全 entry の目録
- `cookbook/examples/` — 完全な入力例
- `cookbook/fragments/` — 再利用可能な部分設定

Agent の利用順序:

1. `cookbook/COOKBOOK.md` で概要を把握
2. `cookbook/index.toml` で候補を選ぶ
3. 各 entry の `meta.toml` で用途と適用条件を確認
4. `input.toml` / `fragment.toml` の実ファイルを読む
5. `README.md` で注意事項を確認

制約チェックは runops Adapter の `validate_params()` が担当する。
cookbook は「何をどう使うか」に集中する。

詳細仕様は [simulator-kb-spec.md](../simulator-kb-spec.md) を参照。

## 外部知識ソース (Knowledge Sources)

### 概要

テーマごとに project を分けても、シミュレータ知識や解析知識を毎回教え直さなくてよいように、
外部の共有知識リポジトリを project に接続できる。

知識は 3 種に分かれる:

| 種別 | 説明 | 保管場所 |
|------|------|----------|
| **source knowledge** | 外部の共有知識リポジトリ。複数 project 間で再利用 | `refs/knowledge/<name>/` |
| **local knowledge** | project 固有の知識 | `.runops/insights/`, `.runops/facts.toml` 等 |
| **derived knowledge** | source と local から生成される派生物 | `.runops/knowledge/enabled/` |

### 設定 (runops.toml)

```toml
[knowledge]
enabled = true
mount_dir = "refs/knowledge"
derived_dir = ".runops/knowledge"
auto_sync_on_setup = true
generate_claude_imports = true

[[knowledge.sources]]
name = "shared-lab-knowledge"
type = "git"
kind = "profiles"
url = "git@github.com:lab/hpc-shared-knowledge.git"
ref = "main"
mount = "refs/knowledge/shared-lab-knowledge"
profiles = ["common-analysis", "emses-basic"]

[[knowledge.sources]]
name = "previous-campaign"
type = "path"
kind = "project"
path = "../previous-campaign"
```

### 操作

```bash
# 外部知識ソースの接続
runo knowledge source attach git shared-kb git@github.com:lab/hpc-shared-knowledge.git
runo knowledge source attach path previous-campaign ../previous-campaign --kind project
runo knowledge source attach path shared-insights ../shared-insights --kind insights

# 同期 (git clone/pull + imports.md 再生成)
runo knowledge source sync                    # 全ソース
runo knowledge source sync shared-kb          # 特定ソースのみ

# imports.md をレンダリング
runo knowledge source render

# 状態確認
runo knowledge source status
runo knowledge source list

# profile の切替
runo knowledge profile enable shared-kb common-analysis
runo knowledge profile disable shared-kb emses-basic

# 切断
runo knowledge source detach shared-kb
```

### 共有知識リポジトリの構造

`runops` は知識ソースに次の構造を期待する:

```
repo/
  README.md              # 必須
  CLAUDE.md              # 推奨 (Agent 向け概要)
  entrypoints.toml       # 推奨 (imports の明示的 manifest)
  profiles/              # 必須
    common-analysis.md   # profile ファイル (Markdown)
    emses-basic.md
  simulators/            # シミュレータ固有知識
  analysis/              # 解析手法・recipe
  commands/              # Agent 用コマンドテンプレート
```

`entrypoints.toml` がある場合、`render_imports()` はそこに列挙された `imports` / `profiles.<name>.imports` だけを `imports.md` に載せる。manifest に無い profile は `profiles/<name>.md` へフォールバックする。`validate_source_structure()` は `entrypoints.toml` の parse、参照先ファイル、profile 内 `@...` import、`analysis/observables/*.toml` と `analysis/recipes/*.toml` も検査する。

### CLAUDE.md 連携

`runo knowledge source render` が `.runops/knowledge/enabled/imports.md` を生成する。
このファイルは有効な profile への `@import` 参照を含み、
project の `CLAUDE.md` から `@.runops/knowledge/enabled/imports.md` で一括参照できる。

`runo init` 時に CLAUDE.md テンプレートに自動挿入される。

### init / setup での動作

- **`runo init`** (対話モード): GitHub の `*shared_knowledge*` リポジトリを自動検索し、候補として提案。手動 URL 入力も可能
- **`runo setup`**: `runops.toml` に設定された知識ソースを自動同期し、`imports.md` をレンダリング

## Lab notebook (`notes/`)

curated knowledge と並列に運用する **append-only な時系列ノート**。
research process の各フェーズ (準備 / 実行 / 解析) で生まれる raw な
情報を、後で整理する前にそのまま残すための場所。

### なぜ curated knowledge と分けるのか

`runo knowledge save <name>` は **同名で書くと上書き** される。
これは curated knowledge が「最終的な整理済 findings」を入れる場所として
正しい挙動だが、「今やってる作業のメモ」「途中で見つけた反例」「却下した
代替案」「ユーザーとの議論の流れ」といった **chronological な情報** とは
shape が違う。

lab notebook はこの隙間を埋める:

| 用途 | 場所 | 性質 | コマンド |
|---|---|---|---|
| 日次の lab notebook | `notes/YYYY-MM-DD.md`, `notes/history/YYYY/YYYY-MM-DD.md` | append-only, chronological | `runo notes append`, `runo notes archive` |
| 長文 refined レポート | `notes/reports/<topic>.md` | refined, 改稿可 | (直接編集) |
| source material | `materials/` | visible, inspectable | (直接編集) |
| 整理済の名前付き知見 | `.runops/insights/<name>.md` | advanced, durable, 上書き可 | `runo knowledge save` |
| 機械可読 atomic claim | `.runops/facts.toml` | advanced, atomic | `runo knowledge add-fact` |

### ファイル形式

- 1 ファイル = 1 日。日付は ISO (`2026-04-08.md`)、JST 基準
- 既存ファイルが無ければ `# YYYY-MM-DD — lab notebook` ヘッダを付けて新規作成
- 各 entry は `## HH:MM <title>` 直下に本文 (markdown 自由)
- **append-only**: 既存 entry には触らない
- 古い日次 notebook は `runo notes archive --older-than 7d` で
  `notes/history/YYYY/YYYY-MM-DD.md` に移す。`notes list/show` は active と
  history を透過的に検索する

例:

```markdown
# 2026-04-08 — lab notebook

## 14:32 Series A vti scan 設計

独立軸: vti = 1..19 eV (10 点, 線形). 4σ CFL で 19 eV が上限.
固定: vflow=400 km/s, vte=10 eV, plate -34 V.
没案: vflow も振る → 30 run × 2 で資源不足.

## 16:05 cs scaling preview

3 点で `tan α = 0.79 (cs/vflow) + 0.02, R² = 0.9997` が出た.
vti scaling より明らかに良い. 3 点だけなのが心配, Series B 完走で確認.
```

### コマンド

```bash
# 追記 (inline)
runo notes append "<title>" "<body...>"

# 追記 (stdin から本文)
runo notes append "<title>" -
echo "..." | runo notes append "<title>"

# heredoc
runo notes append "<title>" - <<'EOF'
- A
- B
- C
EOF

# 一覧 (新しい順, デフォルト 14 日)
runo notes list
runo notes list -n 30

# 内容表示
runo notes show today      # 今日 (JST)
runo notes show latest     # 最新の日
runo notes show 2026-04-08 # 特定日

# 古い日次 notebook を notes/history/YYYY/ に移動
runo notes archive --older-than 7d
```

### いつ書くか — フェーズ別ガイド

`/note` skill は **準備フェーズから使う**。解析時だけでなく:

**準備フェーズ (campaign / case / survey 設計)**:

- 意思決定の理由 (なぜこの値・範囲・解像度を選んだか)
- 設計トレードオフ (何と何を秤にかけて、何を切り捨てたか)
- 却下した代替案 (一度考えてやめたデザイン)
- 資源見積もり (想定 core-hour, queue, 投入順序の判断材料)
- 検証計画 (smoke test の選び方, 成否判定基準)
- 不安・前提 (「ここが心配」「ここが勘」と思う部分)

**投入・実行フェーズ**:

- 投入したコマンド・対象 run・queue・資源量
- 中断・再投入の理由
- ジョブの異常 (kill, requeue, OOM, 異常終了) と対処
- 暫定 status (e.g. "夕方時点で 12/30 完走")

**解析フェーズ**:

- 試したコマンド・スクリプトと結果 (1-3 行)
- 観察したこと (e.g. "α が R0036 で 6.13°")
- 仮説 (e.g. "intercept は sheath 厚由来かも")
- 失敗・つまづき
- TODO・次の一手
- 議論の流れ (user との対話で出てきた論点)

### 昇格パス

```
notes/YYYY-MM-DD.md           ← 日次の意思決定・観察ログ
notes/history/YYYY/YYYY-MM-DD.md
                               ← 古い日次 notebook
        ↓ (ストーリーが固まる)
notes/reports/<topic>.md      ← refined long-form report
        ↓ (atomic な知見を抽出)
.runops/insights/<name>.md    ← curated insight
.runops/facts.toml            ← atomic claim
```

`/learn` skill は **`notes/` を素材として読む** ことを前提にしている:
`runo notes list` で日付一覧を取り、関連する `runo notes show` で
読んで、散らばった raw observation を一つの insight にまとめてから
`runo knowledge save` / `add-fact` で curated 化する。出処になった
日付を insight 本文に書き残しておくと、後から原料を辿れる。

## 知見 (Insights)

### 知見の種類

| type | 説明 | 例 |
|------|------|---|
| `constraint` | 安定性・制約の発見 | 「dt > 1.5 で不安定」 |
| `result` | 実験結果のサマリー | 「サーベイ全体の傾向」 |
| `analysis` | 物理的考察・解釈 | 「加熱メカニズムの推定」 |
| `dependency` | パラメータ依存性 | 「密度と帯電量は線形関係」 |

### 知見の形式

`.runops/insights/` に frontmatter 付き Markdown ファイルとして保存:

```markdown
---
type: result
simulator: emses
tags: [magnetic_field, ion_flux, survey]
source_project: magnetosphere
created: 2026-03-30
---

# 磁場角度サーベイ結果

## サマリー
磁力線入射角 0-90 度のサーベイ (9 runs) を実施。
イオンフラックスは 45 度で最大 (仮説と一致)。

## 詳細
- wc=0.0 (無磁場): フラックス 1.0 (基準値)
- wc=0.294, phi=45: フラックス 2.3 (最大)
- wc=0.294, phi=90: フラックス 0.8

## 考察
磁場がイオン軌道を曲げることで表面への入射角が変化し、
45 度付近でイオン収束効果が最大になると考えられる。
```

### 知見の操作

```bash
# 保存
runo knowledge save mag_results -t result -s emses \
  -m "磁場角度 45度でイオンフラックス最大"

# 構造化 fact の追加
runo knowledge add-fact "CFL limit: dt < 1.0 for emses" \
  -t constraint -s emses --param-name tmgrid.dt -c high \
  --evidence-kind run_observation --evidence-ref run:R20260330-0001

# 一覧
runo knowledge list
runo knowledge list -s emses -t constraint
runo knowledge facts
runo knowledge facts --scope emses -c high
runo knowledge facts --local-only

# shared fact の昇格
runo knowledge promote-fact shared:f004

# 表示
runo knowledge show emses_cfl_limit

# リンク先からインポート
runo knowledge source sync
runo knowledge source sync -s emses
```

### SKILL による操作

AI エージェントは `/learn` スキルを使って知見を保存する。
「知識をまとめて」「結果を記録して」等の指示はすべて `/learn` 経由で
プロジェクトの knowledge システムに保存される（Agent 自身の memory には保存しない）。

## プロジェクト間の知識共有

`knowledge.sources` は `kind` に応じて役割が分かれる:

| `kind` | 用途 | 同期時の扱い |
|--------|------|-------------|
| `profiles` | 共有 knowledge repo を mount して `profiles/` を読む | `refs/knowledge/<name>/` に同期し、`imports.md` を再生成 |
| `project` | 別の runops project の `.runops/insights/` / `.runops/facts.toml` を参照 | insights をコピーし、facts は candidate transport に同期 |
| `insights` | `insights/` ディレクトリや `facts.toml` を持つ共有 knowledge store を参照 | insights をコピーし、facts は candidate transport に同期 |

```toml
[[knowledge.sources]]
name = "surface-charging"
type = "path"
kind = "project"
path = "../surface-charging"

[[knowledge.sources]]
name = "analysis-notes"
type = "git"
kind = "insights"
url = "git@github.com:lab/analysis-notes.git"
mount = "refs/knowledge/analysis-notes"
```

`runo knowledge source sync` の流れ:

```
runo knowledge source sync
  → 各 knowledge source を同期 (git clone/pull or path validate)
  → kind=profiles の source から imports.md を再生成
  → kind=project / kind=insights の source から insight を取り込む
  → kind=project / kind=insights の source から facts を
    .runops/knowledge/candidates/facts/*.toml に同期する
  → 結果を報告
```

取り込まれた insight は source 名で namespace されたファイル名
(`alpha__stability.md` など) で保存される。同じ namespace 内で
同名の insight が既に存在する場合はスキップされる。

shared facts は candidate として source ごとの TOML に保持され、`knowledge facts`
では local fact と一緒に参照できる。採用する fact は
`runo knowledge promote-fact <source>:<fact_id>` で local `.runops/facts.toml`
へ昇格する。

## AI エージェントの推奨ワークフロー

```
1. UNDERSTAND: campaign.toml + knowledge/ + insights/ + notes/ を読む
   → 研究目的、既知の制約、過去の知見、最近の lab notebook を把握

2. PLAN: parameter_schema() + validate_params() を活用
   → 物理的に妥当なパラメータセットを設計
   → 設計の理由・トレードオフ・却下案を runo notes append で残す

3. EXECUTE: runo runs create + runo runs submit
   → survey.toml → run 生成 → job 投入
   → 投入直前に runo notes append でスナップショット (commit hash, run_id 範囲)

4. MONITOR: runo runs status + runo runs log + runo runs sync
   → 実行状況の追跡 (bulk sync は terminal state を silent skip)
   → 異常があれば runo notes append で記録

5. ANALYZE: runo analyze summarize + runo analyze collect
   → 結果の集計・要約
   → 観察・仮説を runo notes append で raw に残す

6. LEARN: runo notes list / show で素材を集めて runo knowledge save / add-fact
   → 結果と考察を curated 層 (.runops/insights/, facts.toml) に昇格
   → 出処になった日付を insight 本文に書き残す

7. ITERATE: 知見に基づいてパラメータを改善
   → 次の実験サイクルへ
```
