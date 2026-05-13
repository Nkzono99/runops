---
name: setup-env
description: Set up or repair the project Python environment. Use when initializing a project or fixing environment issues.
---

# プロジェクト環境のセットアップ

## 方法 1: ブートストラップ (新規プロジェクト)

```bash
uvx --from runops runo init
uvx --from runops runo doctor
```

## 方法 2: 手動セットアップ (既存プロジェクト)

```bash
uv venv .venv
{{ pip_install_line }}
uvx --from runops runo doctor
```

runops CLI を project `.venv` に固定したい offline / pinned workflow だけ、
明示的にインストールする:

```bash
uv pip install runops --python .venv/bin/python
.venv/bin/runo doctor
```

Windows では `.venv\Scripts\runo.exe doctor` に読み替える。

## 注意

- `.venv/` は `.gitignore` に追加済み
- HPC ノードでは login ノードで環境構築し、compute ノードでは同じ `.venv` を使う
- `module load` が必要なモジュールは `simulators.toml` の `modules` に定義済み
- runops 更新: `{{ skill_prefix }}update-runops` または
  `uvx --from runops runo update-harness`
