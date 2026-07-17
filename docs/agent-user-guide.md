# Agent User Guide

runops project では run directory が実行の主単位、`manifest.toml` が状態と provenance
の正本です。Agent は `context` で現在地を把握し、Goal に必要な追加情報だけを選びます。

```bash
uvx --from runops runo context --json
# research memory が Next の判断に必要な場合
uvx --from runops runo research status
# structure / analysis / knowledge / plugin の health が必要な場合
uvx --from runops runo lint --scope structure,analysis,knowledge,plugins
```

## 目的駆動の実行契約

- **Goal**: 今回到達させる研究・project state
- **Done**: 到達を示す evidence / artifact
- **Budget**: run 数、cost、待機時間、観測回数
- **Next**: Goal に最も近い一つの状態遷移

Agent は Done に必要な skill と command だけを使い、到達した時点で結果を返します。
たとえば submit の Done は job_id、初動確認の Done は step / progress marker の変化です。

## 人と Agent の境界

- 人: 研究目的、base input、計算資源上限、残す result を決める。
- Agent: Goal の範囲で case/survey 編集、run 生成、投入、状態同期、解析、一時作業を進める。
- 要確認: 初回 bulk submit、資源増加、cancel、purge、delete、研究方針の転換。

## 研究記憶

```text
research/CURRENT.md
research/journal/active.md
research/journal/archive/JNNNN.md
research/results/RNNNN-topic/{README.md,manifest.toml,artifacts/}
research/archive/results/
.runops/work/<goal-id>/
```

- 現在判断は `CURRENT.md`。既定 50 行を目安にし、作業日誌や artifact inventory に戻さない。
- 時系列ログは `runo research append`。日数ではなく文字数で原文 rotation。
- goal の大量な途中出力は `.runops/work/<goal-id>/`。
- 人が残すと決めた解析だけ `runo research new-result` で昇格。
- narrative は result ごとに README 1 枚。`artifacts/` に Markdown を作らない。
- AI は evidence を自動削除・要約置換しない。
- 網羅的な artifact provenance は export/source index に置く。

```bash
runo research append "Series A design" "Context: ... Evidence: ..."
runo research new-result series-a-scaling
runo research archive R0001-series-a-scaling
runo research restore R0001-series-a-scaling
runo research check
```

旧 project は適用前に必ず preview します。

```bash
runo research migrate-legacy --dry-run
runo research migrate-legacy
# 必要なら
runo research migrate-legacy --restore
```

## 実行と解析

```bash
runo runs status
runo runs sync
runo runs submit --dry-run --all <survey>
runo analyze summarize <run>
runo analyze collect <survey>
runo analyze plot <survey>
runo analyze new-comparison <name> --source <survey>
```

submit 前に command、対象 run、queue、QOS、nodes/tasks/walltime を示し、人の確認を
得ます。submit Goal は job_id の記録で完了します。初動確認も Goal に含む場合は、
progress marker と観測期限を設定して `check-status` skill に進みます。

run-local artifact は `runs/**/analysis/`、survey 集計は `<survey>/summary/`、複数
run/survey 比較は `research/results/` に置きます。

## 再利用知識

`.runops/insights/` と `.runops/facts.toml` は、複数 project で機械的に再利用する
小さな知見の advanced store です。journal を無差別にコピーせず、明示昇格済み result
から claim、適用範囲、反例、evidence path を抽出します。

## runops 本体の patch

研究 project と source patch を混ぜません。別 checkout の branch/commit で修正し、
project 固有情報を除いて issue/PR を作ります。詳しくは
[Upstream Integration Layer](layers/upstream.md) を参照してください。
