---
name: create-run
description: Use when the requested outcome is one or more created run directories generated from an existing case or survey.
---

# case / surveyからrunを生成する

## 実行契約

- **Goal**: active Experiment内で指定caseまたはselected survey pointをimmutableなRun identityへ展開する
- **Done**: created run_id、件数、base case、overrides、概算cost、生成先を報告できる
- **Budget**: ユーザー指定の単一Runまたは明示selected point。候補matrix全体はdirectory budgetではない
- **Invariant**: run identityとgenerated filesはrunopsに作らせ、submitへ自動で進まない

## Entry

| input | entry criteria |
|---|---|
| single run | 既存case、active Experiment、生成先が確定している |
| survey | `experiment_id`、phase、purpose、budget、previewのpoint ref / plan hashが確定している |

entry criteriaが不足する場合は、必要なcaseまたは`{{ skill_prefix }}survey-design`を次のGoalとして返す。

## 状態遷移

```bash
# single run
runo runs create <case_name> --dest runs/<path> --experiment EYYYYMMDD-NNNN

# survey preview / apply
runo runs sweep runs/<survey>
runo runs sweep runs/<survey> \
  --apply --point p0001 --expect-plan sha256:...

# generated view
runo runs list runs/<path>
```

case / surveyのsourceと生成先を確定する。survey previewはread-onlyで、Run IDを消費しない。
候補数・parameter組合せ・costをBudgetと比較し、選んだpointだけをexact plan hash付きで
一度materializeする。`--all`はユーザーが全点を明示選択した場合だけ使う。bulk viewのcreated run_id、
件数、由来をDone evidenceとして返す。

## State invariant

- run directory、`manifest.toml`、`input/`、`submit/job.sh`はrunopsが生成する
- 再利用するinput変更はcase / surveyへ反映してからrunを再生成する
- frozen Runを`regenerate`でin-place更新せず、変更はclone/extendで新しいRunにする
- job submitは別のGoal。単一pilot / full surveyの投入は`{{ skill_prefix }}run-all`が扱う
- smoke / debugはformal Runを作らず`runo test smoke|debug`へrouteする

生成判断を研究記録として残す依頼では、run生成のDoneを返した後、
`{{ skill_prefix }}research-workspace`を独立した次のGoalとして扱う。
