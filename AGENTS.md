# AGENTS.md - runops

runops v2 の開発者向け入口。仕様と決定事項は [SPEC.md](SPEC.md)、利用者向けは
[README.md](README.md) と [docs/](docs/)。

## コミュニケーション

- 日本語で応答する。コード、コマンド、変数名、エラーメッセージは英語のまま。
- commit message は英語（`fix:`, `feat:`, `refactor:`, `test:`, `docs:`）。

## 規約（正本は `.claude/rules/`。Codex もここを読む）

| 内容 | ファイル |
|---|---|
| 層、不変条件、filesystem と adapter の扱い | [.claude/rules/architecture.md](.claude/rules/architecture.md) |
| 品質ゲート、コーディング、テスト、Git、リリース | [.claude/rules/dev-workflow.md](.claude/rules/dev-workflow.md) |
| Lustre、metadata cache、typer、v1 project の扱い | [.claude/rules/gotchas.md](.claude/rules/gotchas.md) |

## skill（正本は `.agents/skills/`）

| skill | 使う場面 |
|---|---|
| `check` | コード変更後の品質ゲートと、変更内容に応じた追加確認 |
| `sync-docs` | command、設定、manifest、adapter 契約を変えたとき |
| `spec-reviewer` | 大きな変更をマージする前の SPEC 準拠レビュー |
| `simulator-adapter` | simulator の package 側に adapter と skill 同梱を足す・直す |
| `improve-harness` | この開発ハーネスか、project に生成するハーネスを直す |
| `release` | version を上げて PyPI に公開する |
| `python-package-refactor` | package 構成や依存境界を整理する |

## 開発

```bash
uv sync --dev
uv run pytest -q                    # 60 秒以内。Slurm は全て mock
uv run ruff format --check src/ tests/ && uv run ruff check src/ tests/
uv run mypy src/
```

## 構成

```text
src/runops/
  cli.py        Typer。入力、確認、表示だけ
  ops/          command ごとの処理（create, submit, sync, listing, tidy, notes, setup, skills, migrate）
  config.py project.py manifest.py case.py runtime.py jobgen.py launchers.py slurm.py util.py
  adapters/     契約（Protocol）、解決順、generic
  legacy_adapters/  v1 emses / beach の移植（migrate-v1 と init 用）
  skills/       project に展開する runops skill（各 60 行以内）
  harness.py    project の AGENTS.md 管理 block
tests/          受け入れ基準（SPEC §13.2）ごとのテスト、golden/、fixtures/v1-project/
```

## 守ること

- 名詞は case / run / sweep。新しい永続 entity や ID 空間、作成前のゲートを足さない（SPEC §1.2）。
- simulator 固有の知識を runops に置かない。adapter と skill は simulator package 側。
- 利用者が覚えるコマンドは `runo init` だけ。それ以外はエージェントへの依頼で行える形に保つ。
- 実運用の v1 project には `runo migrate-v1 --dry-run` 以外を実行しない。
