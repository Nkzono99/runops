# runops

HPC 環境における Slurm ベースのシミュレーション実行管理 CLI ツール。

run ディレクトリを日常運用の主単位とし、パラメータサーベイ展開・job 投入・状態追跡・provenance 記録・解析補助を一貫して管理します。

日常的な CLI コマンド名は `runo`（ルーノ）です。既存スクリプトとの互換性のため、
`runops` コマンドも同じ CLI を指す stable alias として残しています。

## 特徴

- **run 中心の管理**: すべての操作は run ディレクトリ (`runs/.../Rxxxx/`) を基点に行う
- **パラメータサーベイ**: survey.toml による parameter sweep の自動展開（直積生成）
- **Slurm 連携**: sbatch による job 投入、squeue/sacct による状態同期
- **Simulator Adapter**: シミュレータ固有処理を Adapter パターンで抽象化。core はシミュレータに依存しない
- **Launcher Profile**: srun / mpirun / mpiexec の起動方式を Profile で切替可能
- **Provenance 記録**: git commit、executable hash、パラメータ snapshot を manifest.toml に自動記録
- **多重ネスト対応**: `runs/` 以下を自由に階層化して分類・整理できる
- **Agent/AI 対応**: TOML/JSON ベースの構造化データで AI エージェントとの連携が容易
- **Demo Replay**: Codex session log から replay HTML を生成し、操作の流れを研究室向けに可視化できる
- **知識層**: `notes/`, `materials/`, `research/` を人間/Agent の共有作業場にし、`.runops/knowledge/` で生成済みコンテキストを提供
- **外部知識ソース**: 共有知識リポジトリを project に接続し、profile ベースで必要な知識だけを投影
- **Lab notebook**: `notes/YYYY-MM-DD.md` に append-only な時系列ノートを残し、`notes/reports/` で整理済みレポートに育てる
- **Research Layer**: `research/agenda.md` に現在の高レベルな研究判断を残す
- **パラメータバリデーション**: 物理的制約 (CFL 条件, Debye 長等) を run 生成前にチェック
- **Research Campaign**: campaign.toml で研究仮説・変数・観測量を構造化し、実験設計を明示

## インストール

