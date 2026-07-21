# Agent User Guide

このページは、runops project で Agent が守る実行契約をまとめたものです。
run directory が実行の主単位、`manifest.toml` が状態と provenance の正本です。

## 最初に確認するもの

現在地が不明な場合は project context を読みます。必要な情報だけ追加で調べます。

```bash
uvx --from runops runo context --json
uvx --from runops runo research status
uvx --from runops runo lint --scope structure,analysis,knowledge,plugins
```

毎回すべてを実行する必要はありません。現在の Goal に関係する情報だけを選びます。

## 実行契約

| 項目 | 意味 |
|---|---|
| Goal | 今回到達させる研究・project state |
| Done | 到達を示す evidence や artifact |
| Budget | run 数、cost、待機時間、観測回数の上限 |
| Invariant | 状態整合性、安全性、provenance の境界 |

Agent は現在の evidence から、Done に必要な最短の状態遷移を選びます。Done に到達したら
結果を返し、次 phase は候補として示します。

| Goal | Done の例 |
|---|---|
| campaign 設計 | 仮説、変数、観測量を持つ検証済み `campaign.toml` |
| survey 設計 | `survey.toml`、pilot points、run 数、概算 cost |
| run 生成 | created run ID、件数、由来 |
| submit | manifest に記録された job ID |
| 初動確認 | step や progress marker の変化 |
| 解析 | metric、figure、export と再現 command |

## 人と Agent の境界

- 人は研究目的、base input、資源上限、残す result を決める。
- Agent は Goal の範囲で case / survey 編集、run 生成、状態同期、解析を進める。
- 初回 bulk submit、資源増加、cancel、archive、purge、delete、研究方針の転換は確認する。

生成済みの `manifest.toml`、`input/`、`submit/job.sh` を直接編集しません。再利用する変更は
case や survey に戻し、新しい run を生成します。

## 実行と解析

```bash
runo runs status
runo runs sync
runo runs submit --dry-run --all <survey>
runo analyze summarize <run>
runo analyze collect <survey>
runo analyze plot <survey>
```

submit 前には command、対象 run、queue、QOS、resources、walltime を示します。submit の
Done は job ID です。初動確認も Goal に含む場合だけ、progress marker と観測期限を決めて
待機します。

artifact の置き場所:

| 対象 | 保存先 |
|---|---|
| run-local analysis | `runs/**/analysis/` |
| survey 集計 | `<survey>/summary/` |
| 複数 run / survey の比較 | `research/results/` |
| Goal 中の一時出力 | `.runops/work/<goal-id>/` |

## 研究記憶

```text
research/CURRENT.md
research/journal/active.md
research/journal/archive/JNNNN.md
research/results/RNNNN-topic/{README.md,manifest.toml,artifacts/}
research/archive/results/
.runops/work/<goal-id>/
```

- `CURRENT.md` には現在の判断だけを置く。
- 時系列ログは `runo research append` で追記し、量に応じて原文のまま rotate する。
- 大量の途中出力は `.runops/work/<goal-id>/` に置く。
- 人が残すと決めた解析だけ `runo research new-result` で昇格する。
- evidence を自動削除したり、要約で置き換えたりしない。

```bash
runo research append "Series A design" "Context: ... Evidence: ..."
runo research new-result series-a-scaling
runo research check
```

旧 project の移行は、必ず preview してから適用します。

```bash
runo research migrate-legacy --dry-run
runo research migrate-legacy
```

## 再利用知識と upstream

`.runops/insights/` と `.runops/facts.toml` には、明示的に昇格した小さな知見だけを置きます。
journal を無差別にコピーせず、claim、適用範囲、反例、evidence path を記録します。

runops 本体の patch は研究 project と混ぜません。別 checkout の branch / commit で修正し、
project 固有情報を除いて issue や PR にします。詳細は
[Upstream Integration Layer](layers/upstream.md) を参照してください。
