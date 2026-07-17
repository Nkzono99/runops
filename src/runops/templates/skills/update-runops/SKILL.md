---
name: update-runops
description: Use when the requested outcome is a specific runops tool, project harness, or simulator-package update.
---

# requested update surfaceだけを更新する

## 実行契約

- **Goal**: 指定version / surfaceをcurrent projectで利用可能にする
- **Done**: before / after version、適用chain、`.new` conflict、migration候補、validationを報告できる
- **Budget**: 一つのtarget versionと明示されたtool / harness / simulator surfaceだけ
- **Invariant**: `uvx`を標準CLIとし、edited fileとlocal checkoutを保護し、project-state migrationを推測しない

## Goal routing

| requested surface | route |
|---|---|
| runops CLI version確認 | `uvx --from runops runo --version` |
| exact version | `uvx --from "runops==<version>" runo --version` |
| generated harness | `runo update-harness --plan` → `--apply-chain` |
| project-state migration | `{{ skill_prefix }}migrate-runops` |
| simulator package | `runo update` |
| runops local patch | `{{ skill_prefix }}patch-runops` |

project `.venv`へのrunops常駐はoffline / pinned workflowで明示された場合だけ
`uv pip install "runops==<version>" --python .venv/bin/python`を使う。

## Harness route

```bash
uvx --from runops runo update-harness --plan
uvx --from runops runo update-harness --apply-chain
```

chainは`.runops/harness.lock`のapplied versionからexact-version checkpointを選ぶ。未編集fileと
不足scaffoldは更新し、user editは`<path>.new`として保持する。`.new`があればdiffを報告し、
自動mergeしない。実行中packageがtemplate / knowledgeのsourceであり、source checkoutをpullしない。

## Adjacent routes

`runo migrate list`で候補だけを確認し、migration適用が現在のGoalに含まれなければ次のGoalとして返す。
`runo update`はsimulator package更新が明示された場合だけ使い、editable installを置換する変更は
対象と影響を示してcheckpointを得る。

```bash
uvx --from runops runo doctor
uvx --from runops runo lint
```

選択surfaceのvalidationでDoneを返し、他surfaceを一括更新しない。