runops はプロジェクトごとにブートストラップインストールされます。
事前のグローバルインストールは不要で、[uv](https://docs.astral.sh/uv/) だけあれば始められます。

```bash
# プロジェクトディレクトリを作成して初期化 (uv だけあれば OK)
uvx --from runops runo init

# activate して利用開始
source .venv/bin/activate
runo doctor
```

`runo init` が以下を自動的に行います:

1. `.venv/` を作成 (`uv venv`)
2. `tools/runops/` に runops リポジトリを clone
3. runops を `.venv` に editable install (`uv pip install -e`)
4. シミュレータ固有パッケージをインストール

runops の更新は `cd tools/runops && git pull` で行えます。

### 既存プロジェクトのセットアップ

```bash
uvx --from runops runo setup https://github.com/user/my-project.git
source my-project/.venv/bin/activate
runo doctor
```

### 開発者向け (runops 自体の開発)

```bash
git clone https://github.com/Nkzono99/runops.git
cd runops
uv sync --dev
```

## デモ作成

Codex の session log から、研究室向けの replay UI を self-contained な HTML として生成できます。

```bash
uv run runo demo build-codex-replay \
  ~/.codex/sessions/2026/04/24/rollout-....jsonl \
  --out replay.html \
  --workspace-root .
```

生成された `replay.html` には chapter ナビゲーション、ファイルツリー、現在イベントの command/diff/output 表示、activity feed、timeline が含まれます。詳細は [docs/demo-replay.md](docs/demo-replay.md) を参照してください。

## クイックスタート

### 1. プロジェクトの初期化

上記のインストール手順を実行すると、以下のファイル・ディレクトリが生成されます:

```
my-simulation-project/
  runops.toml      # プロジェクト設定
  simulators.toml      # シミュレータ定義
  launchers.toml       # Launcher Profile 定義
  SITE.md              # site profile 由来の companion doc (生成物)
  campaign.toml        # 研究意図 (仮説・変数・観測量)
  .gitignore           # 大容量出力の除外設定
  CLAUDE.md            # 現在の標準 Agent ハーネス (Claude Code) 向け指示
  AGENTS.md            # CLAUDE.md と同内容の補助ミラー
  .claude/
    settings.json      # Claude Code の team-shared permission / hook 設定
    hooks/             # submit 承認・保護パス監視 hook
    rules/             # project 固有の運用ルール
    skills/            # 定型作業用 SKILL
  cases/               # Case 定義の格納場所
  runs/                # run の格納場所
  refs/                # シミュレータリファレンス / 外部知識ソース
    MPIEMSES3D/        # Adapter が参照する simulator docs
    beach/             # Adapter が参照する simulator docs
    knowledge/         # 外部知識ソースのマウントポイント
      shared-lab-kb/   # git/path で接続した共有知識リポジトリ
  tools/
    runops/        # runops 本体 (editable install, Git 管理外)
  .venv/               # Python 仮想環境 (Git 管理外)
  .runops/             # runops 内部状態 / 生成済み Agent context
    knowledge/         # 自動生成ナレッジ (gitignore 対象)
      enabled/         # 有効な profile の imports.md
      candidates/      # 外部 source 由来の candidate fact transport
    insights/          # advanced: curated Markdown insight
    facts.toml         # advanced: machine-readable structured claims
    environment.toml   # 実行環境記述 (自動検出)
  notes/               # Human/Agent shared workspace: lab notebook
    YYYY-MM-DD.md      # 日次の作業ログ (`runo notes append` で追記)
    reports/           # 長文レポート (改稿可)
    README.md          # notes / materials / .runops の役割
  research/            # Current high-level research decisions
    README.md
    agenda.md          # mutable decision ledger
    proposals/         # optional pre-execution decisions
    reviews/           # optional checkpoint snapshots
  materials/           # Human-provided source material for Agent
    papers/            # PDF, BibTeX, paper notes
    manuals/           # Site / simulator / tool manuals
    figures/           # Reference figures
    snippets/          # Copied examples and source excerpts
    index.toml         # Optional material index
```

`runo init` が生成する Claude ハーネスは、`.claude/settings.json` と
`.claude/hooks/` により次のようなガードを入れます。

- `manifest.toml`、`runs/**/input/**`、`submit/job.sh`、`work/**`、`SITE.md` などの生成物は直接編集しない
- `.runops/knowledge/` は生成済み Agent context なので手で整形しない
- `.runops/facts.toml` や `.runops/insights/` を使う場合は `runo knowledge save` / `add-fact` 経由で更新する
- `runo runs submit` は `--dry-run` を除き実行前に確認を挟む

runops 自体の開発では、Claude ハーネスの定義は
`src/runops/harness/claude.py` にまとまっています。

### 2. 研究意図の定義 (campaign.toml)

プロジェクトルートに `campaign.toml` を作成し、何を調べたいかを記述:

```toml
[campaign]
name = "parameter-sensitivity"
description = "格子サイズと時間刻みの感度解析"
hypothesis = "nx=512 以上で解が収束する"
simulator = "my_solver"

[variables]
"nx" = { role = "independent", range = [128, 1024], unit = "cells" }
"dt" = { role = "independent", range = [1.0e-9, 1.0e-7], unit = "s" }

[observables]
max_field = { source = "work/output.h5", description = "最大電場強度" }
```

AI エージェントはこのファイルを読んで survey 設計や結果解釈に活用します。

### 3. シミュレータと Launcher の設定

`simulators.toml` にシミュレータを定義 (シミュレータ指定で init した場合は自動生成):

```toml
[simulators.my_solver]
adapter = "generic"
resolver_mode = "local_executable"
executable = "/path/to/solver"
```

`launchers.toml` に Launcher Profile を定義:

```toml
[launchers.slurm_srun]
kind = "srun"
command = "srun"
use_slurm_ntasks = true
```

### 4. Case の定義

`runo case new` で case を生成し、`cases/<simulator>/<case>/case.toml` を編集します:

```bash
runo case new my_case -s my_solver
```

生成された `cases/my_solver/my_case/case.toml` の例:

```toml
[case]
name = "my_case"
simulator = "my_solver"
launcher = "slurm_srun"
description = "基本ケース"

[classification]
model = "cavity"
submodel = "rectangular"
tags = ["baseline"]

[job]
partition = "compute"
nodes = 1
ntasks = 32
walltime = "12:00:00"

[params]
nx = 256
ny = 256
dt = 1.0e-8
```

### 5. 単一 run の作成

```bash
runo runs create my_case --dest runs/cavity/test
```

### 6. パラメータサーベイの実行

`runs/cavity/scan/survey.toml` を作成:

```toml
[survey]
id = "S20260327-scan"
name = "parameter scan"
base_case = "my_case"
simulator = "my_solver"
launcher = "slurm_srun"

[axes]
nx = [128, 256, 512]
dt = [1.0e-8, 1.0e-9]

[naming]
display_name = "nx{nx}_dt{dt}"

[job]
partition = "compute"
nodes = 1
ntasks = 32
walltime = "12:00:00"
```

```bash
runo runs sweep runs/cavity/scan
```

### 7. Job の投入

```bash
# cwd の run を投入
cd runs/cavity/test/R20260327-0001
runo runs submit

# survey 内の全 run を一括投入
cd runs/cavity/scan
runo runs submit --all
```

### 8. 状態の確認

```bash
# 単一 run の状態確認
runo runs status R20260327-0001

# Slurm 状態を manifest に同期
runo runs sync R20260327-0001

# run の一覧表示
runo runs list
runo runs list runs/cavity/scan
```

## コマンドリファレンス

### プロジェクト管理

| コマンド | 説明 |
|---------|------|
| `runo init [SIMS...] [-y]` | プロジェクトの初期化 (対話型がデフォルト) |
| `runo setup [URL]` | 既存 runops project のセットアップ |
| `runo doctor [PATH]` | 環境検査 (設定・sbatch・run_id 一意性・環境検出) |
| `runo context [DIR]` | Agent 向け project context の要約を表示 (`research/agenda.md` と latest note の入口を含む) |
| `runo lint [PATH] [--scope ...] [--json]` | project state の health check (structure / runs / provenance / analysis / knowledge) |
| `runo migrate list/show/apply` | `docs/migrations/` に登録された project-state migration を確認・適用 |
| `runo config show` | 設定表示 |
| `runo config add-simulator` | シミュレータ追加 (対話型) |
| `runo config add-launcher` | ランチャー追加 (対話型) |
| `runo update` | シミュレータパッケージのアップグレード |
| `runo update-refs [SIMS...]` | refs/ リポジトリ更新 + ナレッジインデックス再生成 |

### Run 作成・投入

| コマンド | 説明 |
|---------|------|
| `runo case new CASE [--minimal] [--survey]` | 新規 case のスキャフォールド生成 (`--minimal` で小さな bundled テンプレートを使用、EMSES では `emu generate -u` を best-effort で自動実行し `[meta.physical]` を埋める) |
| `runo runs create CASE` | case から単一 run を生成 |
| `runo runs sweep [DIR] [--dry-run]` | survey.toml からパラメータ直積で全 run 一括生成 (`--dry-run` で件数・パラメータ組合せ・概算 core-hour のみ表示) |
| `runo runs submit [RUN]` | run を sbatch で投入 (`-qn` でキュー上書き、`--afterok` で依存ジョブ指定) |
| `runo runs submit --all [DIR]` | created な run を一括投入 |
| `runo runs clone` | run 複製・派生 |
| `runo runs extend` | スナップショットから継続 run 生成 |

### 状態管理・モニタリング

| コマンド | 説明 |
|---------|------|
| `runo runs status [RUNS...]` | run の状態確認 (run_id / run dir / survey dir を複数渡してまとめて表示可) |
| `runo runs sync [RUNS...]` | Slurm 状態を manifest.toml に反映 (bulk 対応: survey 配下の created run + terminal state な run は silent skip) |
| `runo runs log [RUN]` | 最新 job の stdout/stderr 表示 + 進捗% |
| `runo runs jobs [PATH] [--watch SECS]` | プロジェクト内の実行中ジョブ一覧 (`--watch` で自動更新) |
| `runo runs dashboard [TARGETS...] [--watch SECS] [--all]` | 複数 run の進捗 (state, step/N, %, last Slurm state) を 1 つの表で表示 |
| `runo runs history [PATH]` | 投入履歴表示 |
| `runo runs list [PATHS...]` | run の一覧表示 (複数 PATH 指定可、状態・タグでフィルタ可能) |

### 解析・整理

| コマンド | 説明 |
|---------|------|
| `runo analyze summarize [RUN]` | Adapter による run 解析 summary 生成 |
| `runo analyze collect [DIR]` | survey 内の全 run から集計データ生成 |
| `runo analyze plot [DIR]` | survey 集計結果の可視化 (`--recipe` / `--list-recipes` 対応) |
| `runo runs cancel [RUN]` | submitted/running な run を `scancel` + `sync` で安全に停止 |
| `runo runs archive [RUN]` | run のアーカイブ (completed のみ) |
| `runo runs purge-work [RUN]` | work/ 内の不要ファイル削除 (archived のみ) |
| `runo runs delete [RUN]` | created / cancelled / failed の run ディレクトリをハード削除 (completed/archived は archive → purge-work を使う) |

### Lab notebook (実験ノート)

| コマンド | 説明 |
|---------|------|
| `runo notes append TITLE [BODY]` | 今日の `notes/YYYY-MM-DD.md` に timestamped エントリを追記 (`-` または省略で stdin から本文を読む) |
| `runo notes list [-n N]` | 最近の lab notebook 日付一覧 (新しい順) |
| `runo notes show [DATE\|today\|latest]` | 指定日 (省略時は today) の lab notebook を表示 |

`notes/` は append-only な実験ノートと、改稿可能な `notes/reports/` を置く
人間/Agent 共有の知識層です。準備フェーズの意思決定、観察、仮説、TODO を
その場で残し、価値が出てきたら `notes/reports/` の long-form レポートに
整理します。`research/agenda.md` は TODO ではなく、現在の見立て、active
question、paused/killed、次に何をなぜ行うかを残す mutable な判断の台帳です。
`runo context --json` は `research_agenda` と `notes.latest_path` を返すため、
Agent は最初の入口から agenda の存在と現在判断の有無を把握できます。
`materials/` には論文 PDF、manual、図、snippet などの source material を置きます。

`.runops/knowledge/enabled/imports.md` は source knowledge から生成される
Agent context です。`.runops/insights/` と `.runops/facts.toml` は互換性のため
残る advanced/structured knowledge store として扱い、日常のメモやレポートは
まず `notes/`, `materials/`, `research/` に置くことを推奨します。

### 知識管理

| コマンド | 説明 |
|---------|------|
| `runo knowledge save NAME` | 知見を .runops/insights/ に保存 |
| `runo knowledge list` | 知見一覧表示 |
| `runo knowledge show NAME` | 知見の詳細表示 |
| `runo knowledge add-fact CLAIM` | 構造化された知識を facts.toml に追加 |
| `runo knowledge facts` | local facts と imported candidate facts の一覧表示 |
| `runo knowledge promote-fact FACT_ID` | candidate fact を local facts.toml に昇格 |
| `runo knowledge source list` | 外部知識ソース一覧表示 |
| `runo knowledge source attach TYPE NAME URL` | 外部知識ソースを接続 (git / path) |
| `runo knowledge source detach NAME` | 外部知識ソースを切断 |
| `runo knowledge source sync [NAME]` | 知識ソース同期 + insight / fact transport |
| `runo knowledge source render` | 有効な profile から imports.md を生成 |
| `runo knowledge source status` | 知識統合の状態表示 |
| `runo knowledge profile enable SOURCE PROFILE...` | source の profile を有効化して imports.md を更新 |
| `runo knowledge profile disable SOURCE PROFILE...` | source の profile を無効化して imports.md を更新 |

知識管理は三層構造:
- **source knowledge** — 外部共有知識リポジトリ (`refs/knowledge/` にマウント)
- **visible project knowledge** — 人間と Agent が直接読む `notes/`, `materials/`, `research/`
- **derived / structured knowledge** — source と local から生成される `imports.md`、candidate fact transport、advanced な insights/facts

profile source は repo ルートの `entrypoints.toml` で import 対象を明示できる。
`imports.md` はこの manifest を優先し、未指定 profile は `profiles/<name>.md` に
フォールバックする。`imports.md` は source of truth ではなく、Agent が読みやすい
形にレンダリングされた派生コンテキストです。

全コマンドは引数省略時にカレントディレクトリをデフォルトとする。

## プロジェクト構成

```
runops/
  pyproject.toml
  SPEC.md                  # 詳細仕様書
  CLAUDE.md                # 開発ガイド
  AGENTS.md                # Agent 運用ガイド
  src/
    runops/
      cli/                 # CLI エントリポイント (typer)
        main.py            # コマンド登録
        init.py            # init / setup / doctor
        new.py             # case new (`--minimal`, EMSES `emu generate -u`)
        create.py          # runs create / runs sweep (`--dry-run`)
        submit.py          # runs submit (`-qn`, `--afterok`)
        status.py          # runs status / runs sync (bulk-friendly)
        log.py             # runs log
        jobs.py            # runs jobs (`--watch`)
        dashboard.py       # runs dashboard (multi-run 進捗ビュー)
        history.py         # runs history
        list.py            # runs list (複数 PATH 対応)
        clone.py           # runs clone
        extend.py          # runs extend
        analyze.py         # analyze summarize / collect / plot
        notes.py           # notes append / list / show (lab notebook)
        manage.py          # runs archive / purge-work / cancel / delete
        update.py          # update (パッケージ更新)
        update_refs.py     # update-refs (refs/ 更新 + ナレッジ)
        knowledge.py       # knowledge / knowledge source
        config.py          # config (設定管理)
      core/                # ドメインロジック
        project.py         # Project 読込・検証
        case.py            # Case 読込・展開
        survey/            # Survey 展開・parameter 直積
        run/               # RunInfo・run_id 採番・run directory 作成
        run_creation/      # case / survey から run を生成する orchestration
        manifest.py        # manifest.toml 読書き
        state.py           # 状態遷移管理
        provenance.py      # コード provenance 取得
        discovery.py       # runs/ 再帰探索・run_id 一意性検証
        exceptions.py      # ドメイン例外
        site/              # HPC site profile 解決
        validation/        # パラメータバリデーション
        campaign.py        # campaign.toml 読込
        environment/       # 実行環境検出・記述
        knowledge/         # 知識層 (insights, facts)
        knowledge_source/  # 外部知識ソース管理
        demo/              # session import / replay UI
      adapters/            # Simulator Adapter
        base.py            # SimulatorAdapter 抽象基底クラス
        registry.py        # Adapter 登録・lookup
        generic.py         # 汎用 Adapter 実装
      launchers/           # Launcher Profile
        base.py            # Launcher 抽象基底クラス
        srun.py            # srun Launcher
        mpirun.py          # mpirun Launcher
        mpiexec.py         # mpiexec Launcher
      jobgen/              # job.sh 生成
        generator.py       # Slurm batch script 生成
      slurm/               # Slurm 連携
        submit.py          # sbatch 投入
        query.py           # squeue / sacct 問合せ
  tests/
  docs/
```

## 状態遷移

run は以下の状態遷移に従います:

```
created --> submitted --> running --> completed
                |           |
                v           v
             failed      failed
                |
                v
            cancelled

completed --> archived --> purged
```

`runo runs cancel` は `submitted` / `running` の run に対して `scancel` と `sync`
を組み合わせて発行し、最終状態を `cancelled` に遷移させます。
`runo runs delete` はライフサイクル外の操作で、`created` / `cancelled` / `failed`
の run ディレクトリを直接削除します (`completed` / `archived` の run は
`archive` → `purge-work` 経路を使ってください)。

> **Note**: `runo runs sync` は Slurm の観測結果を manifest に反映するため、
> ポーリング間隔によっては `submitted → completed` のように途中状態を飛び越す遷移が発生します。
> 詳細は [SPEC.md](SPEC.md) を参照してください。

## 技術スタック

- Python 3.10+
- CLI: [typer](https://typer.tiangolo.com/) (click ベース)
- 設定ファイル: TOML (tomli / tomli-w)
- パッケージ管理: [uv](https://docs.astral.sh/uv/)
- テスト: pytest
- Lint/Format: ruff
- 型チェック: mypy (strict)

## 開発

```bash
# テスト
uv run pytest

# Lint
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/

# 型チェック
uv run mypy src/

# CLI 実行 (開発中)
uv run runo --help
```

## ドキュメント

- [AI エージェントではじめる](docs/get-started-with-agent.md) -- `runo init` 済み project を Agent と進める最短導線
- [AI Agent 運用概念図](docs/project-flow.md) -- `runo init` 後の project を Agent とどう回すかの全体像
- [src 構成ガイド](docs/src-structure.md) -- `src/runops/` の層構造と adapter / launcher / site 解決の流れ
- [アーキテクチャ](docs/architecture.md) -- システム設計とモジュール構成
- [拡張ガイド](docs/extending.md) -- Adapter / Launcher の追加方法
- [レイヤー一覧](docs/layers/README.md) -- project 側状態と運用境界の正本
- [実験層](docs/layers/experiment.md) -- campaign / case / survey の設計正本
- [Execution Kernel](docs/layers/execution-kernel.md) -- run / submit / sync / manifest / provenance の実行状態正本
- [解析層](docs/layers/analysis.md) -- 解析・可視化成果物の置き場所と運用ルール
- [研究判断層](docs/layers/research.md) -- `research/agenda.md` による判断台帳
- [知識層](docs/layers/knowledge.md) -- AI エージェント向け知識管理アーキテクチャ
- [ハーネス層](docs/layers/harness.md) -- Agent instructions / skills / rules の責務分離
- [Upstream 連携層](docs/layers/upstream.md) -- `tools/runops` local patch / feedback / PR の境界
- [移行ガイド](docs/migrations/README.md) -- runops 更新時の project-state migration 手順
- [TOML リファレンス](docs/toml-reference.md) -- 全設定ファイルのフィールド定義
- [SPEC.md](SPEC.md) -- 完全な仕様書

## ライセンス

Apache-2.0
