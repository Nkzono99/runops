---
name: beach
description: "Use when working with BEACH through runops. Keep this as a thin runops bridge; delegate BEACH-specific config review, case design, diagnosis, output analysis, and visualization to the BEACH Context plugin when it is available."
---

# BEACH runops bridge

この skill は runops 開発リポジトリ側の薄い橋渡しである。BEACH 固有の
長文知識、物理・数値判断、出力解析、可視化 workflow は外部 Codex plugin
`BEACH Context` (`beach-context`) に委譲する。runops 側では run directory、
case/survey 展開、manifest、adapter contract、job.sh 生成、lint/test/docs の
整合性だけを扱う。

## 最初に確認すること

1. 対象 project で `runo plugins --check` または `runo plugins --json` を確認し、
   `beach-context` 推薦と `delegated_capabilities` を見る。
2. 現在の Codex session で `BEACH Context` plugin / skill が利用可能なら、
   `config-review`, `case-design`, `run-diagnose`, `output-analysis`,
   `visualization-script` はそちらを使う。
3. plugin が利用できない場合だけ、この skill の最小情報と現在の project files
   (`case.toml`, `beach.toml`, `manifest.toml`, run output) を根拠にする。

## runops 側で担当すること

- `src/runops/adapters/contrib/beach/adapter.py` の adapter contract、runtime
  resolution、required outputs、summary parsing を保つ。
- `runo runs create`, `runo runs submit`, `runo runs status`,
  `runo analyze summarize`, `runo analyze collect`
  から見た runops workflow を壊さない。
- BEACH project では `runo plugins` が `BEACH Context` / `beach-context` と
  委譲 role を表示することを確認する。
- KUDPC 上で実行やテストを行う場合は KUDPC plugin の routing に従い、login node
  で solver、pytest、可視化、重い解析を直接実行しない。

## 最小 fallback

- 入力は `beach.toml`、runops case は adapter がそれを `work/` に配置する。
- 代表的な output は `summary.txt`、`charges.csv`、`mesh_triangles.csv`、
  `charge_history.csv`、`potential_history.csv`。
- `summary.txt` は runops の完了判定と要約の主な入口である。
- 詳細な parameter 意味、安定性判断、図化手順は plugin または BEACH upstream
  docs を根拠にし、この repository の古い記憶で補完しない。

## 変更時の検証

- Adapter 変更: `tests/test_adapters/test_beach.py`,
  `tests/test_adapters/test_contract.py`
- plugin 推薦変更: `tests/test_application/test_plugins.py`,
  `tests/test_cli/test_plugins.py`, `tests/test_application/test_context.py`,
  `tests/test_mcp/test_tools.py`
- harness 表示変更: `tests/test_harness/test_codex.py`,
  `tests/test_cli/test_init.py`, `tests/test_cli/test_update_harness.py`
