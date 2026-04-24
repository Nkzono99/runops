# 開発ワークフロー

## 品質ゲート

コードを変更したら、コミット前に以下を通すこと:

```bash
uv run ruff format --check src/ tests/
uv run ruff check src/ tests/
uv run mypy src/
uv run pytest tests/ -x -q
```

CI でも同じチェックが走る。ruff format 違反は自動修正可 (`uv run ruff format src/ tests/`)。

## コーディング規約

- Python 3.10+ (match 文OK、`X | Y` 型ユニオンOK)
- docstring は Google style、ただし自明なものに無理に書かない
- mypy strict: `Any` の使い捨てを避け、型ヒントを明示する
- line length 88 (ruff 既定)
- テストは `tests/test_<package>/test_<module>.py` に配置
- CLI テストは `typer.testing.CliRunner` 経由
- Slurm 依存はモック化 (`subprocess.run` を monkeypatch)
- TOML fixture は `tests/fixtures/` に配置

## テスト方針

- 新機能 / バグ修正には対応するテストを書く
- Adapter / Launcher は contract test で抽象メソッドの網羅を確認
- CLI テストは exit code + stdout/stderr を検証
- `_write_if_missing` 等の冪等ヘルパーは「2 回呼んでも壊れない」ことを確認

## Git ルール

- 1 コミット = 1 論理変更
- commit message は英語推奨 (`fix:`, `feat:`, `refactor:`, `test:`, `docs:`)
- `--no-verify` / `--force` は使わない
- PR は main ブランチへ

## リリース

`$release` スキルで実施する。手順の概要:

1. 品質ゲート通過を確認
2. `pyproject.toml` と `src/runops/__init__.py` のバージョンを **同時に** 更新
3. 日本語のリリースノート草案を作る
4. `git commit -m "chore: bump version to X.Y.Z"` を作成
5. その commit を確認してから `git tag -a vX.Y.Z` を切る
6. `git push origin main` と `git push origin vX.Y.Z` を **順に** 実行する
7. `CI` と `Publish to PyPI` を確認し、GitHub Release 本文も日本語で作成する

`git commit` と `git tag`, `git push origin main` と `git push origin vX.Y.Z` は
並列化しない。tag が 1 つ前の commit を指すと publish が壊れる。
