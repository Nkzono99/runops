# AGENTS.md — runops

## プロジェクト概要

HPC 環境における Slurm ベースのシミュレーション実行管理 CLI ツール。
run ディレクトリを日常運用の主単位とし、パラメータサーベイ展開・job 投入・状態追跡・provenance 記録・解析補助を一貫して管理する。

仕様書: `SPEC.md`

## コミュニケーション

- **日本語で応答する**。コード・コマンド・変数名・エラーメッセージは英語のまま
- commit message は英語 (`fix:`, `feat:`, `refactor:`, `test:`, `docs:`)
- Agent 向けドキュメント (rules, skills, agents) は日本語で書いてよい

## Codex ハーネス

このリポジトリでは Claude Code 用の `.claude/` に加えて、Codex 用に以下を置く。

| 目的 | Codex 側 | Claude 側 |
|------|----------|-----------|
| Project doc | `AGENTS.md` | `CLAUDE.md` |
| 定型スキル | `.agents/skills/<name>/SKILL.md` | `.claude/skills/<name>/SKILL.md` |
| 専門 agent 由来の知識 | `.agents/skills/<name>/SKILL.md` | `.claude/agents/<name>.md` |
| 実行設定 | `.codex/config.toml` | `.claude/settings.json` |
| 高コスト / 不可逆 command policy | `.codex/rules/runops.rules` | `.claude/settings.json` permissions |
| 設計・運用リファレンス | `.codex/rules/*.md` | `.claude/rules/*.md` |

Codex ではスキルを `$check`, `$release`, `$implement-core` のように `$` 付きで呼ぶ。
Claude Code の `/check` などとは表記が異なる。

Codex の project-local config は、この repo を trusted project として登録したときに読む。
詳細は `.codex/README.md` を参照する。
shared な運用変更を入れたら、`AGENTS.md`, `CLAUDE.md`,
`.agents/skills/release/SKILL.md`, `.claude/skills/release/SKILL.md`,
`.codex/rules/dev-workflow.md`, `.claude/rules/dev-workflow.md`,
`.codex/rules/gotchas.md`, `.claude/rules/gotchas.md` の drift も点検する。

## プロジェクトでの利用方法

runops はプロジェクトごとにブートストラップインストールする。事前のグローバルインストールは不要。
CLI は `runo` を標準コマンドとして使う。既存スクリプトとの互換性のため、
`runops` も同じ CLI を指す stable alias として残す。

```bash
# 新規プロジェクト作成
mkdir my-project && cd my-project
uvx --from runops runo init

# activate
source .venv/bin/activate
runo doctor
```

`runo init` が `.venv/` と `tools/runops/` を自動構築し、editable install する。
Agent は `tools/runops/docs/` や `tools/runops/SPEC.md` を直接参照できる。

```bash
# 既存プロジェクトを clone + セットアップ
uvx --from runops runo setup https://github.com/user/my-project.git
source my-project/.venv/bin/activate
runo doctor
```

## 技術スタック

- 言語: Python 3.10+
- パッケージ管理: uv (pyproject.toml)
- CLI フレームワーク: typer (click ベース)
- 設定ファイル形式: TOML (tomli / tomli-w)
- テスト: pytest
- Lint/Format: ruff
- 型チェック: mypy (strict)

## ディレクトリ構成

