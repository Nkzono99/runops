---
name: research-director
description: Select the next bounded scientific experiment from the research agenda, create an evidence-linked proposal, define a pilot and falsification criteria, and update the active experiment portfolio.
---

# Research Director

この skill は「次に何を計算するか」を決め、full survey より小さい検証可能な pilot
へ落とす。実行数を増やすこと自体を成果にせず、active question を最短で判別できる
実験を 1 件だけ選ぶ。

## 読むもの

1. `campaign.toml`
2. `research/agenda.md` の Charter、Current Beliefs、Active Questions、
   Active Experiment Portfolio
3. 関連する `notes/reports/`、`analysis/cross_run/`、run summary / figure
4. `SITE.md`、queue / quota、既知の runtime と失敗率
5. relevant simulator plugin skill / enabled knowledge

## 作るもの

`research/proposals/<date>-<topic>.md` を 1 件作り、最低限次を明記する。

- Experiment ID と対象 Active Question
- Objective と prior evidence path
- Hypothesis と対立仮説
- falsification observation（何が出たら仮説を棄却するか）
- baseline、独立変数、固定する control、既知 confound
- pilot matrix（両端・中央・control など最小の代表点）
- full matrix candidate（pilot 後にだけ有効）
- required artifact / metric と解析方法
- success / failure / stop / expand criterion
- pilot と full の cost estimate、queue、walltime、quota 影響
- human gate と承認対象

同時に `research/agenda.md` の `Active Experiment Portfolio` を更新する。

さらに `research/experiments.toml` の同じ Experiment ID に最低 2 候補を
`[[experiments.candidates]]` として記録する。各候補は `information_gain`,
`falsification`, `estimated_core_hours`, `operational_risk` を持つ。
`selected_candidate` と proposal 本文の選定理由を一致させる。

```text
- E1:
  - Phase: proposed
  - Question:
  - Proposal: research/proposals/<date>-<topic>.md
  - Pilot runs:
  - Review:
  - Decision: WAIT
  - Cost budget:
  - Stop criterion:
  - Expand criterion:
  - Human gate: yes
```

## 判断ルール

- 1 proposal は原則 1 active question を判別する。
- pilot は full matrix より十分小さくし、control と failure-detecting edge を含める。
- 既存 evidence で答えられるなら新規 run を提案しない。
- 必要な artifact / metric を先に定義できない experiment は開始しない。
- falsification criterion のない proposal は完成扱いにしない。
- cost が human limit を超える場合は pilot も投入せず承認を待つ。
- この skill 自体は full submit を行わない。設計は
  `{{ skill_prefix }}survey-design`、pilot 後の判断は
  `{{ skill_prefix }}review-pilot`、投入は `{{ skill_prefix }}run-all` へ渡す。

## 完了条件

- proposal が evidence path と criteria を持つ
- portfolio の phase / proposal / budget / gate が一致する
- 次に投入してよい範囲が pilot までと明記されている
- 判断理由を `{{ skill_prefix }}note` へ追記している
