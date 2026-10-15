# 開発ワークフロー

## 品質ゲート

コミット前に `check` skill の手順を通す。CI（`.github/workflows/ci.yml`）も同じ
ruff format / ruff check / mypy / pytest（branch coverage 80%）を Python 3.10–3.13 で実行する。

## コーディング

- Python 3.10+。`tomllib` は `runops.util.tomllib` を使う（3.10 は `tomli`）。
- 型ヒントを付ける（mypy は `disallow_untyped_defs`）。line length 100。
- 新しい command / option / field は先に `SPEC.md` を更新し、`sync-docs` skill の表に沿って
  文書と skill を揃える。command は合計 25 を超えない。
- 新しい永続 entity、ID 空間、ledger、作成前のゲートを足さない（SPEC §1.2）。

## テスト

- 受け入れ基準（SPEC §13.2）ごとにテストがある。挙動を変えたら対応するテストを直す。
- CLI は `tests/conftest.py` の `cli` fixture（`runops.cli.main` を呼び exit code と出力を返す）、
  Slurm は `fake_slurm`、project は `project_dir`（generic simulator と `demo` case）を使う。
- job.sh は `tests/golden/`、v1 移行は `tests/fixtures/v1-project/` を使う。
- 実際の Slurm、ネットワーク、計算ノードを必要とするテストを書かない。

## Git

- 1 コミット 1 論理変更。message は英語の Conventional Commits（`feat:`, `fix:`, `docs:` ...）。
- main-first。大きな変更だけ branch を切る。`--no-verify`、`--force`、`git reset --hard` は使わない。
- コミットや push はユーザーの依頼があるときだけ行う。

## リリース

`release` skill に従う。`pyproject.toml` と `src/runops/__init__.py` の version を同時に更新する。
