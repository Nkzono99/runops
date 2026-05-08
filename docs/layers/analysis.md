# Analysis Layer

この文書は runops の解析・可視化レイヤの正本です。
[docs/toml-reference.md](../toml-reference.md) は個別ファイル形式の参照、`$analyze` skill は実行手順、
`$summarize-script` skill は project `summarize.py` 作成の入口として扱い、
置き場所・成果物・運用ルールで迷った場合はこの文書を優先します。

## 目的

Analysis layer は、simulation output から研究判断に使える軽量な成果物を作り、
run / survey / cross-run comparison の由来を後から復元できるようにする層です。

この層は raw output 置き場ではありません。大容量の simulator output は `work/` に残し、
解析に使う要約、図、集計表、比較 script、publication export だけを curated output として置きます。

## 置き場所

| 対象 | 置き場所 | 役割 |
|------|----------|------|
| run 単体の解析 | `runs/<path>/R*/analysis/` | その run に閉じた curated output |
| run 単体の要約 | `runs/<path>/R*/analysis/summary.json` | `runo analyze summarize` が生成する key metrics |
| run 単体の図 | `runs/<path>/R*/analysis/figures/` | `summary.json` から参照できる run-local figure |
| run 単体の試行錯誤 | `runs/<path>/R*/analysis/scratch/` | 一時解析。Git 管理しない |
| survey 集計 | `runs/<survey>/summary/` | 1 survey 配下の run 群の集計 |
| survey plot | `runs/<survey>/summary/plots/` | `runo analyze plot` が生成する survey-local plot |
| cross-run 比較 | `analysis/cross_run/<comparison_id>/` | 複数 survey / 複数 run / 手書き script をまたぐ比較 workspace |
| 比較専用 script | `analysis/cross_run/<comparison_id>/scripts/` | その比較だけに閉じる script |
| 比較データ・図 | `analysis/cross_run/<comparison_id>/data/`, `figures/` | CSV/JSON/contact sheet/比較図 |
| 長文レポート | `notes/reports/<topic>.md` | refined な解析記事。何度改稿してよい |
| 時系列ログ | `notes/YYYY-MM-DD.md` | 解析中の観察・判断・図の読み取り |
| publication bundle | `exports/papers/<paper-id>/<export-name>/` | paper repo に渡す snapshot |

使い分けの原則:

- run の状態、job 履歴、provenance は [Execution Kernel](execution-kernel.md) の
  `manifest.toml` に残し、Analysis Layer では成果物から参照する。
- run に閉じるものは `runs/<run>/analysis/` に置く。
- 1 survey に閉じる集計は `<survey>/summary/` に置く。
- 複数 survey / 複数系列 / 手作業の比較 script を束ねるものは project root の `analysis/cross_run/` に置く。
- 読み物としての解釈は `notes/reports/`、時系列の作業記録は `notes/` に置く。
- 一時的な試行錯誤は `analysis/scratch/` に置き、curated output を上書きしない。

## コマンド

| コマンド | 役割 |
|----------|------|
| `runo analyze summarize [RUN]` | completed run から `analysis/summary.json` を作る |
| `runo analyze collect <survey_dir>` | survey 配下の既存 `summary.json` を集めて `<survey_dir>/summary/` に出す |
| `runo analyze plot <survey_dir>` | `survey_summary.json` 由来の列で survey plot を作る |
| `runo analyze new-comparison <name> --source <path>` | `analysis/cross_run/<id>/` を scaffold する |
| `runo analyze export <run-or-survey> --paper <paper-id>` | run/survey の解析成果を publication bundle にする |

`collect` は既存の `analysis/summary.json` を集めます。
completed run に summary が無い場合は missing summary として記録し、自動では `summarize` しません。
先に必要な run で `runo analyze summarize` を実行してください。

## Run-Level Summary

`runo analyze summarize` は Adapter の `summarize()` を実行し、
必要に応じて project script の `summarize(run_dir, base_summary)` で拡張した結果を
`analysis/summary.json` に保存します。

