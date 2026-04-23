# CLAUDE.md — runops

## プロジェクト概要

HPC 環境における Slurm ベースのシミュレーション実行管理 CLI ツール。
run ディレクトリを日常運用の主単位とし、パラメータサーベイ展開・job 投入・状態追跡・provenance 記録・解析補助を一貫して管理する。

仕様書: `SPEC.md`

## コミュニケーション

- **日本語で応答する**。コード・コマンド・変数名・エラーメッセージは英語のまま
- commit message は英語 (`fix:`, `feat:`, `refactor:`, `test:`, `docs:`)
- Agent 向けドキュメント (rules, skills, agents) は日本語で書いてよい

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

`runo init` が `.venv/` と `tools/runops/` を自動構築し、editable install する。

## 技術スタック

- Python 3.10+ / uv (pyproject.toml) / typer (click ベース)
- TOML (tomli / tomli-w) / pytest / ruff / mypy (strict)

## ディレクトリ構成

```
src/runops/
  cli/           # CLI エントリポイント (typer) — 薄い層
  core/          # ドメインロジック (CLI / Slurm に依存しない)
  adapters/      # Simulator Adapter (抽象基底 + registry)
  launchers/     # Launcher Profile (srun / mpirun / mpiexec)
  jobgen/        # job.sh 生成
  slurm/         # Slurm 連携 (sbatch / squeue / sacct)
  sites/         # bundled site preset
  harness/       # Agent harness 定義
  templates/     # project / case / survey 用 静的テンプレート
tests/
  test_core/ test_cli/ test_adapters/ test_launchers/ test_slurm/
  fixtures/      # テスト用 TOML ファイル等
```

## ビルド・実行

```bash
uv sync --dev                              # 開発環境セットアップ
uv run pytest                              # テスト
uv run ruff check src/ tests/              # Lint
uv run ruff format --check src/ tests/     # Format check
uv run mypy src/                           # 型チェック
uv run runo --help                       # CLI 実行
```

## 設計原則

- **run ディレクトリが主単位**: すべての操作は run_id / run dir を基点とする
- **manifest.toml が正本**: run の状態・由来・provenance はすべて manifest.toml に記録
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

**現在は private リポジトリ**のため、後方互換性は気にしなくてよい。
コマンド名・引数・ファイル形式は自由に変更可能。エイリアスや互換レイヤーは不要。

## 主要コマンド (抜粋)

| コマンド | 説明 |
|---------|------|
| `runo init` / `setup` / `doctor` | プロジェクト管理 |
| `runo case new` / `runs create` / `runs sweep` | case / run 生成 |
| `runo runs submit [--all] [-qn] [--qos]` | ジョブ投入 |
| `runo runs status` / `sync` / `log` / `dashboard` | モニタリング |
| `runo analyze summarize` / `collect` | 解析 |
| `runo notes append` / `knowledge save` | 知見管理 |
| `runo runs archive` / `purge-work` / `cancel` / `delete` | ライフサイクル |

全コマンド一覧: `.claude/rules/commands.md`

## 開発ルール

詳細は `.claude/rules/dev-workflow.md` を参照。

- ruff format / ruff check / mypy strict / テストカバレッジ 80%+
- docstring は Google style
- テスト: Slurm はモック、TOML は fixtures、CLI は CliRunner
- Git: 1 コミット = 1 論理変更、`--no-verify` / `--force` 禁止
- release 時は `pyproject.toml` + `__init__.py` の version を同時に更新

## Adapter 実装時の注意

1. `adapters/base.py` の `SimulatorAdapter` を継承
2. 全抽象メソッドを実装 + オプションメソッド
3. `adapters/registry.py` に登録 → `simulators.toml` にエントリ追加
4. テストを `tests/test_adapters/` に追加

## 知識層

詳細は `.claude/rules/knowledge-layer.md` を参照。
