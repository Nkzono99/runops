---
name: implement-core
description: "Use when implementing or modifying domain/state/parsing or runtime contracts under src/runops/core/: project/case/survey/run/manifest/state/provenance/discovery contracts and core boundary tests."
---

# Core domain implementation

`src/runops/core/` の domain/state/parsing と runtime contract を実装・修正する。仕様の正本は
[`SPEC.md`](../../../SPEC.md)、現行 CLI 名の正本は
[`.codex/rules/commands.md`](../../../.codex/rules/commands.md) である。古い agent
example や記憶から schema / command を推測しない。

## 責務と境界

- project / case / survey / run identity、manifest、state、discovery を扱う。
- `core/` から `application/`, `cli/`, `mcp/`, `slurm/`, `adapters/`, `harness/`
  を import しない。
- workflow orchestration、外部 command、prompt / rendering は core に置かない。
- filesystem value object は `Path`、domain value は型付き frozen dataclass を優先する。
- manifest の既知 field を更新しても未知 top-level / section field を保持する。

現在の run_id は `RYYYYMMDD-NNNN`。manifest は `[run]` の `id` / `status` と
`params_snapshot` 等を持つが、完全な schema は必ず `SPEC.md` を読む。別 table の
古いサンプルを複製しない。

状態遷移:

```text
created -> submitted -> running -> completed
created/submitted/running -> failed
submitted/running -> cancelled
completed -> archived -> purged
archived -> completed (restore)
```

## Workflow

1. `SPEC.md`、`.codex/rules/architecture.md`、対象 source/test を読む。
2. 失敗 test を先に追加し、boundary と lossless behavior を含める。
3. domain/runtime contract と domain-specific error を実装する。
4. `$test-module` または対象 pytest、mypy strict、Ruff format/check を実行する。
5. state/schema/CLI まで変わる場合は `SPEC.md` と canonical docs の更新を依頼する。

完了前に public type annotation、error path、invalid TOML、duplicate run_id、禁止 import
が検証されていることを確認する。