```
runops/
  pyproject.toml
  src/
    runops/
      __init__.py
      cli/              # CLI エントリポイント (typer)
        main.py
        init/           # runo init / doctor / scaffold / bootstrap
        knowledge/      # runo knowledge / knowledge source
        setup.py        # runo setup (clone + bootstrap)
        new.py          # runo case new
        create.py       # runo runs create / sweep
        submit.py       # runo runs submit
        status.py       # runo runs status / sync
        manage.py       # runo runs archive / purge-work / cancel / delete
        update_harness.py
        ...
      core/             # ドメインロジック
        project.py
        case.py
        survey/          # Survey 展開・parameter 直積
        run/             # RunInfo・run_id 採番・run directory 作成
          __init__.py
        manifest.py
        state.py
        provenance.py
        discovery.py
        site/            # HPC site profile 解決
        environment/     # 実行環境検出・記述
        validation/      # パラメータバリデーション
        run_creation/    # case/survey から run を生成する orchestration
          __init__.py
          manifest.py
          merge.py
        knowledge_source/  # 外部知識ソース管理
          __init__.py
          config.py
          render.py
          validation.py
        demo/            # session import / replay UI
          __init__.py
          importer.py
          replay.py
        publication/
        ...
      adapters/         # Simulator Adapter
        __init__.py
        base.py         # SimulatorAdapter 抽象基底クラス
        registry.py     # Adapter 登録・lookup
      launchers/        # Launcher Profile
        __init__.py
        base.py         # Launcher 抽象基底クラス
        srun.py
        mpirun.py
        mpiexec.py
      jobgen/           # job.sh 生成
        __init__.py
        generator.py
      slurm/            # Slurm 連携 (sbatch / squeue / sacct)
        __init__.py
        submit.py
        query.py
      sites/            # bundled site preset (runo init で読込)
        __init__.py
        camphor.toml
        camphor.md
      harness/          # project 側 harness 生成 / 更新ロジック
        __init__.py
        builder.py
        claude.py
        codex.py
      templates/        # project / case / survey 用 静的テンプレート
        __init__.py
        ...
  tests/
    conftest.py
    test_core/
    test_cli/
    test_adapters/
    test_launchers/
    test_slurm/
    fixtures/           # テスト用 TOML ファイル等
```

## 主要コマンド

| コマンド | 説明 |
|---------|------|
| `runo --version` | runops package version を表示 |
| `runo init [SIMS...] -y` | Project 初期化 (対話型がデフォルト) |
| `runo setup [URL]` | 既存プロジェクトを clone + 環境セットアップ |
| `runo doctor` | 環境検査 |
| `runo context --json` | Agent 向け project context を JSON で取得 |
| `runo case new CASE [--minimal] [--survey]` | case のスキャフォールド生成 (`--minimal` で小さな bundled テンプレート、EMSES では `emu generate -u` を自動実行) |
| `runo runs create CASE` | case から単一 run を生成 |
| `runo runs sweep [DIR] [--dry-run]` | survey.toml からパラメータ直積で全 run 生成 (`--dry-run` で件数・パラメータ・概算 core-hour を表示するだけ) |
| `runo runs submit [RUN]` | run を sbatch で投入 (`-qn`, `--afterok` 対応) |
| `runo runs submit --all [DIR]` | created な run を一括投入 |
| `runo runs log [RUN]` | 最新 job の stdout/stderr 表示 + 進捗% |
| `runo runs status [RUNS...]` | run 状態確認 (run_id・run dir・survey dir を複数渡してまとめて表示可) |
| `runo runs sync [RUNS...]` | Slurm 状態を manifest に反映 (bulk 対応: survey 配下の created run + terminal state な run は silent skip) |
| `runo runs jobs [PATH] [--watch SECS]` | プロジェクト内の実行中ジョブ一覧 (`--watch` で N 秒ごとに自動更新) |
| `runo runs dashboard [TARGETS...] [--watch SECS] [--all]` | 複数 run の進捗 (state, step/N, %, last Slurm state) を 1 つの表で表示 |
| `runo runs history [PATH]` | 投入履歴表示 |
| `runo runs list [PATHS...]` | run 一覧表示 (複数 PATH 指定可) |
| `runo runs clone` | run 複製・派生 |
| `runo runs extend` | スナップショットから継続 run 生成 |
| `runo runs retry [RUN] [--plan]` | failed/cancelled run の retry 準備。`--plan` では状態を戻さず partial output と retry intent を記録 |
| `runo analyze summarize [RUN]` | run 解析 summary 生成 |
| `runo analyze collect [DIR]` | survey 集計 |
| `runo analyze new-comparison NAME [--source PATH]` | cross-run 比較 workspace (`analysis/cross_run/`) を作成 |
| `runo notes append TITLE [BODY]` | 今日の lab notebook (`notes/YYYY-MM-DD.md`) に追記 (`-` または省略で stdin) |
| `runo notes list` | active / history の lab notebook 日付一覧 |
| `runo notes show [DATE\|today\|latest]` | active / history から指定日の lab notebook を表示 |
| `runo notes archive [--older-than 7d]` | 古い日次 notebook を `notes/history/YYYY/` に移動 |
| `runo runs archive [RUN]` | run アーカイブ (completed のみ) |
| `runo runs purge-work [RUN]` | work/ 内の不要ファイル削除 (archived のみ) |
| `runo runs cancel [RUN]` | scancel + sync を同時実行し、submitted/running な run を停止 |
| `runo runs delete [RUN]` | created/cancelled/failed な run ディレクトリをハード削除 (completed/archived は archive→purge-work を使う) |
| `runo config show` | 設定表示 |
| `runo config add-simulator` | シミュレータ追加 (対話型) |
| `runo config add-launcher` | ランチャー追加 (対話型) |
| `runo update-refs` | refs/ リポジトリ更新 + ナレッジインデックス再生成 |
| `runo knowledge save` | 知見を .runops/insights/ に保存 |
| `runo knowledge add-fact` | 構造化 fact を .runops/facts.toml に追加 |
| `runo knowledge list` | 知見一覧表示 |
| `runo knowledge facts` | 構造化 fact 一覧表示 |
| `runo knowledge show` | 知見の詳細表示 |
| `runo knowledge source list` | 外部知識ソース一覧表示 |
| `runo knowledge source attach` | 外部知識ソースを接続 (git / path) |
| `runo knowledge source detach` | 外部知識ソースを切断 |
| `runo knowledge source sync` | 知識ソース同期 + 外部知見取り込み |
| `runo knowledge source render` | 有効な profile から imports.md を生成 |
| `runo knowledge source status` | 知識統合の状態表示 |

