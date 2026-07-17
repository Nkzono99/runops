---
name: learn
description: Use when the requested outcome is one reusable insight or structured fact backed by an explicit research result.
---

# 一つのclaimを再利用知識へ昇格する

## 実行契約

- **Goal**: 明示されたresultのstable claimをinsightまたはfactにする
- **Done**: claim、適用範囲、反例、source result ID、evidence pathを保存・報告できる
- **Budget**: 一つのclaimと、その根拠に必要なresult README / artifactだけ
- **Invariant**: journalから重要度を推測して一括昇格せず、source evidenceを複製・改変しない

## Goal routing

| claim | route |
|---|---|
| narrative、条件付き知見 | `runo knowledge save` |
| atomic、機械検証可能な主張 | `runo knowledge add-fact` |

`runo research status`でsource resultを特定し、該当`research/results/RNNNN-*/README.md`と
artifactからclaim、scope、counterexample、evidence pathだけを抽出する。resultへ昇格していない
観察は保存せず、候補と不足evidenceを返す。

`research/CURRENT.md`は現在判断が変わる場合だけ別のstate updateとして編集する。
