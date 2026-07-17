---
name: survey-design
description: Use when the requested outcome is a survey.toml, pilot matrix, parameter-space proposal, or bounded cost estimate.
---

# 検証可能なparameter surveyを設計する

## 実行契約

- **Goal**: 仮説を検証するaxes、pilot、full candidateをsurvey定義にする
- **Done**: `survey.toml`、pilot points、run数、cost見積もり、検証結果を報告できる
- **Budget**: 指定caseと一つの情報gapごとに最も近いsourceだけを読む。full matrixはcost ceiling内
- **Invariant**: immutable parameterとcost ceilingを守り、run生成やsubmitへ自動で進まない

## Source routing

| 情報gap | 最初のsource |
|---|---|
| active question / prior decision | `research/CURRENT.md` と該当result README |
| parameter名、物理範囲、安定性 | simulator plugin skill / enabled knowledge |
| base値、job資源 | 対象`case.toml`とinput |
| projectで確定したconstraint | `.runops/facts.toml` |
| 上記で不足する既知例 | `materials/`、最後に`refs/` cookbook |

各gapが解消した時点でsource探索を終える。

## Outcome loop

hypothesisとobservablesからindependent axesを選び、control、failure-detecting edge、代表点で
最小pilotを作る。pilot後のfull matrix candidateとcost ceilingは分けて定義する。
`[survey]`, `[axes]`, `[naming]`, `[job]`を持つ`survey.toml`を作り、
`runo runs sweep <survey> --dry-run`のrun数、組合せ、概算costをDone evidenceにする。

`[naming].display_name`を空にする場合は、base caseとの差分を一目で識別できるよう、
長いparameter keyには`[naming.aliases]`、同じ意味を持つ複数parameterには
`[[naming.groups]]`を一度だけ設計する。例えば`nx`, `ny`, `nz`の一様な倍率変更は
`label = "size"`, `strategy = "uniform_ratio"`として`size-x3`へ畳み込む。
runごとにLLMで名前を生成せず、dry-runに表示される決定的なdirectory名を検証する。

parameterの正確なsyntaxは`runo runs sweep --help`とschema、物理的意味は専門skillを使う。

## Pilot / full entry

- pilotはcontrol、failure-detecting edge、代表点を含む最小集合
- full candidateはpilotの判定基準と`Decision: EXPAND`をentry criteriaに持つ
- immutable parameterはbase caseに固定し、sensitive axisには理由と安全範囲を持たせる

survey設計がDone。run生成、submit、journal整理は、それぞれをGoalに含む依頼で開始する。