全コマンドは引数省略時にカレントディレクトリをデフォルトとする。

## 開発ルール

### コーディング規約

- ruff format / ruff check を CI で強制
- mypy strict モード
- テストカバレッジ 80% 以上を目標
- docstring は Google style

### 設計原則

- **run ディレクトリが主単位**: すべての操作は run_id または run ディレクトリを基点とする
- **不変と可変の分離**: run_id は不変、パスは可変（分類・整理用）
- **Simulator Adapter パターン**: simulator 固有処理は Adapter に閉じ込める。core は simulator に依存しない
- **Launcher Profile パターン**: MPI 起動方式は Launcher に閉じ込める
- **MPI に介入しない**: Python ツールは rank ごとのラッパにならない。job.sh で srun/mpirun を直接実行
- **manifest.toml が正本**: run の状態・由来・provenance はすべて manifest.toml に記録
- **cwd ベース**: 全コマンドはカレントディレクトリをデフォルトターゲットとする

### 後方互換性

- **現在は private リポジトリ**のため、後方互換性は気にしなくてよい
- コマンド名・引数・ファイル形式は自由に変更可能
- エイリアスや互換レイヤーは不要。古いインタフェースは削除する
- 将来 public 化する際に API を固める

### テスト方針

- Slurm 依存部分はモック化 (実 HPC なしでテスト可能にする)
- TOML 読書きは fixtures ディレクトリのサンプルファイルを使用
- CLI テストは typer の CliRunner を使用
- Adapter / Launcher は抽象基底クラスの contract test を用意

### Git 管理

- run の大容量出力 (work/outputs/, work/restart/, work/tmp/) は .gitignore で除外
- テスト fixtures の TOML ファイルは Git 管理対象
- `gh release create` などで release を切るときは、先に `pyproject.toml` の `[project].version` を更新し、Git tag / release 名と同じバージョンに揃えること
- release の annotated tag message と GitHub Release 本文は日本語で書く
- release の `git commit` → `git tag -a` → `git push origin main` → `git push origin vX.Y.Z` は順に実行し、並列化しない
- Codex の個人用メモや一時 override は `AGENTS.override.md` に置き、Git 管理しない

## ビルド・実行

