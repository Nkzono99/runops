# CLAUDE.md — runops

## プロジェクト概要

HPC 環境における Slurm ベースのシミュレーション実行管理 CLI ツール。
run ディレクトリを日常運用の主単位とし、パラメータサーベイ展開・job 投入・状態追跡・provenance 記録・解析補助を一貫して管理する。

仕様書: `SPEC.md`

## コミュニケーション

- **日本語で応答する**。コード・コマンド・変数名・エラーメッセージは英語のまま
- commit message は英語 (`fix:`, `feat:`, `refactor:`, `test:`, `docs:`)
- Agent 向けドキュメント (rules, skills, agents) は日本語で書いてよい

## 開発ハーネス対応

runops の開発ハーネスは `.claude/` だけではなく、`.codex/` と
`.agents/skills/` も含む。ハーネス改善時は次を意識すること:

- Claude 固有設定は `.claude/`、Codex 固有設定は `.codex/` に置く
- 共通ワークフローや運用知識は、tool 固有の文法差を除いて意図的な差分だけを残す
- shared な運用変更を入れたら `AGENTS.md`, `CLAUDE.md`,
  `.claude/skills/improve-harness/SKILL.md`, `.agents/skills/improve-harness/SKILL.md`,
  `.claude/skills/release/SKILL.md`, `.agents/skills/release/SKILL.md`,
  `.claude/rules/dev-workflow.md`, `.codex/rules/dev-workflow.md`,
  `.claude/rules/gotchas.md`, `.codex/rules/gotchas.md` の drift を点検する

## プロジェクトでの利用方法

CLI は `runo` を標準コマンドとして使う。既存スクリプトとの互換性のため、
`runops` も同じ CLI を指す stable alias として残す。

```bash
# 新規プロジェクト作成
mkdir my-project && cd my-project
uvx --from runops runo init
source .venv/bin/activate && runo doctor

# 既存プロジェクトを clone + セットアップ
uvx --from runops runo setup https://github.com/user/my-project.git
source my-project/.venv/bin/activate && runo doctor
```

`runo init` が `.venv/` を自動構築し、runops を通常 package install する。

## 技術スタック

- Python 3.10+ / uv (pyproject.toml) / typer (click ベース)
- TOML (tomli / tomli-w) / pytest / ruff / mypy (strict)

## ディレクトリ構成

```
src/runops/
  cli/           # CLI エントリポイント (typer) — 薄い層
    init/        # runo init / doctor / scaffold / bootstrap
    knowledge/   # runo knowledge / knowledge source
    mcp.py       # runo mcp serve / check / tools
  core/          # ドメインロジック (CLI / Slurm に依存しない)
  adapters/      # Simulator Adapter (抽象基底 + registry)
  launchers/     # Launcher Profile (srun / mpirun / mpiexec)
  jobgen/        # job.sh 生成
  slurm/         # Slurm 連携 (sbatch / squeue / sacct)
  mcp/           # Ops MCP provider (FastMCP / envelope / registry)
  sites/         # bundled site preset
  harness/       # project 側 harness 生成 / 更新 (builder / claude / codex)
  templates/     # project / case / survey 用 静的テンプレート
tests/
  test_core/ test_cli/ test_adapters/ test_launchers/ test_slurm/
  fixtures/      # テスト用 TOML ファイル等
```

## ビルド・実行

```bash
uv sync --dev                              # 開発環境セットアップ
uv run pytest                              # テスト
uv run pytest --cov=runops --cov-branch --cov-report=term-missing --cov-fail-under=80  # Coverage
uv run ruff check src/ tests/              # Lint
uv run ruff format --check src/ tests/     # Format check
uv run mypy src/                           # 型チェック
uv run runo --help                       # CLI 実行
```

## 設計原則

- **run ディレクトリが主単位**: すべての操作は run_id / run dir を基点とする
- **manifest.toml が正本**: run の状態・由来・provenance はすべて manifest.toml に記録
- **研究判断の隔離**: 生成 project の `research/agenda.md` は mutable な現在判断の台帳。本文は日本語
- **Simulator Adapter パターン**: simulator 固有処理は Adapter に閉じ込める
- **Launcher Profile パターン**: MPI 起動方式は Launcher に閉じ込める
- **MPI に介入しない**: Python ツールは rank ごとのラッパにならない
- **cwd ベース**: 全コマンドはカレントディレクトリをデフォルトターゲット

詳細は `.claude/rules/architecture.md` を参照。

## 状態遷移

```
created → submitted → running → completed
created/submitted/running → failed
submitted/running → cancelled
completed → archived → purged
```

## 後方互換性

**現在は private / v0 系**のため、後方互換性は強く維持しなくてよい。
コマンド名・引数・ファイル形式は自由に変更可能。エイリアスや互換レイヤーは原則不要。
project-state に影響する breaking change は `docs/migrations/v0.md` に移行方法を残す。
将来 v1 で public 化する際に CLI / project schema / manifest / analysis artifact schema を固める。

## 主要コマンド (抜粋)

| コマンド | 説明 |
|---------|------|
| `runo --version` | version 確認 |
| `runo init` / `setup` / `doctor` | プロジェクト管理 |
| `runo context --json` / `runo lint` | project context と health check |
| `runo mcp serve` / `mcp check` / `mcp tools --json` | MCP provider の起動・検査 |
| `runo migrate list/show/apply` | project-state migration |
| `runo case new` / `runs create` / `runs sweep` | case / run 生成 |
| `runo runs submit [--all] [-qn] [--qos] [--afterok] [--yes]` | ジョブ投入 (`--all` は確認付き、`--yes` で省略) |
| `runo runs status` / `sync` / `log` / `dashboard` | モニタリング |
| `runo analyze summarize` / `collect` / `plot` / `export` / `new-comparison` | 解析 |
| `runo notes append` / `notes archive` / `knowledge save` | 知見管理 |
| `runo runs archive` / `purge-work` / `cancel` / `delete` | ライフサイクル |

全コマンド一覧: `.claude/rules/commands.md`

## 開発ルール

詳細は `.claude/rules/dev-workflow.md` を参照。

- ruff format / ruff check / mypy strict / テストカバレッジ 80%+
- docstring は Google style
- テスト: Slurm はモック、TOML は fixtures、CLI は CliRunner
- Git: 1 コミット = 1 論理変更、`--no-verify` / `--force` 禁止
- release 時は `pyproject.toml` + `__init__.py` の version を同時に更新し、annotated tag / GitHub Release は日本語で書く

## Adapter 実装時の注意

1. `adapters/base.py` の `SimulatorAdapter` を継承
2. 全抽象メソッドを実装 + `required_outputs` などのオプションメソッド
3. `adapters/registry.py` に登録 → `simulators.toml` にエントリ追加
4. テストを `tests/test_adapters/` に追加

## 知識層

詳細は `.claude/rules/knowledge-layer.md` を参照。
