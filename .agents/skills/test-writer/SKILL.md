---
name: test-writer
description: "Use when writing or updating runops tests after implementation or bug fixes, including application services, core contracts, CLI, adapters, launchers, Slurm, MCP, and harness drift."
---

# Test writing

behavior/schema の正本は `SPEC.md`、command surface は `.codex/rules/commands.md`、
test boundary は `.codex/rules/architecture.md` を読む。実装の現在挙動を無条件に正解と
せず、仕様と regression intent を先に固定する。

## Placement

- `tests/test_core/`: domain/state/parsing・runtime contract と禁止 import。
- `tests/test_application/`: use case、plan/apply、port injection、non-mutation。
- `tests/test_cli/`: CliRunner の help / exit / rendering。domain rule は重複検査しない。
- `tests/test_mcp/`: envelope、facade、registry、CLI/application parity。
- `tests/test_adapters/`, `test_launchers/`, `test_slurm/`: contract と injected runner。
- `tests/test_harness/`: generated/development guidance drift。

## Rules

- happy path に加え invalid input、missing/corrupt file、stale plan、external failure、
  unknown-field preservation、no-clobber/concurrency を対象リスクに応じて扱う。
- filesystem は `tmp_path`、時刻・command・network・Slurm は injection/fake を使う。
- login node で Python test を直接実行せず、KUDPC では compute allocation を使う。
- assertion を弱めて通さない。RED を記録してから最小実装で GREEN にする。
- patch は dependency を所有する implementation module に当てる。

対象 pytest の後に Ruff format/check、必要な mypy、広い regression suite を実行し、
実行 command・pass count・未検証範囲を報告する。
