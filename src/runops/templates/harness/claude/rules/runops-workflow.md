# runops ワークフロー不変条件

`.claude/settings.json` が高コスト・不可逆操作の機械的な境界を持つ。この rule は、
Goal / Done に向かう状態遷移で正規の更新経路を選ぶために使う。

## 状態遷移の不変条件

| 対象 | 正規の更新経路 |
|---|---|
| run directory / `manifest.toml` / input / `submit/job.sh` | case / survey を source にした `runo runs create|sweep|regenerate` |
| run state / provenance | `runo runs submit|sync|archive|purge-work|delete` |
| runtime output | `work/` を evidence として保持し、runops command で整理する |
| reusable simulator input | `case.toml`、input template、`survey.toml` |
| insight / fact | `runo knowledge save|add-fact|promote-fact` |
| `SITE.md`, `.runops/knowledge/`, `refs/` | generated / read-only source として参照する |
| trial analysis | `runs/**/analysis/scratch/` |
| curated analysis | `analysis/summary.json`, curated figure, `research/results/` |

runops 本体の変更は研究 project と分離した source checkout で扱う。project では
`uvx --from runops runo ...`、simulator runtime では `.venv/` を使う。

## Submit の実行契約

| Goal | entry / Done |
|---|---|
| pilot submit | 対象・queue・資源・command の承認 / job_id と判定基準の報告 |
| full submit | pilot evidence、`Decision: EXPAND`、cost ceiling、承認 / 全 job_id と投入 evidence の報告 |
| startup validation | progress marker と観測期限 / marker の進行または期限時点の状態報告 |

`runo runs submit --dry-run --all` で bulk 対象を確定し、承認済みの場合は
`runo runs submit --all --yes` で CLI prompt をまとめる。startup validation は
`check-status` skill の観測予算に従う。

## Human checkpoint

次の状態遷移は、対象と影響を示して承認を得る。

- 初回 bulk submit、`runo runs submit --all`、資源増加 retry
- purge / delete、実行 binary・module・launcher の変更
- `runops.toml`, `simulators.toml`, `launchers.toml`, `CLAUDE.md`, `AGENTS.md`,
  `.claude/settings.json`, `.codex/config.toml`, `.codex/rules/**` の変更

cancel は対象と理由を報告して進める。

## Evidence checkpoint

意味のある状態遷移を一つの論理コミットにする。submit 前は snapshot commit、解析後は
metric / figure と provenance、knowledge 昇格時は source result と evidence path を残す。
