# runops ワークフロー不変条件

`.claude/settings.json` が高コスト・不可逆操作の機械的な境界を持つ。この rule は、
Goal / Done に向かう状態遷移で正規の更新経路を選ぶために使う。

## 状態遷移の不変条件

| 対象 | 正規の更新経路 |
|---|---|
| run directory / `manifest.toml` / input / `submit/job.sh` | case / survey を source にした `runo runs create|sweep|clone|extend`。`regenerate --dry-run` は差分確認のみ |
| Experiment question / budget / decision | `runo experiments create|review|close` |
| Survey candidate / materialize | `runo runs sweep` (read-only) / `--apply --point|--all --expect-plan` |
| smoke / debug | `runo test smoke|debug|record|clean` (`.runops/test-runs/T...`) |
| run state / provenance | `runo runs submit|sync|archive|restore|purge-work|delete` |
| runtime output | `work/` を evidence として保持し、runops command で整理する |
| reusable simulator input | `case.toml`、input template、`survey.toml` |
| insight / fact | `runo knowledge save|add-fact|promote-fact` |
| `SITE.md`, `.runops/knowledge/`, `refs/` | generated / read-only source として参照する |
| trial analysis / provisional prose | `.runops/work/<goal-id>/` |
| curated analysis | `analysis/summary.json`, curated figure, sealed `research/results/` |

runops 本体の変更は研究 project と分離した source checkout で扱う。project では
`uvx --from runops runo ...`、simulator runtime では `.venv/` を使う。

## Submit の実行契約

| Goal | entry / Done |
|---|---|
| bounded pilot submit | Goalによる認可、exact対象・queue・資源 / job_id・成功条件をhandoff |
| full submit | pilot Result evidence、Experiment `decision=expand`、cost ceiling、承認 / 全 job_id と投入 evidence の報告 |
| startup validation | progress marker と観測期限 / marker の進行または期限時点の状態報告 |

`runo runs submit --dry-run --all` で bulk 対象を確定し、承認済みの場合は
`runo runs submit --all --yes` で CLI prompt をまとめる。startup validation は
`check-status` skill のBudgetに従う。

`runo runs sweep`は既定でdirectoryを作らない。pilot materializationには`--apply`、explicit
point selection、previewのplan hashを使い、旧全生成の代わりに`--all`を推測しない。

bounded pilot submitがGoalに含まれる場合は追加の承認ターンを作らず、通常のsubmit
precondition後に投入する。job_idと成功条件を返した時点でhandoffし、startup validationが
Goalに含まれる場合だけbounded checkへ進む。full / large submitだけEXPAND gateを使う。

## Human checkpoint

次の状態遷移は、対象と影響を示して承認を得る。

- 初回 bulk submit、`runo runs submit --all`、資源増加 retry
- Survey `--all` materialization、Experiment `decision=expand`
- purge / delete、実行 binary・module・launcher の変更
- `runops.toml`, `simulators.toml`, `launchers.toml`, `CLAUDE.md`, `AGENTS.md`,
  `.claude/settings.json`, `.codex/config.toml`, `.codex/rules/**` の変更

cancel は対象と理由を報告して進める。

## Evidence checkpoint

意味のある状態遷移を一つの論理コミットにする。今回変更した投入設定はsubmit前にcommitし、
変更がなければcurrent commit / dirty provenanceを使う。解析後はmetric / figureとprovenance、
knowledge昇格時はsource resultとevidence pathを残す。

Run reviewはterminal outcomeの確認であり、claimへの採用ではない。Resultがevidence edgeを
所有する。Run evidenceはcompleted相当、理由付きreview、identity / source / baseline / input
snapshotを要求し、T IDと`.runops/test-runs/**`はscientific evidenceにしない。
Result sealにはselection reasonを記録し、includeしたRun-owned outputをpurgeしない。
永続的な研究 prose は `research/CURRENT.md`、`research/journal/*.md`、各 Result
の `README.md` だけに置く。別名の note も作らず、一時 prose は
`.runops/work/` に置く。
