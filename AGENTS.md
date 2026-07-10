# AGENTS.md - runops

## 入口

このファイルは Codex が最初に読む短い案内である。詳細手順は
`.agents/skills/`、設計・運用リファレンスは `.codex/rules/*.md`、仕様は
`SPEC.md` に分ける。AGENTS.md は 150 行程度を上限目安に保ち、長い表や手順を
ここへ戻さない。

runops は HPC 環境における Slurm ベースのシミュレーション実行管理 CLI。
run ディレクトリを日常運用の主単位とし、パラメータサーベイ展開、job 投入、
状態追跡、provenance 記録、解析補助を一貫して管理する。

## コミュニケーション

- 日本語で応答する。コード、コマンド、変数名、エラーメッセージは英語のまま。
- commit message は英語 (`fix:`, `feat:`, `refactor:`, `test:`, `docs:`)。
- Agent 向けドキュメント (rules, skills, agents) は日本語で書いてよい。
- 個人用メモや一時 override は `AGENTS.override.md` に置き、Git 管理しない。

## 参照先

| 用途 | ファイル |
|---|---|
| 仕様 | `SPEC.md` |
| アーキテクチャ境界 | `.codex/rules/architecture.md` |
| 全コマンド一覧 | `.codex/rules/commands.md` |
| 品質ゲート / Git / release | `.codex/rules/dev-workflow.md` |
| よくあるミス | `.codex/rules/gotchas.md` |
| 知識層 | `.codex/rules/knowledge-layer.md` |
| 高コスト / 不可逆 command policy | `.codex/rules/runops.rules` |
| Codex 設定の読み込み | `.codex/README.md` |

## Codex ハーネス

このリポジトリは Claude Code 用の `.claude/` に加えて Codex 用の
`.codex/` と `.agents/skills/` を持つ。

| 目的 | Codex 側 | Claude 側 |
|---|---|---|
| Project doc | `AGENTS.md` | `CLAUDE.md` |
| 定型スキル | `.agents/skills/<name>/SKILL.md` | `.claude/skills/<name>/SKILL.md` |
| 専門 agent 由来の知識 | `.agents/skills/<name>/SKILL.md` | `.claude/agents/<name>.md` |
| 実行設定 | `.codex/config.toml` | `.claude/settings.json` |
| command policy | `.codex/rules/runops.rules` | `.claude/settings.json` permissions |
| リファレンス | `.codex/rules/*.md` | `.claude/rules/*.md` |

Codex ではスキルを `$check`, `$release`, `$implement-core` のように `$` 付きで呼ぶ。
Codex の project-local config は、この repo を trusted project として登録したときに読む。

shared な運用変更を入れたら `AGENTS.md`, `CLAUDE.md`,
`.agents/skills/*`, `.claude/skills/*`, `.codex/rules/*`,
`.claude/rules/*` の意図的でない drift を点検する。

## 開発環境

- このリポジトリでの作業は repo root の `.venv` を使い、原則 `uv run <command>` で実行する。
- runops project を使う側では `uvx --from runops runo ...` を標準経路にする。
- CLI 名は `runo` を優先する。`runops` は互換 alias として残す。
- 技術スタックは Python 3.10+ / uv / Typer / TOML / pytest / ruff / mypy strict。

## HarnessOps 導線

HarnessOps CLI (`hops`) は `.venv` に常駐 install せず、`uvx --from harnessops hops ...` で実行する。
診断は `$hops-diagnose` または `uvx --from harnessops hops doctor --check-overlay --check-records`。
ハーネス摩擦や上流改善候補は `$harnessops-bridge` / `$hops-add-failure` で記録し、lab 評価は `$hops-run-lab`、更新は `$hops-update-harness` を使う。
この checkout の upstream lab overlay は repo 外の `../runops-harness-lab` に置く。
repo 内 `harness-lab/` は再作成・Git 管理しない。
`.harnessops/`, `harness-feedback/`, HarnessOps overlay は手で組み替えず、更新は `uvx --refresh-package harnessops --from harnessops hops update-harness ...` に委譲する。

## 主要ディレクトリ

```text
src/runops/
  cli/        Typer entrypoints。薄い層に保つ
  core/       domain/state/parsing と runtime contract。禁止 import 境界を守る
  application/ use case / orchestration / port
  adapters/   Simulator Adapter
  launchers/  Launcher Profile
  jobgen/     job.sh 生成
  slurm/      sbatch / squeue / sacct 連携
  mcp/        Ops MCP provider
  harness/    project 側 harness 生成 / 更新
  templates/  project / case / survey 用テンプレート
tests/
  test_core/ test_application/ test_cli/ test_mcp/ test_adapters/ test_launchers/ test_slurm/
```

## ビルドと検証

```bash
uv sync --dev
uv run runo --help
uv run ruff format --check src/ tests/
uv run ruff check src/ tests/
uv run mypy src/
uv run pytest
uv run pytest --cov=runops --cov-branch --cov-report=term-missing --cov-fail-under=80
```

コードを変えたら、対象範囲に応じて `$check` または `$test-module` を使う。
CLI の詳細は `.codex/rules/commands.md` を参照し、コマンド追加・変更時は
そちらを正本として更新する。

## 設計原則

- run ディレクトリが主単位。すべての操作は run_id または run dir を基点にする。
- run_id は不変、パスは分類・整理用に可変。
- `manifest.toml` が正本。状態・由来・provenance は manifest に記録する。
- CLI / MCP は薄くし、workflow は `application/`、domain/state/parsing と
  runtime contract は `core/` に置く。
- simulator 固有処理は Adapter、MPI 起動方式は Launcher に閉じ込める。
- Python ツールは MPI rank ごとのラッパにならない。job.sh で srun/mpirun を直接実行する。
- 全コマンドはカレントディレクトリをデフォルトターゲットとする。

状態遷移:

```text
created -> submitted -> running -> completed
created/submitted/running -> failed
submitted/running -> cancelled
completed -> archived -> purged
```

## 実装時の入口

core は `$implement-core`、CLI は `$implement-cli`、Slurm は `$implement-slurm`、
Launcher / job.sh は `$implement-launcher`、Simulator Adapter は `$implement-adapter`。
テスト追加は `$test-writer`、仕様準拠レビューは `$spec-reviewer`、
ハーネス改善は `$improve-harness`、ドキュメント反映は `$update-docs` を使う。

## 後方互換性と Git

現在は private / v0 系のため、後方互換性は強く維持しなくてよい。
project-state に影響する breaking change は `docs/migrations/v0.md` に移行方法を残す。

現在は個人開発のため main-first で進める。通常作業は `main` で行い、
品質ゲートを通してから `origin/main` へ fast-forward / direct push する。
大きな設計レビューや共同作業が必要な変更だけ branch / PR に分ける。
`--force`、non-fast-forward push、`--no-verify` は使わない。
release は `$release` を使い、`pyproject.toml` と `src/runops/__init__.py` の version を
同時に更新する。annotated tag message と GitHub Release 本文は日本語で書く。

## 知識層

AI エージェント向けの知識管理は `.codex/rules/knowledge-layer.md` と
`docs/layers/knowledge.md` を参照する。`research/agenda.md` は mutable な現在判断の
台帳であり、TODO 置き場ではない。
