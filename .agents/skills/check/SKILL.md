---
name: check
description: "Run runops quality gates (ruff format, ruff check, mypy, pytest with branch coverage) after code changes, and the extra checks for filesystem, adapter, or migration changes. Report pass/fail per step and fix failures."
---

# 品質チェック

## 常に実行する

```bash
uv run ruff format --check src/ tests/
uv run ruff check src/ tests/
uv run mypy src/
uv run pytest -q --cov=runops --cov-branch --cov-fail-under=80
```

pytest は 60 秒以内が目標（SPEC §13.1）。Slurm は `tests/conftest.py` の `FakeSlurm` で
mock する。実際の `sbatch` を呼ぶテストを書かない。

## 変更内容に応じて追加する

| 変更 | 追加の確認 |
|---|---|
| rename / move / archive / 作成など filesystem 操作 | `uv run pytest -q -p no:cacheprovider --basetemp=/LARGE0/gr20001/b36291/claude_scratch/pytest-lustre` で Lustre 上でも通す（`RENAME_NOREPLACE` が EINVAL になる経路） |
| adapter 解決、`.venv` の entry point、skill 展開 | `tests/test_skills.py` と `tests/test_adapters.py`。必要なら scratch project で `uv venv` + `uv pip install -e <simulator>` して `runo doctor` |
| `migrate-v1` | `tests/test_migrate.py`。実 project には `runo migrate-v1 --dry-run` だけを実行し、適用は `work/` を除いたコピーで行う |
| job.sh 生成 | `tests/golden/*.sh` との差分を目視し、意図した変更なら `UPDATE_GOLDEN=1 uv run pytest tests/test_jobgen.py` |
| project に展開する skill / AGENTS.md block | `tests/test_skills.py`（行数上限）と `sync-docs` skill |
| 開発ハーネス | `tests/test_dev_harness.py` |

## 報告

各ステップの pass / fail を示し、失敗はエラー出力と修正内容を添える。
`ruff format` の違反は `uv run ruff format src/ tests/` で直してよい。
