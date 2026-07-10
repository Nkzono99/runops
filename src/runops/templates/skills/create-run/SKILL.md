---
name: create-run
description: Create runs or expand a survey from cases. Use when generating simulation runs with runo runs create or runo runs sweep.
---

# Run / Survey を生成する

## 手順

1. 使用するケースの case.toml を確認する
2. 単一 run か survey (パラメータスイープ) かを判断する
3. run を生成する
4. 生成結果を確認する

## 単一 Run の生成

```bash
# 生成先ディレクトリへ移動して実行
cd runs/test/basic
runo runs create <case_name>

# または --dest で生成先を指定
runo runs create <case_name> --dest runs/test/basic
```

生成される run:
```
runs/test/basic/Rxxxxxxxx-xxxx/
  manifest.toml      # 状態・由来・provenance (正本)
  input/             # 入力ファイル (case から自動生成)
  submit/            # job.sh (自動生成)
  work/              # 実行時出力用 (空)
  analysis/          # 解析結果用 (空)
```

## Survey の展開

survey.toml がある場合、パラメータの直積で複数 run を一括生成する。

```bash
# survey.toml のあるディレクトリを指定
runo runs sweep runs/sheath/angle_scan

# または cwd で
cd runs/sheath/angle_scan
runo runs sweep
```

### survey.toml の準備

survey.toml が未作成の場合は、先にケースと survey を作成する:

```bash
# ケース作成時に --survey で同時生成
runo case new my_case -s emses --survey

# または既存ケースに survey を追加
mkdir -p runs/<survey_name>
# survey.toml を作成 (フォーマットは {{ skill_prefix }}survey-design スキル参照)
```

### survey.toml の例

```toml
[survey]
name = "angle sweep"
base_case = "emses/my_case"
simulator = "emses"
launcher = "default"

[axes]
"species[2].ray_zenith_angle_deg" = [0, 20, 40, 60, 80]
"tmgrid.dt" = [0.5, 1.0]

[naming]
display_name = "angle{%raw%}{{ray_zenith_angle_deg}}{%endraw%}_dt{%raw%}{{tmgrid_dt}}{%endraw%}"

[job]
partition = "compute"
nodes = 4
ntasks = 32
walltime = "02:00:00"
```

この例では 5 x 2 = 10 個の run が生成される。

## 生成結果の確認

```bash
# run 一覧を表示
runo runs list
runo runs list runs/sheath/angle_scan

# 生成数と設定を確認
runo runs status
```

## 生成後の次ステップ

```bash
# 単一 run を投入
cd runs/test/basic/Rxxxxxxxx-xxxx
runo runs submit -qn <partition>
```

survey 全体の投入はここから直接行わず、必ず `{{ skill_prefix }}run-all` へ委譲する。
production / large survey は proposal の pilot と review の `Decision: EXPAND` が揃うまで
full submit しない。`--yes` はこの gate を省略しない。

## 注意

- run ディレクトリを手で作らない (必ず `runo runs create` / `runo runs sweep` を使う)
- manifest.toml を手動編集しない
- input/ や submit/job.sh を直接作らない
- survey の run 数にかかわらず bulk submit は `{{ skill_prefix }}run-all` を使う
- `runo runs submit --dry-run --all` で投入前に確認できる

## `{{ skill_prefix }}note` で残すべきこと

run / survey 生成の前後で lab notebook に記録する:

- 何 run 生成したか (件数, 内訳, 命名規則)
- 想定総コスト (core-h, walltime)
- どの case を base にしたか, 上書きしたパラメータの一覧
- sweep 軸の意味付け (e.g. "vti を 1-19 eV にしたのは…")
- 投入前の commit hash (`git rev-parse HEAD`)

```bash
runo notes append "Series A sweep 生成" - <<'EOF'
runs/series_A_flat_plate/ に 10 run.
base case: cases/emses/flat_plate, sweep 軸: ions[0].vti = 1..19 eV.
display_name: vti{vti}.
total core-h ≈ 64k. snapshot commit: 53a7e62.
EOF
```
