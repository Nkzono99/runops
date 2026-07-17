# Harness Layer

Harness Layer は、人間と Agent が runops project を安全に運用するための手順、
権限、skills、rules、project-local instructions の層です。
研究状態そのものではなく、研究状態を扱うための操作面です。

## 目的

- Agent が project の文脈を読めるようにする。
- Goal / Done / Budget から最短の状態遷移を選べるようにする。
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
| `src/runops/templates/scaffold/` | minimal `research/`, `materials/` などの scaffold |

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

### Feed-forward core

通常運用は、禁止事項の列挙ではなく次の実行契約を正本にします。

1. **Goal**: 今回到達させる研究・project state
2. **Done**: 到達を示す evidence / artifact
3. **Budget**: run 数、cost、待機時間、観測回数
4. **Next**: Goal に最も近い一つの状態遷移

Agent は Done に必要な source と skill だけを読み、到達時に返します。submit、監視、解析は
別々の到達状態なので、後続段階は依頼の Done に含まれる場合に進みます。

頻出skillは次の条件を満たします。

- descriptionは「いつの後に」ではなく、どのrequested outcomeで発火するかを書く。
- 一つのskillは一つのDoneで閉じ、隣接phaseは次のGoal候補として返す。
- source探索、診断、観測にはBudgetを置き、情報gapが解消した時点で終了する。
- campaign、survey、run生成、解析、plugin setup、cleanupは90行以内を回帰テストする。
- research journalやknowledge昇格は、provenanceまたはknowledgeがGoalに含まれる場合に独立して扱う。
- 汎用package開発skillはrunops開発ハーネスに置き、simulation research projectには配布しない。

否定形の rule は、目的設定だけでは守れない安全 invariant に限定します。高コスト・不可逆
command は policy / permission、人間の研究判断は checkpoint、定型手順は relevant skill に置きます。
CLI command の網羅表を root instruction に複製せず、task-specific skill と選択した command の
`--help` を progressive disclosure で参照します。

置かないもの:

- 研究判断の正本。これは `research/CURRENT.md`。
- run の状態、job 履歴、provenance。これは Execution Kernel の `manifest.toml`。
- 時系列の研究ログ。これは量で rotation する `research/journal/active.md`。
- simulator output。これは `runs/**/work/`。
- 解析成果物。run-local は `runs/**/analysis/`、残す横断結果は `research/results/`。
- upstream issue の本文そのもの。これは GitHub issue と evidence path。

## 更新ルール

- `runo update-harness` は template 由来の harness を再生成する。
- 既存 project の local edits と衝突する場合は `.new` を出して手動マージに回す。
- shared な運用変更を入れたら Claude / Codex 側の drift を点検する。
- root instruction は入口と feed-forward core に絞り、180 行を上限として回帰テストする。
- project 固有の一時 override は `AGENTS.override.md` や user-local 設定に置き、Git 管理しない。
- project 固有 harness を汎用化したくなったら [Upstream Integration Layer](upstream.md) に進む。

## Agent から見た読み順

1. project root の `AGENTS.md` / `CLAUDE.md`
2. directory-specific `AGENTS.md` / `CLAUDE.md`
3. `runo plugins --json` の `delegated_capabilities` と該当 simulator/environment plugin skill
4. relevant project-local skill
5. relevant layer doc under `docs/layers/`
6. `.runops/knowledge/enabled/imports.md` と `.runops/knowledge/runops/`
7. 実行中 package の場所 (`uvx --from runops python -c "import runops; print(runops.__file__)"`) は最後の手段

## 他レイヤとの関係

- Experiment / Execution Kernel / Analysis / Research / Knowledge Layer は project 状態の正本を持つ。
- Harness Layer はそれらを安全に操作するための手順を持つ。
- Upstream Integration Layer は、harness の不満や改善を runops template に戻す境界を持つ。