```bash
# 開発環境セットアップ
uv sync --dev

# テスト
uv run pytest

# Coverage (CI と同じ分岐込み floor)
uv run pytest --cov=runops --cov-branch --cov-report=term-missing --cov-fail-under=80

# Lint
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/

# 型チェック
uv run mypy src/

# CLI 実行 (開発中)
uv run runo --help
```

## 状態遷移

```
created → submitted → running → completed
created/submitted/running → failed
submitted/running → cancelled
completed → archived → purged
```

## Adapter 実装時の注意

新しい Simulator Adapter を追加する場合:
1. `src/runops/adapters/base.py` の `SimulatorAdapter` を継承
2. 全抽象メソッドを実装: render_inputs, resolve_runtime, build_program_command, detect_outputs, detect_status, summarize, collect_provenance
3. オプションメソッドの実装: parameter_schema, validate_params, required_outputs, knowledge_sources, agent_guide, case_template, doc_repos, pip_packages
4. `adapters/registry.py` に登録
5. `simulators.toml` に設定エントリを追加
6. テストを `tests/test_adapters/` に追加

## 知識層 (Knowledge Layer)

AI エージェントがシミュレーションを自律的に行うための知識管理。
詳細は `docs/knowledge-layer.md` を参照。

- **シミュレータ知識**: `refs/` + `.runops/knowledge/` (update-refs で更新)
- **外部共有知識**: `runops.toml` の `[knowledge]` に基づき外部ソースを接続し、必要に応じて `refs/knowledge/` 配下へ同期 (`knowledge source attach/sync` で管理)
- **実行環境**: `.runops/environment.toml` (doctor で自動検出)
- **研究意図**: `campaign.toml` (ユーザーが記述)
- **実験知見 (curated)**: `.runops/insights/` (knowledge save / knowledge source sync で管理)
- **構造化知識 (curated)**: `.runops/facts.toml` (knowledge add-fact / knowledge facts で管理)
- **lab notebook (chronological)**: `notes/YYYY-MM-DD.md` (`runo notes append` で時系列追記)、古い日次ノートは `notes/history/YYYY/YYYY-MM-DD.md`
- **長文レポート**: `notes/reports/<topic>.md` (改稿可)
- **研究判断の台帳**: `research/agenda.md` (現在の高レベルな研究判断。本文は日本語)

curated knowledge / lab notebook / research agenda は役割を分ける:

- `.runops/insights/` / `.runops/facts.toml` は整理済の永続知見 (上書き可・名前付き・atomic)
- `notes/YYYY-MM-DD.md` は append-only な時系列ログ。準備フェーズの意思決定・観察・仮説・TODO をその場で残し、古くなったら `notes/history/YYYY/` に archive する
- `research/agenda.md` は mutable な現在判断の正本。TODO ではなく、active question、current decision、paused/killed、判断が変わる条件を残す
- 価値が出てきたら `notes/reports/` で refined version を書き、さらに `.runops/insights/` / `facts.toml` に昇格

### 外部知識ソース

複数プロジェクト間で共有する知識を外部リポジトリとして管理し、project に接続できる。
`runops.toml` の `[knowledge]` セクションで設定する。

```bash
# 外部知識ソースの接続
runo knowledge source attach git shared-kb git@github.com:lab/hpc-shared-knowledge.git
runo knowledge source attach path local-kb ../hpc-knowledge

# 同期・レンダリング
runo knowledge source sync
runo knowledge source render

# 状態確認
runo knowledge source status
runo knowledge source list
```

`runo init` 時に GitHub の `*shared_knowledge*` リポジトリを自動検索し、対話的に接続できる。
`runo setup` 時は `runops.toml` に設定された知識ソースを自動同期する。

主要コマンド:
- `runo update-refs` — refs/ リポジトリ更新 + ナレッジインデックス再生成
- `runo knowledge source attach/detach/sync/render/status` — 外部知識ソース管理
- `runo knowledge save/list/show` — Markdown 知見の管理
- `runo knowledge add-fact/facts` — 構造化知識の管理
- `runo doctor` — 環境検出・保存
