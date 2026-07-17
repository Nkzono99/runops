---
name: analyze
description: Use when the requested outcome explicitly requires metrics, figures, survey aggregation, cross-run comparison, or publication export from completed runs.
---

# requested evidenceを解析成果物にする

## 実行契約

- **Goal**: 指定run / surveyから要求されたmetric、figure、comparison、exportを作る
- **Done**: requested artifact、再現command、主要結果、source runを報告できる
- **Budget**: 指定targetとartifact数。選んだ解析routeだけを実行する
- **Invariant**: raw outputとprovenanceを保持し、knowledge昇格や別routeを自動で連鎖しない

## Goal routing

| requested outcome | route |
|---|---|
| run-local metrics | `runo analyze summarize <run>` |
| survey table | `runo analyze collect <survey>` |
| 定型plot | `runo analyze plot <survey> --list-recipes` → 選択recipe |
| 指定x/y plot | `runo analyze plot <survey> --list-columns` → `--x/--y` |
| cross-run comparison | `runo analyze new-comparison <name> --source <survey>` |
| publication bundle | `runo analyze export <target> --paper <paper-id>` |

一つの依頼で必要なrouteだけを選ぶ。summaryが選択routeのentry criteriaなら対象runに限定して
生成する。requested metricがAdapter summaryに無い場合は、`{{ skill_prefix }}summarize-script`を
そのmetricに限定して使う。

## Artifact placement

- run-local curated artifact: `runs/**/analysis/`
- run-local trial: `runs/**/analysis/scratch/`
- survey aggregation: `<survey>/summary/`
- cross-run result: `research/results/RNNNN-*/README.md`と`artifacts/`
- publication export: `exports/papers/`

解析artifactと結果報告がDone。再利用knowledgeへの昇格は、claimとevidenceを指定した
`{{ skill_prefix }}learn`の別Goalとして扱う。
