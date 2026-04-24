# Gotchas (よくあるミス)

## Circular imports

`harness/builder.py` が `cli/init/command.py` を import するとループする。
harness は templates と adapters.registry にだけ依存する。
`cli/init/command.py` が harness/builder を import する方向は OK。

## `_write_if_missing` のセマンティクス

`_write_if_missing` は **ファイルが存在しなければ書く**。
既存ファイルは一切上書きしない。テストでファイル上書きを期待すると失敗する。

## load_static vs get_jinja_env

- `load_static("path")` — そのまま返す (変数展開なし)
- `get_jinja_env().get_template("path")` — Jinja2 レンダリングが必要な場合

テンプレートに `{{` が含まれないなら `load_static` で十分。

## tomllib vs tomli

Python 3.11+ は `tomllib` が標準。3.10 では `tomli` を使う。
ファイル先頭の `sys.version_info` 分岐を踏襲すること。

## python vs python3

この環境では `python` コマンドが無いことがある。
ワンライナーや検証には `uv run python` か `python3` を使う。

## Claude / Codex settings

- `.claude/settings.json` — Git 管理。チーム共有の permissions / model
- `.claude/settings.local.json` — .gitignore 済。個人の許可パターン
- `.codex/config.toml` — Git 管理。Codex の project-local config
- `.codex/rules/runops.rules` — Git 管理。高リスク command の policy

Claude Code では local が team を **マージ上書き** する。同じキーを両方に書くと
local が勝つ。Codex の個人用メモや一時 override は `AGENTS.override.md` に置く。

## Adapter の pip_packages / doc_repos

Adapter が返すリストは **累積** (重複排除) される。
同じ package を複数 adapter が返しても 1 回だけ install される。

## バージョン二重管理

`pyproject.toml` の `version` と `src/runops/__init__.py` の `__version__` は
**必ず同時に更新する**。片方だけ変えるとランタイム (`runo --version`) と
PyPI パッケージのバージョンがずれる。`$release` スキルを使えば自動で両方更新される。

## release の commit / tag 順序

release では `git commit` の完了を待ってから `git tag -a` を切る。
commit と tag を並列に走らせると、tag が 1 つ前の commit を指したまま push されることがある。
push も `main` と tag を順に実行する。

## read_text() の encoding

`Path.read_text()` は `encoding` 引数を省略するとシステムロケール依存になる。
日本語を含むファイルを読むときは必ず `encoding="utf-8"` を明示する。

## ハーネス lock

`harness.lock` は **テンプレートの hash** を記録する。
ファイルの hash ではない。比較は「disk hash == lock hash」→ unedited。
lock がない旧プロジェクトでは全ファイルが "edited" 扱いになる。
