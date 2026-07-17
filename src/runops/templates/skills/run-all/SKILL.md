---
name: run-all
description: Generate and submit a survey when the requested outcome is a bounded pilot or an approved full parameter sweep.
---

# Bounded pilot から full survey の判断へ進める

## 実行契約

- **Goal**: bounded pilot、または承認済み full submit を requested state まで進める
- **Done**: pilotはjob_id・成功条件・再開条件をhandoffし、fullは全job_id・skip・資源量を報告できる
- **Budget**: `cost ceiling` と Goal が認可した run / resource 範囲
- **Invariant**: full / large submit だけはpilot evidence、`Decision: EXPAND`、承認をentry criteriaにする

bounded pilot submit が Goal に含まれ、対象と資源がcost ceiling内で確定している場合、
その依頼を認可として通常のsubmit preconditionを通し、追加の承認ターンを作らない。
別のdry-runは対象・queue・資源が曖昧な場合に使う。

pilot submit は job_id と成功条件を返して会話を handoff する。完了観測を Done に含めない。
startup validation が Goal に含まれる場合だけ、submit後に
`{{ skill_prefix }}check-status`のbounded startup checkへ一度遷移する。

## State routing

| current evidence | one transition | outcome |
|---|---|---|
| run未生成 | `runo runs sweep`とlistでexact pilot run_idを確定 | bounded pilot submit |
| bounded pilot認可済み | exact runをsubmit | job_idと成功条件を返してhandoff |
| pilot submitted / running | job_id、成功条件、再開条件を返す | submit GoalのDone |
| pilot completed、判断なし | result evidenceと`research/CURRENT.md`の判断を次Goalにする | full submitをdefer |
| `REVISE`, `STOP`, `WAIT` | 判断と次の実験候補を返す | submitしない |
| `Decision: EXPAND` + 承認 | dry-runで対象・skip・costを再確認してfull submit | fullのDone |

full submit の entry criteria:

- pilot run_id、判定基準、result evidence が対応している
- `research/CURRENT.md` の判断が `Decision: EXPAND`
- 初回 bulk submit または資源増加分についてユーザー承認がある

```bash
runo runs sweep $ARGUMENTS
runo runs list $ARGUMENTS
runo runs submit <pilot-run-id> -qn <queue>

runo runs submit --dry-run --all -qn <queue>
runo runs submit --all -qn <queue>
# 会話上で承認済みなら CLI prompt を省略
runo runs submit --all --yes -qn <queue>
```

pilotのhandoffにはjob_id、対象run、成功条件、成功確認後の次段階を含める。
policy / environment blockerは、止まった状態と予定していたcommandを返す。

## 投入 evidence

投入evidenceの記録がGoalに含まれる場合は`{{ skill_prefix }}research-workspace`へsurvey、時刻、queue、
run数、想定walltime / core-hour、pilotと成功条件、job_id、source commit / dirty provenanceを渡す。
入力・設定を今回変更した場合だけ、その変更をsubmit前の一つの論理コミットにする。
