# Harness Layer

Harness Layer は、人間と Agent が runops project を安全に運用するための手順、
権限、skills、rules、project-local instructions の層です。
研究状態そのものではなく、研究状態を扱うための操作面です。

## 目的

- Agent が project の文脈を読めるようにする。
- 高コスト / 不可逆操作に guardrail を置く。
- 定型作業を skill として共有する。
- Claude Code / Codex の違いを吸収し、同じ project 運用思想を保つ。
- project-local harness と runops upstream template の責務を分ける。

## Project 側の主な構成

| 場所 | 役割 | 更新方針 |
|------|------|----------|
| `CLAUDE.md` | Claude Code 用 project doc | `runo init` / `update-harness` で生成・更新 |
| `AGENTS.md` | Codex 用 project doc | `runo init` / `update-harness` で生成・更新 |
| `.claude/skills/<name>/SKILL.md` | Claude Code skill | template 由来。project 固有編集は慎重に |
| `.agents/skills/<name>/SKILL.md` | Codex skill | template 由来。project 固有編集は慎重に |
| `.claude/rules/` | Claude Code 補助ルール | template 由来 |
| `.codex/rules/` | Codex command policy / rules | template 由来 |
| `.claude/settings.json` | Claude Code permissions | shared guardrail |
| `.codex/config.toml` | Codex project-local config | trusted project 登録時に読む |
| `cases/AGENTS.md`, `runs/AGENTS.md` | directory-specific guidance | `update-harness` で同期 |

## runops 側の template

project 側 harness の source of truth は runops repo 内の template です。

| Source | 生成先 |
|--------|--------|
| `src/runops/templates/skills/<name>/SKILL.md` | `.claude/skills/`, `.agents/skills/` |
| `src/runops/templates/harness/claude/` | `.claude/`, `CLAUDE.md` |
| `src/runops/templates/harness/codex/` | `.codex/`, `AGENTS.md` |
| `src/runops/templates/harness/shared/` | Claude / Codex 共通本文・rules |
| `src/runops/templates/scaffold/` | `notes/`, `research/`, `materials/` などの scaffold |

汎用 harness 改善は project 側ファイルに直接固定せず、template に戻します。

## 何を置くか

Harness Layer に置くもの:

- command policy
- human gate
- skill 手順
- Agent が最初に読むべき順序
- protected file の扱い
- runops local patch / feedback の手順
- project-specific override

置かないもの:

- 研究判断の正本。これは `research/agenda.md`。
- run の状態、job 履歴、provenance。これは Execution Kernel の `manifest.toml`。
- 実験ログ。これは `notes/YYYY-MM-DD.md`。
- simulator output。これは `runs/**/work/`。
- 解析成果物。これは `runs/**/analysis/`, `<survey>/summary/`, `analysis/cross_run/`。
- upstream issue の本文そのもの。これは GitHub issue と note の evidence path。

## 更新ルール

- `runo update-harness` は template 由来の harness を再生成する。
- 既存 project の local edits と衝突する場合は `.new` を出して手動マージに回す。
- shared な運用変更を入れたら Claude / Codex 側の drift を点検する。
- project 固有の一時 override は `AGENTS.override.md` や user-local 設定に置き、Git 管理しない。
- project 固有 harness を汎用化したくなったら [Upstream Integration Layer](upstream.md) に進む。

## Agent から見た読み順

1. project root の `AGENTS.md` / `CLAUDE.md`
2. directory-specific `AGENTS.md` / `CLAUDE.md`
3. relevant skill
4. relevant layer doc under `docs/layers/`
5. `.runops/knowledge/enabled/imports.md` と `.runops/knowledge/runops/`
6. 実行中 package の場所 (`uvx --from runops python -c "import runops; print(runops.__file__)"`) は最後の手段

## 他レイヤとの関係

- Experiment / Execution Kernel / Analysis / Research / Knowledge Layer は project 状態の正本を持つ。
- Harness Layer はそれらを安全に操作するための手順を持つ。
- Upstream Integration Layer は、harness の不満や改善を runops template に戻す境界を持つ。
