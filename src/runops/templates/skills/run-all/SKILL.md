---
name: run-all
description: Generate and submit a survey when the requested outcome is a reviewed pilot or an approved full parameter sweep.
---

# Pilot evidence から survey 投入へ進める

## 実行契約

- **Goal**: reviewed pilot、または承認済み full submit を requested state まで進める
- **Done**: pilotはjob_id・対象・判定基準、fullは全job_id・skip・資源量・snapshot commitを報告できる
- **Budget**: `cost ceiling` と承認された run / resource 範囲
- **Invariant**: pilot evidence、cost ceiling、必要な承認を満たさずfull submitしない

初動確認が Goal に含まれる場合は、submit の Done を満たした後、
`{{ skill_prefix }}check-status` の bounded startup check へ一度だけ遷移する。

## State routing

| current evidence | one transition | outcome |
|---|---|---|
| run未生成 | `runo runs sweep`とlistでexact pilot run_idを確定 | pilot submitへ進める状態 |
| pilot evidenceなし | 対象・queue・資源・cost・commandの承認後にpilot submit | pilotのDone |
| pilot submitted / running | stateを返し、必要なら`{{ skill_prefix }}check-status`を次Goalにする | 今回は待機しない |
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

entry criteriaがpilotまでならpilotのDoneを返す。policy / environment blockerは、
止まった状態と予定していた command を evidence として返す。

## 投入 evidence

投入evidenceの記録がGoalに含まれる場合は`{{ skill_prefix }}research-workspace`へsurvey、時刻、queue、
run数、想定walltime / core-hour、pilotと判定基準、job_id、投入前snapshot commitを渡す。
