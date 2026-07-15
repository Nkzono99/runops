---
name: analyze
description: Analyze completed runs and collect survey results. Use after runs complete to summarize findings.
---

# 完了した Run の結果を解析・集計する

解析・可視化成果物の置き場所と運用ルールの正本は
`runops-reference` skill と `runo analyze --help`。

## 個別 run の要約

```bash
cd <run_dir>
runo analyze summarize
```

## survey の集計

```bash
runo analyze collect $ARGUMENTS
```

## survey の plot

```bash
runo analyze plot $ARGUMENTS --list-columns
runo analyze plot $ARGUMENTS --list-recipes
runo analyze plot $ARGUMENTS --recipe completion-vs-dt
runo analyze plot $ARGUMENTS --x param.some_axis --y some_metric
```

## cross-run 比較 workspace

複数 run / survey をまたぐ比較では、図・中間表・比較専用 script を
`runo analyze new-comparison` で `research/results/RNNNN-<comparison_id>/` にまとめる。
説明は `README.md` 1 枚、data / figure / script は `artifacts/` 以下に置く。

```bash
runo analyze new-comparison "landau model comparison" --source runs/series_a
```

一時的な試行錯誤や run-local な下書きは `analysis/scratch/` に置いてよい。
複数 run / survey をまたぐ成果物として残す段階で cross-run workspace に昇格する。

## 論文向け export

```bash
runo analyze export $ARGUMENTS --paper draft-a
```

## 手順

1. `runo analyze summarize` で各 run の要約を生成する
2. survey の場合は `runo analyze collect <dir>` を実行する
3. `collect` が生成した `summary/survey_summary.csv`, `summary/survey_summary.json`, `summary/artifacts.toml`, `summary/survey_summary.md` を確認する
4. まず `runo analyze plot <dir> --list-recipes` を試し、使える recipe があれば `--recipe` を優先する
5. recipe が無い場合は `runo analyze plot <dir> --list-columns` で列を確認し、`--x/--y` を指定して図を生成する
6. run-local な試行錯誤は `analysis/scratch/` に置き、複数 run / survey をまたぐ比較は `runo analyze new-comparison` で workspace を作る
7. completed run に `analysis/summary.json` が無い場合、先に対象 run で `runo analyze summarize` を実行する
8. paper repo に渡す段階では `runo analyze export <run-or-survey> --paper <paper-id>` で `exports/papers/` に束ねる
9. 結果の概要と注目すべき傾向を報告する
10. 知見があれば `{{ skill_prefix }}learn` で保存する

## custom summarize.py が必要な場合

Adapter の summary だけでは足りない metric、2D colormap、slice 図、分布比較用の
figure metadata が必要な場合は、先に `{{ skill_prefix }}summarize-script` で
case-local な `cases/<simulator>/<case>/summarize.py` を作る。
