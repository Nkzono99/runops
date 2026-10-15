# AGENTS.md - runops

runops v2 の開発者向け入口。仕様と決定事項は [SPEC.md](SPEC.md)、利用者向けは
[README.md](README.md) と [docs/](docs/)。

## コミュニケーション

- 日本語で応答する。コード、コマンド、変数名、エラーメッセージは英語のまま。
- commit message は英語（`fix:`, `feat:`, `refactor:`, `test:`, `docs:`）。

## 開発

```bash
uv sync --dev
uv run pytest                       # 60 秒以内。Slurm は全て mock
uv run ruff format --check src/ tests/ && uv run ruff check src/ tests/
uv run mypy src/
uv run pytest --cov=runops --cov-branch --cov-fail-under=80
```

KUDPC の LARGE0/LARGE1（Lustre）は `RENAME_NOREPLACE` に未対応。filesystem に触る変更は
`uv run pytest --basetemp=/LARGE0/.../tmp-dir` でも確認する。

## 構成

```text
src/runops/
  cli.py        Typer。入力、確認、表示だけ
  ops/          command ごとの処理（create, submit, sync, listing, tidy, notes, setup, skills, migrate）
  config.py project.py manifest.py case.py runtime.py jobgen.py launchers.py slurm.py util.py
  adapters/     契約（Protocol）、解決順、generic
  legacy_adapters/  v1 emses / beach の移植（migrate-v1 用）
  skills/       project に展開する runops skill（各 60 行以内）
  harness.py    project の AGENTS.md 管理 block
tests/          受け入れ基準（SPEC §13.2）ごとのテスト、fixtures/v1-project
```

## 守ること

- 名詞は case / run / sweep。新しい永続 entity や ID 空間を足さない（SPEC §1.2）。
- 作成をゲートしない。記録し、一覧で見せ、`tidy` で提案する。
- simulator 固有の知識を runops に置かない。adapter と skill は simulator package 側。
- `ops/` は print / prompt をしない。Slurm 呼び出しは runner 引数で注入する。
- command を増やすときは SPEC §7.3 と §13.1 の上限（25）を確認し、SPEC を先に更新する。
- project 側の AGENTS.md block を変えたら 120 行以内を保つ（テストあり）。

`.claude/`、`.codex/`、`.agents/skills/` の開発ハーネスは v1 の構成を前提に書かれており、
v2 に合わせた見直しが未了。
