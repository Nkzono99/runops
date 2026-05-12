---
name: setup-env
description: Set up or repair the project Python environment. Use when initializing a project or fixing environment issues.
---

# プロジェクト環境のセットアップ

## 方法 1: ブートストラップ (新規プロジェクト)

```bash
uvx --from runops runo init
source .venv/bin/activate
runo doctor
```

## 方法 2: 手動セットアップ (既存プロジェクト)

```bash
uv venv .venv
uv pip install runops --python .venv/bin/python
{{ pip_install_line }}
source .venv/bin/activate
runo doctor
```

## 注意

- `.venv/` は `.gitignore` に追加済み
- HPC ノードでは login ノードで環境構築し、compute ノードでは同じ `.venv` を使う
- `module load` が必要なモジュールは `simulators.toml` の `modules` に定義済み
- runops 更新: `uv pip install --upgrade runops --python .venv/bin/python`
