---
name: setup-env
description: Use when the requested outcome is a healthy or repaired project runtime environment verified by runo doctor.
---

# project runtimeを利用可能にする

## 実行契約

- **Goal**: 指定projectのPython / simulator runtimeをdoctor可能な状態にする
- **Done**: 選択したruntime経路、導入package、`runo doctor`結果を報告できる
- **Budget**: 一つのproject環境と、診断で不足が確認されたdependencyだけ
- **Invariant**: runops CLIは原則`uvx`、`.venv`はproject runtimeに使い、無関係なpackageを更新しない

## Environment routing

| state | route |
|---|---|
| project未作成 | `uvx --from runops runo init` |
| 既存projectのruntime不足 | `uv venv .venv` → `{{ pip_install_line }}` |
| offline / pinned CLI | `uv pip install runops --python .venv/bin/python` |

選んだrouteの後に`uvx --from runops runo doctor`を一度実行する。Windowsのpinned CLIは
`.venv\Scripts\runo.exe`を使う。

- `.venv/`はGit管理しない
- HPC moduleは`simulators.toml`の`modules`をsourceにする
- runops / harness更新は`{{ skill_prefix }}update-runops`の別Goalとして扱う