project script の探索順:

1. `cases/<case>/summarize.py`
2. `cases/<simulator>/<case>/summarize.py`
3. `scripts/summarize.py`

新規 project では `cases/<simulator>/<case>/summarize.py` を推奨します。
custom metric、2D colormap、slice 図、分布比較用の figure metadata が必要な場合は
`$summarize-script` skill でこの hook を設計します。

最小例:

```python
from pathlib import Path


def summarize(run_dir: Path, base_summary: dict) -> dict:
    summary = dict(base_summary)
    summary["ion_flux_max"] = compute_ion_flux(run_dir)

    fig_dir = run_dir / "analysis" / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    plot_path = fig_dir / "potential_profile.png"
    make_plot(run_dir, plot_path)

    summary.setdefault("figures", [])
    summary["figures"].append(
        {
            "path": "figures/potential_profile.png",
            "caption": "Potential profile along z-axis",
        }
    )
    return summary
```

`summary.json` の schema は固定しません。Adapter と project script が任意の key を追加できます。
ただし `figures` は以下の規約に従います。

| Field | 必須 | 説明 |
|-------|------|------|
| `figures[].path` | yes | `analysis/` からの相対 path |
| `figures[].caption` | yes | 図の説明 |
| `figures[].kind` | no | `line`, `colormap`, `contact_sheet` など |
| `figures[].quantity` | no | `density`, `potential`, `rhobk` など |
| `figures[].plane` | no | `xy`, `xz`, `yz`, `3d`, `none` など |
| `figures[].step` | no | `final`, step number, frame id など |

`kind` 以降は optional metadata ですが、2D colormap や分布比較を後で集めたい場合は
できるだけ入れてください。

## Figure Design

run-level `summarize.py` は数値 metric だけでなく、2D カラーマップ、slice 図、履歴 plot などを生成してよいです。
比較しやすくするため、同じ survey family では以下を揃えます。

- figure filename
- quantity name
- slice plane / slice index
- frame / step
- color range
- normalization
- axis labels / units
- overlay の意味

run-level 図は atomic artifact にします。
複数 run を並べた contact sheet や系列比較図は、`figures_index.json` を読んで
`<survey>/summary/plots/` または `analysis/cross_run/<id>/figures/` に生成します。

## Metric Schema Design

`runo analyze collect` は `summary.json` を flat 化し、manifest 由来の
`origin.*`, `classification.*`, `variation.*`, `param.*` などの列と結合します。
cross-series 比較のため、同じ geometry / survey family では同じ metric key を常に出してください。

推奨:

- scalar metric は単位が分かる名前にする。例: `potential_final_v`, `charge_abs_max_c`
- nested metric は意味のある group にする。例: `output_counts.hdf5_fields`
- 物理的に定義できない metric は、非出力にするか、常に同じ sentinel (`null` / `nan`) を出して列存在を維持する。
- case 間で比較する metric は、すべての case の `summarize.py` で同名 key を出す。
- list / dict は CSV では JSON 文字列になる。plot したい値は scalar にする。

避けること:

- run ごとに ad hoc な key 名を増やす。
- model 名や case 名を metric key に埋め込む。
- 図だけ作って `summary.json` や note に evidence path を残さない。

## Survey Collection

`runo analyze collect <survey_dir>` は `<survey_dir>/summary/` に以下を生成します。

| File | 説明 |
|------|------|
| `summary/survey_summary.csv` | flat 化した run 一覧。CSV で比較しやすい表 |
| `summary/survey_summary.json` | run ごとの summary 原本、状態数、readiness、numeric stats、warning |
| `summary/figures_index.json` | 各 run の figure path / caption の索引 |
| `summary/survey_summary.md` | 人が読むための短い Markdown report |
| `summary/plots/*.png` | `runo analyze plot` が生成する図 |

収集ルール:

- `analysis/summary.json` がある run はそれを利用する。
- completed run でも `analysis/summary.json` が無い場合は missing summary として記録する。
- completed 以外の run は state count には含めるが、summary が無ければ集計対象外。
- Adapter の `required_outputs()` / `detect_status()` から `analysis_status = ready | incomplete | unknown` を付ける。
- `summary.json` の `status` が `completed` 以外、または `partial = true` の場合は partial summary として扱う。
- `summary.figures[]` と `analysis/figures/` 配下の画像を `figures_index.json` に索引化する。

## Survey Plot

`runo analyze plot` は `survey_summary.json` の各 run から `flat_metadata` と `flat_summary`
を統合した表を読み、指定列で可視化します。

```bash
runo analyze plot runs/sheath/angle_scan --list-columns
runo analyze plot runs/sheath/angle_scan --list-recipes
runo analyze plot runs/sheath/angle_scan --recipe completion-vs-dt
runo analyze plot runs/sheath/angle_scan --x param.angle --y ion_flux --group param.seed
```

ルール:

- `--list-columns` で利用可能列を確認する。
- Adapter が `default_plot_recipes()` を持つ場合は `--list-recipes` / `--recipe` を優先する。
- `x`, `y`, `group_by` は fallback column list を recipe に持てる。
- `y` は数値列が必要。
- `--kind auto` は x が数値なら `line`、非数値なら `bar` を選ぶ。
- `line` / `scatter` は numeric x が必要。
- default 出力先は `summary/plots/<y>_vs_<x>.png`。

## Cross-Run Comparison

複数 run / survey をまたぐ比較・可視化では、比較単位の成果物を
project root の `analysis/cross_run/<comparison_id>/` にまとめます。

```bash
runo analyze new-comparison "no_plate vs flat_plate" \
  --source runs/no_plate_scan \
  --source runs/flat_plate_scan
```

生成される構造:

```text
analysis/cross_run/<comparison_id>/
  manifest.toml
  README.md
  scripts/
  data/
  figures/
```

`manifest.toml` は比較の正本です。source run / survey / path、比較専用 script、
生成 data、figures、主要パラメータを追記していきます。

使い分け:

- 1 survey 内の単純集計は `<survey>/summary/`。
- 複数 survey、複数 model family、論文図、contact sheet、手書き比較 script は `analysis/cross_run/<id>/`。
- project-wide reusable script は root の `scripts/` に置き、比較に閉じる script は workspace の `scripts/` に置く。

## Notes, Reports, And Evidence

解析結果は成果物だけでなく、判断の文脈も残します。

- 時系列の作業ログ、観察、未確認点は `notes/YYYY-MM-DD.md` に残す。
- 図を生成したら note に Markdown image として埋めるか、代表図 / contact sheet と artifact path を残す。
- 図の caption には物理量、slice/frame、単位、color scale、normalization、overlay の意味を書く。
- `Observation:` と `Interpretation:` と `Caveat:` を分ける。
- まとまった解析記事は `notes/reports/<topic>.md` に昇格する。
- 再利用可能な atomic fact だけ `.runops/insights/` / `.runops/facts.toml` に昇格する。

すべての数値・図・結論には evidence path を付けてください。
最低限、run / survey、summary、figure、script、CSV/JSON、manifest のどれかに辿れるようにします。

## Publication Export

`runo analyze export <run-or-survey> --paper <paper-id>` は paper repo に渡しやすい
project 側 snapshot を `exports/papers/<paper-id>/<export-name>/` に生成します。

対象:

- run export: `manifest.toml`, `analysis/summary.json`, `analysis/figures/**`
- survey export: `summary/survey_summary.csv`, `survey_summary.json`, `figures_index.json`,
  `survey_summary.md`, `summary/plots/**`, 参照された run figure 群
- `survey.toml` がある場合は survey export に同梱する。

publication export は成果物の移送用です。解析の正本は run / survey / cross-run workspace 側に残します。
