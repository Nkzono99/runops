---
name: summarize-script
description: Design, create, or refactor project summarize.py hooks for runo analyze summarize. Use when adding case-local metrics, 2D colormaps, slice plots, figure metadata, stable summary.json keys, or distribution comparisons from simulator outputs.
---

# summarize.py を設計・作成する

この skill は project 側の `summarize.py` を作る。目的は、`runo analyze summarize`
で各 run の `analysis/summary.json` と run-local figure を安定して生成し、
後続の `runo analyze collect` / `plot` / cross-run 比較に渡せる形へ整えること。
`runo analyze summarize` は `summary["figures"]` から `analysis/artifacts.toml`
も生成するため、figure metadata は後から Agent / report / export が読む索引になる。

## まず読む

必要な範囲で読む:

1. `runops-reference` skill と `runo analyze --help`
2. `campaign.toml`
3. 対象 case の `case.toml`
4. 対象 survey の `survey.toml`
5. 代表 run の `manifest.toml`
6. 代表 run の `work/` 出力一覧
7. 既存の `cases/**/summarize.py` / `scripts/summarize.py`

## 置き場所

デフォルトは case-local に置く。

```text
cases/<simulator>/<case>/summarize.py
```

複数 case で完全に同じ処理を共有する場合だけ `scripts/summarize.py` を使う。
survey 全体の contact sheet、複数 run を並べる比較図、論文図は
`summarize.py` に入れず、`runo analyze collect` 後に `<survey>/summary/plots/`
または `analysis/cross_run/<comparison_id>/` で作る。

## 必須インタフェース

```python
from pathlib import Path


def summarize(run_dir: Path, base_summary: dict) -> dict:
    summary = dict(base_summary)
    return summary
```

- `base_summary` を破壊的に前提化せず、まず `dict(base_summary)` にコピーする。
- 返り値は JSON serializable にする。
- 画像は `run_dir / "analysis" / "figures"` に保存する。
- `figures[].path` は `analysis/` からの相対 path にする。
- `figures[]` の metadata は `analysis/artifacts.toml` にも反映される。

## 設計ルール

- metric key は survey family 内で安定させる。
- scalar metric には単位がわかる名前を付ける。例: `potential_final_v`,
  `density_peak_m3`, `ion_flux_max_m2_s`。
- case 名、model 名、run_id を metric key に埋め込まない。
- 物理的に定義できない値は、列を消すより `None` / `float("nan")` などで列存在を維持する。
- 2D colormap、slice 図、履歴 plot などを作ってよい。ただし figure metadata を必ず残す。
- 同じ比較系列では filename、quantity、plane、step、color range、normalization、
  axis label、unit を揃える。
- raw output を `analysis/` にコピーしない。`analysis/` には curated output だけを置く。

## figure metadata

`summary["figures"]` は list にする。最低限:

```python
summary.setdefault("figures", [])
summary["figures"].append(
    {
        "path": "figures/density_xz_final.png",
        "caption": "Final density slice on the y-center XZ plane.",
        "kind": "colormap",
        "quantity": "density",
        "plane": "xz",
        "step": "final",
    }
)
```

2D 分布や slice 比較を後で集めるため、`kind`, `quantity`, `plane`, `step` は
できるだけ埋める。

## 実装手順

1. 代表 run を 1-3 個選び、`work/` にどの出力があるか確認する。
2. `analysis.md` に沿って、run-local metric と run-local figure だけを設計する。
3. metric schema を決める。`collect` で比較したい値は scalar key にする。
4. `cases/<simulator>/<case>/summarize.py` を作成または更新する。
5. 対象 run で `runo analyze summarize <run>` を実行する。
6. `analysis/summary.json` を読み、metric と `figures` metadata を確認する。
7. `analysis/artifacts.toml` を読み、figure path / title / description / script / data を確認する。
8. survey がある場合は `runo analyze collect <survey>` を実行し、
   `summary/survey_summary.csv`, `summary/survey_summary.json`, `summary/artifacts.toml` を確認する。
9. 必要なら `runo analyze plot <survey> --list-columns` で plot 可能な列を確認する。
10. 結果と evidence path を `{{ skill_prefix }}note` に残す。
11. 研究判断が変わる場合だけ `{{ skill_prefix }}research-agenda` も更新する。

## 最小テンプレート

```python
from __future__ import annotations

from pathlib import Path
from typing import Any


def summarize(run_dir: Path, base_summary: dict[str, Any]) -> dict[str, Any]:
    summary = dict(base_summary)
    analysis_dir = run_dir / "analysis"
    fig_dir = analysis_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)

    # TODO: read run_dir / "work" outputs and add stable scalar metrics.
    # summary["metric_name_unit"] = value

    return summary
```

## 確認ポイント

- `runo analyze summarize <run>` が例外なく完了する。
- `analysis/summary.json` が JSON として読める。
- `analysis/artifacts.toml` が生成され、代表 figure の意味を復元できる。
- `summary.json` の key が比較したい survey / case 間で揃っている。
- 作った figure path が実在し、`figures[].path` が `analysis/` からの相対 path になっている。
- `runo analyze collect <survey>` 後に必要な列が `survey_summary.csv` に出る。
- 解析の観察と figure path を note に残している。
