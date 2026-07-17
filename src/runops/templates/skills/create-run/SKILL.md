---
name: create-run
description: Use when the requested outcome is one or more created run directories generated from an existing case or survey.
---

# case / surveyからrunを生成する

## 実行契約

- **Goal**: 指定caseまたはsurveyをimmutableなrun identityへ展開する
- **Done**: created run_id、件数、base case、overrides、概算cost、生成先を報告できる
- **Budget**: ユーザー指定の単一runまたはsurvey matrix。surveyはdry-runで件数確認後に生成する
- **Invariant**: run identityとgenerated filesはrunopsに作らせ、submitへ自動で進まない

## Entry

| input | entry criteria |
|---|---|
| single run | 既存caseと生成先が確定している |
| survey | `survey.toml`、run数、cost ceilingが確定している |

entry criteriaが不足する場合は、必要なcaseまたは`{{ skill_prefix }}survey-design`を次のGoalとして返す。

## 状態遷移

```bash
# single run
runo runs create <case_name> --dest runs/<path>

# survey preview / apply
runo runs sweep runs/<survey> --dry-run
runo runs sweep runs/<survey>

# generated view
runo runs list runs/<path>
```

case / surveyのsourceと生成先を確定する。surveyはdry-runの件数・parameter組合せ・costを
Budgetと比較し、範囲内なら選んだ生成commandを一度実行する。bulk viewのcreated run_id、
件数、由来をDone evidenceとして返す。

## State invariant

- run directory、`manifest.toml`、`input/`、`submit/job.sh`はrunopsが生成する
- 再利用するinput変更はcase / surveyへ反映してからrunを再生成する
- job submitは別のGoal。単一pilot / full surveyの投入は`{{ skill_prefix }}run-all`が扱う

生成判断を研究記録として残す依頼では、run生成のDoneを返した後、
`{{ skill_prefix }}research-workspace`を独立した次のGoalとして扱う。
