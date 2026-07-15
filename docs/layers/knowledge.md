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

- `CURRENT.md`: active question、現在判断、次の一手だけを置く mutable な入口。
- `journal/active.md`: append-only。文字数上限に達したら原文のまま numbered segment へ移す。
- `results/`: 人が残すと決めた解析だけ。説明は result ごとに `README.md` 1 枚。
- `artifacts/`: CSV、JSON、画像、script 等の実体。Markdown は禁止。
- `.runops/work/`: goal 実行中の一時出力。Git 管理せず、active research memory に数えない。

既定 budget は `runops.toml` の `[research.workspace]` で変更できます。

```toml
[research.workspace]
current_chars = 20000
journal_segment_chars = 64000
result_readme_chars = 30000
active_results = 8
result_artifact_files = 50
result_artifact_bytes = 209715200
```

`runo research status` は Unicode 文字数、active result 数、artifact の件数と bytes を
機械的に測ります。`runo research check` は budget 超過、artifact 内 Markdown、symlink、
論理名が同じ複数形式を検査します。

```bash
runo research append "observation" "..."
runo research rotate --force
runo research new-result dust-release
runo research archive R0001-dust-release
runo research restore R0001-dust-release
```

archive/restore は rename による可逆操作です。自動削除は行いません。

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
