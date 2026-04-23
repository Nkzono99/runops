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
3. `git commit -m "chore: bump version to X.Y.Z"` + `git tag vX.Y.Z`
4. `git push origin main --tags` で CI が PyPI にパブリッシュ
