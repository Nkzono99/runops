# 研究記憶と知識層

runops の context は `Execution Kernel`、`Research Workspace`、`Agent Gateway`、
`Operator/Developer` に分け、依存方向を
`core -> application -> interfaces/infrastructure` に保ちます。

runops project の研究記憶は、長く放置したかではなく active な情報量で管理します。
AI に重要度判定や自動要約を委ねず、原文を保つ rotation と人による result 昇格を
組み合わせます。

```text
research/
  CURRENT.md
  journal/
    active.md
    archive/J0001.md
  results/
    R0001-topic/
      README.md
      manifest.toml
      artifacts/
  archive/results/
.runops/work/<goal-id>/
```

- `CURRENT.md`: active question、現在判断、次の一手だけを置く mutable な入口。既定 50 行を目安に保つ。
- `journal/active.md`: append-only。`--kind` / `--subject` で Experiment / Survey / Run に軽く紐付け、文字数上限に達したら原文のまま numbered segment へ移す。
- `results/`: 人が残すと決めた解析だけ。説明は Result ごとに `README.md` 1 枚、claim と evidence edge は `manifest.toml`。
- `artifacts/`: CSV、JSON、画像、script 等の実体。Markdown は禁止。
- `.runops/work/`: goal 実行中の一時出力。Git 管理せず、active research memory に数えない。

既定 budget は `runops.toml` の `[research.workspace]` で変更できます。

```toml
[research.workspace]
current_chars = 20000
current_lines = 50
current_path_references = 10
current_chronological_headings = 3
journal_segment_chars = 64000
result_readme_chars = 30000
active_results = 8
result_artifact_files = 50
result_artifact_bytes = 209715200
```

`current_chars` は hard limit です。行数、path 参照数、日付・時刻で始まる見出し数は
compact guidance で、超過しても warning に留まります。時系列は journal、残す詳細解析は
`results/`、網羅的な artifact provenance は export/source index に分けます。

`runo research status` は Unicode 文字数、行数、path 参照、時系列見出し、active result 数、
artifact の件数と bytes を機械的に測ります。`runo research check` は hard budget 超過、
artifact 内 Markdown、symlink、論理名が同じ複数形式を検査します。

```bash
runo research append "observation" "..."
runo research rotate --force
runo research new-result dust-release
runo research seal R0001-dust-release \
  --claim "..." --outcome supported \
  --selection-reason "Why this source supports the claim" \
  --evidence-run R2026...
runo research check-result R0001-dust-release
runo research archive R0001-dust-release
runo research restore R0001-dust-release
```

archive/restore は rename による可逆操作です。自動削除は行いません。

evidence の採否は Result が所有し、Run に project-global な selected flag を置きません。
TestAttempt の T ID と `.runops/test-runs/**` は scientific Result evidence にできません。
case / survey の `notes.md` と Run `analysis/notes.md` は legacy な分散 narrative として
`runo lint` が warning を出します。provisional prose は `.runops/work/`、時系列は journal、
現在判断は CURRENT、残す説明は Result README に集約します。

## 旧 project の移行

```bash
runo research migrate-legacy --dry-run
runo research migrate-legacy
runo research migrate-legacy --restore
```

旧 `notes/`、`analysis/cross_run/`、`analysis/**/*.md`、`exports/`、`_handoff/`、
旧 research ledger と HarnessOps metadata を `research/archive/legacy/` へ内容そのままで
移します。`MIGRATION.json` が移動元と移動先を記録するため復元できます。

外部共有知識、simulator plugin、`.runops/insights/`、`.runops/facts.toml` は別の
再利用層です。project の作業経緯や解析 narrative をそこへ無差別に複製しません。
