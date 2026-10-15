---
name: sync-docs
description: "Keep runops specs, user docs, and agent-facing text consistent after a change to commands, options, config fields, manifest fields, adapter contract, or project layout. Use before committing such a change."
---

# 仕様と文書の同期

runops の挙動は複数の場所に書かれている。変更の種類から直す場所を決め、正本から順に直す。

| 変更 | 正本 | 追随させる場所 |
|---|---|---|
| command / option の追加・変更 | `SPEC.md` §7.3（先に更新。§13.1 の上限 25 を確認） | `docs/reference.md` の command 表、`src/runops/skills/runops-reference/SKILL.md`、`src/runops/harness.py` の `COMMANDS` |
| `runops.toml` / `case.toml` の field | `SPEC.md` §4, §5 | `docs/reference.md`、`config.py` / `case.py` の既知 key 集合 |
| manifest の field | `SPEC.md` §6.2 | `docs/reference.md` の manifest 表、`ops/migrate.py` の変換 |
| adapter 契約・skill 同梱 | `SPEC.md` §8 | `docs/adapter.md`、`adapters/base.py` の docstring、`legacy_adapters/` |
| エージェントの使い方・規則 | `src/runops/harness.py`（project の AGENTS.md block） | `src/runops/skills/*/SKILL.md`、README の依頼例 |
| 実装中の判断で SPEC 本文と違う結論になった | `SPEC.md` 本文を直し、§14 に理由を 1 行追加 | — |

## 規則

- README は利用者向けで、人が覚えるコマンドは `runo init` だけという前提で書く。それ以外は
  エージェントへの依頼例として書く。
- `docs/` は `reference.md` と `adapter.md` の 2 本だけ。ページを増やす前に既存ページの節で収める。
- project に展開する skill は各 60 行以内、AGENTS.md block は 120 行以内（テストあり）。
- 経緯は書かない（commit message と SPEC §14 に残す）。現在の挙動だけを書く。

## 確認

```bash
uv run pytest -q tests/test_skills.py tests/test_dev_harness.py
uv run runo --help
```

`--help` の command 一覧と SPEC §7.3、`docs/reference.md` の表が一致することを確認する。
