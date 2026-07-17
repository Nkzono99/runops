---
name: run-all
description: Generate and submit a survey when the requested outcome is a reviewed pilot or an approved full parameter sweep.
---

# Pilot evidence から survey 投入へ進める

## 実行契約

- **Goal**: reviewed pilot、または承認済み full submit を requested state まで進める
- **Done (pilot)**: pilot job_id、対象 run、判定基準を報告できる
- **Done (full submit)**: 全 job_id、対象・skip・queue・資源量・snapshot commit を報告できる
- **Budget**: `cost ceiling` と承認された run / resource 範囲

初動確認が Goal に含まれる場合は、submit の Done を満たした後、
`{{ skill_prefix }}check-status` の bounded startup check へ一度だけ遷移する。

## 状態遷移

1. `research/CURRENT.md`、対応する result README、pilot matrix、cost ceiling を確認する
2. `runo runs sweep` と `runo runs list` で run と exact pilot run_id を確定する
3. pilot evidence が未作成なら、投入内容の承認を得て pilot run を submit し、pilot の Done を返す
4. pilot 完了後は `{{ skill_prefix }}research-workspace` で result evidence と CURRENT の判断を更新する
5. full submit の entry criteria を確認する
6. `runo runs submit --dry-run --all` で対象と skip を確定する
7. remaining run 数、queue、資源量、cost ceiling、command を示して承認を得る
8. `runo runs submit --all` を実行し、full submit の Done を返す

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

entry criteria が pilot までなら pilot の Done、判断が `REVISE`, `STOP`, `WAIT` なら
その判断と次の実験候補を現在の到達状態として返す。policy / environment blocker は、
止まった状態と予定していた command を evidence として返す。

## 投入 evidence

`{{ skill_prefix }}research-workspace` には survey、時刻、queue、run 数、想定 walltime / core-hour、
pilot と判定基準、job_id、投入前 snapshot commit を残す。
