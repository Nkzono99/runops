---
name: improve-harness
description: "Audit or improve the runops agent harnesses: the development harness of this repository (AGENTS.md, .agents/skills, .claude, .codex) and the project harness runops generates (src/runops/harness.py, src/runops/skills). Use when instructions drift from the code, repeat friction appears, or a new workflow needs a skill."
---

# ハーネスの改善

runops には 2 つのハーネスがある。どちらを直すかを先に決める。

| ハーネス | 正本 | 読む人 |
|---|---|---|
| 開発ハーネス | `AGENTS.md`、`.agents/skills/*/SKILL.md`、`.claude/rules/*.md`、`.codex/rules/runops.rules`、`.claude/settings.json`、`.codex/config.toml` | runops を開発するエージェント |
| project ハーネス | `src/runops/harness.py`（AGENTS.md の管理 block）、`src/runops/skills/*/SKILL.md` | runops を使う project のエージェント |

## 開発ハーネスの構造

- skill の正本は `.agents/skills/<name>/SKILL.md`（Codex が読む）。`.claude/skills/<name>/SKILL.md`
  は同じ `name` / `description` の frontmatter と、正本を読むよう指示する 1 文だけを持つ。
- 専門 agent（`spec-reviewer`）も同様に、`.claude/agents/*.md` と `.codex/agents/*.toml` は
  `.agents/skills/<name>/SKILL.md` を指す入口に留める。
- 規約の正本は `.claude/rules/*.md`（Claude Code が自動で読む）。Codex 向けには `AGENTS.md` の表から
  同じ file を参照する。`.codex/rules/` には execpolicy の `runops.rules` だけを置く。
- `AGENTS.md` は 80 行程度の入口に保つ。`CLAUDE.md` は `@AGENTS.md` だけ。
- `tests/test_dev_harness.py` が、入口と正本の対応、参照先の存在、AGENTS.md の長さを検査する。

## 進め方

1. 摩擦を具体的に特定する（どの作業で、何を誤り、何を読み直したか）。
2. 直す場所を 1 か所に決める。恒久規約は rules、繰り返す手順は skill、project の利用者向けは
   project ハーネス。同じ内容を 2 か所に書かない。
3. skill を足すときは description に発火条件を書き、手順は判断に必要な分だけにする。
   `.claude/skills/` に入口を作る。
4. project ハーネスを変えたら `sync-docs` に従い、SPEC §8.3 / §10 と README も確認する。
5. `uv run pytest -q tests/test_dev_harness.py tests/test_skills.py` を通す。
