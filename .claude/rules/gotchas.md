# Gotchas (よくあるミス)

## Circular imports

`cli/init/workflow.py` は harness の plugin recommendation helper を使う。
harness 側から `cli/init/command.py` や `workflow.py` を import するとループするため、
harness は templates と adapters.registry を依存の入口にする。

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

## settings.json と settings.local.json

- `.claude/settings.json` — Git 管理。チーム共有の permissions / model
- `.claude/settings.local.json` — .gitignore 済。個人の許可パターン

local が team を **マージ上書き** する。同じキーを両方に書くと local が勝つ。

## Adapter の pip_packages / doc_repos

Adapter が返すリストは **累積** (重複排除) される。
同じ package を複数 adapter が返しても 1 回だけ install される。

## バージョン二重管理

`pyproject.toml` の `version` と `src/runops/__init__.py` の `__version__` は
**必ず同時に更新する**。片方だけ変えるとランタイム (`runops --version`) と
PyPI パッケージのバージョンがずれる。`/release` スキルを使えば自動で両方更新される。

## release の commit / tag 順序

release commit は `main` 上で作り、`git push origin main` 後に CI green を確認する。
tag はその `main` の release commit に `git tag -a` で付ける。

tag 作成と `git push origin vX.Y.Z` を並列に走らせると、tag が古い commit を指したまま
publish されることがある。

## read_text() の encoding

`Path.read_text()` は `encoding` 引数を省略するとシステムロケール依存になる。
日本語を含むファイルを読むときは必ず `encoding="utf-8"` を明示する。

## ハーネス lock

`harness.lock` は **テンプレートの hash** を記録する。
ファイルの hash ではない。比較は「disk hash == lock hash」→ unedited。
lock がない旧プロジェクトでは全ファイルが "edited" 扱いになる。
