---
name: survey-design
description: Use when the requested outcome is a survey.toml, pilot matrix, parameter-space proposal, or bounded cost estimate.
---

# 検証可能なparameter surveyを設計する

## 実行契約

- **Goal**: 仮説を検証するaxes、pilot、full candidateをsurvey定義にする
- **Done**: `survey.toml`、pilot points、run数、cost見積もり、検証結果を報告できる
- **Budget**: 指定caseと一つの情報gapごとに最も近いsourceだけを読む。full matrixはcost ceiling内

## Source routing

| 情報gap | 最初のsource |
|---|---|
| active question / prior decision | `research/CURRENT.md` と該当result README |
| parameter名、物理範囲、安定性 | simulator plugin skill / enabled knowledge |
| base値、job資源 | 対象`case.toml`とinput |
| projectで確定したconstraint | `.runops/facts.toml` |
| 上記で不足する既知例 | `materials/`、最後に`refs/` cookbook |

各gapが解消した時点でsource探索を終える。

## 状態遷移

1. hypothesisとobservablesから必要なindependent axesを選ぶ
2. control、failure-detecting edge、代表点から最小pilotを作る
3. pilot evidence後に検討するfull matrix candidateとcost ceilingを分ける
4. `[survey]`, `[axes]`, `[naming]`, `[job]`を持つ`survey.toml`を作る
5. `runo runs sweep <survey> --dry-run`でrun数、parameter組合せ、概算costを検証する
6. Doneと、full submitに進むための判定基準を報告する

parameterの正確なsyntaxは`runo runs sweep --help`とschema、物理的意味は専門skillを使う。

## Pilot / full entry

- pilotはcontrol、failure-detecting edge、代表点を含む最小集合
- full candidateはpilotの判定基準と`Decision: EXPAND`をentry criteriaに持つ
- immutable parameterはbase caseに固定し、sensitive axisには理由と安全範囲を持たせる

survey設計がDone。run生成、submit、journal整理は、それぞれをGoalに含む依頼で開始する。
