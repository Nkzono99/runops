---
name: implement-cli
description: "Use when implementing or modifying Typer entry points under src/runops/cli/, including grouped commands, options, application-service wiring, rendering, and CliRunner tests."
---

# CLI implementation

CLI は薄い interface である。command surface の正本は
`.codex/rules/commands.md`、behavior/schema の正本は `SPEC.md`、境界は
`.codex/rules/architecture.md` を読む。

## Current contract

- preferred executable は `runo`、`runops` は alias。
- grouped command が現行 v0 surface。例: `runo runs submit [RUN]`、
  `runo analyze collect [DIR]`。
- CLI は Typer input、prompt、exit code、表示だけを所有する。
- workflow は `application/` の use case/action、外部 I/O は port/infrastructure に委譲する。
- dry-run / MCP / actual execution が同じ plan を使う場合、CLI で規則を再実装しない。
- 確認省略は `--yes` を canonical とする。残す `--force` alias は同一 semantics の
  hidden compatibility option に限る。

## Workflow

1. `src/runops/cli/main.py`、対象 command、application contract、既存 test を読む。
2. CliRunner で help、success、error、non-mutation の失敗 test を先に書く。
3. `Annotated` option/argument を使い、domain/application error を明示的な exit に変換する。
4. command を登録し、CLI function を parse -> call -> render の短い構造に保つ。
5. 対象 pytest、mypy、Ruff format/check を実行する。
6. command/option を変えたら `.codex/rules/commands.md` と必要な migration note を更新する。

CLI test で subprocess/Slurm を実行しない。patch は facade ではなく dependency を所有する
implementation module に当てる。
