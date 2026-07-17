---
name: summarize-script
description: Use when the requested outcome is a case-local summarize.py that produces specified stable metrics or run-local figures.
---

# requested metricをstableなsummarize hookにする

## 実行契約

- **Goal**: 指定metric / figureを`runo analyze summarize`のstable outputにする
- **Done**: hook、代表runの`summary.json`、`artifacts.toml`、必要なcollect列を報告できる
- **Budget**: 一つのcase、requested metric / figure、代表run 1-3個
- **Invariant**: raw outputを保持し、stable keyとfigure schemaを揃え、cross-run解析をhookへ入れない

## Source routing

| information gap | source |
|---|---|
| requested observable | `campaign.toml`, 対象`case.toml` / `survey.toml` |
| available output | 代表runの`manifest.toml`と必要な`work/`一覧 |
| existing convention | 対象case、次に`cases/**/summarize.py` |
| exact interface | `runo analyze summarize --help` |

既定の配置は`cases/<simulator>/<case>/summarize.py`。複数caseで完全に同じ処理だけ
`scripts/summarize.py`へ共有する。survey plotとpaper figureはcollect後のsurvey summaryまたは
`research/results/RNNNN-*/artifacts/`に置く。

## Runtime contract

```python
from pathlib import Path
from typing import Any

def summarize(run_dir: Path, base_summary: dict[str, Any]) -> dict[str, Any]:
    summary = dict(base_summary)
    return summary
```

- return valueはJSON serializableにする
- scalar keyはsurvey family内で安定させ、単位が分かる名前にする
- undefined valueでも比較列を保てる表現を選ぶ
- curated imageは`analysis/figures/`、`figures[].path`は`analysis/`からの相対pathにする
- figure metadataにはcaption、kind、quantity、plane、stepなど比較に必要な意味を持たせる
- raw outputを`analysis/`へ複製しない

## Outcome loop

代表runで`runo analyze summarize <run>`を実行し、requested key、figure path、
`analysis/artifacts.toml`を確認する。survey比較がDoneに含まれる場合だけ
`runo analyze collect <survey>`で列の安定性を確認する。別metric、cross-run plot、knowledge昇格、
journal追記は独立したGoalとして扱う。
