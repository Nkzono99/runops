---
name: check
description: "Run all quality checks (ruff format, ruff check, mypy, pytest) on the changed files. Report pass/fail for each step. If anything fails, show the error and suggest a fix."
---

# 品質チェック実行

変更したファイルに対して全品質ゲートを実行し、結果を報告する。

```bash
uv run ruff format --check src/ tests/
uv run ruff check src/ tests/
uv run mypy src/
uv run pytest tests/ -x -q
```

失敗したステップがあればエラーを表示し、修正案を提示する。
