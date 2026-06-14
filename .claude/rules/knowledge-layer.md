# 知識層 (Knowledge Layer)

AI エージェントがシミュレーションを自律的に行うための知識管理。
詳細は `docs/layers/knowledge.md` を参照。

## 知識の種類

| 種類 | 保存先 | 更新方法 |
|------|--------|----------|
| シミュレータ知識 | simulator/environment plugin + `.runops/knowledge/` + 任意の `refs/` fallback mirror | plugin install/update, `runops knowledge source sync`, `runops update-refs` |
| 外部共有知識 | `runops.toml` の `[knowledge]` | `knowledge source attach/sync` |
| 実行環境 | `.runops/environment.toml` | `runops doctor` |
| 研究意図 | `campaign.toml` | ユーザーが記述 |
| 実験知見 (curated) | `.runops/insights/` | `knowledge save` / `knowledge source sync` |
| 構造化知識 (curated) | `.runops/facts.toml` | `knowledge add-fact` / `knowledge facts` |
| lab notebook | `notes/YYYY-MM-DD.md`, `notes/history/YYYY/YYYY-MM-DD.md` | `runops notes append`, `runops notes archive` |
| 長文レポート | `notes/reports/<topic>.md` | 直接編集 (改稿可) |
| 研究判断の台帳 | `research/agenda.md` | 直接編集 (現在判断の更新) |

## 二層構造

- `.runops/insights/` / `.runops/facts.toml` は整理済の永続知見 (上書き可・名前付き・atomic)
- `notes/YYYY-MM-DD.md` は append-only な時系列ログ。古い日次 notebook は `notes/history/YYYY/` に archive する
- `research/agenda.md` は mutable な現在判断の正本。TODO ではなく active question / current decision / paused-killed / 判断が変わる条件を置く
- 価値が出てきたら `notes/reports/` → `.runops/insights/` / `facts.toml` に昇格

## 外部知識ソース

複数プロジェクト間で共有する知識を外部リポジトリとして管理し、project に接続できる。

Simulator / site が外部 Codex plugin を推薦する場合、`runops init` / `runops setup`
と生成 harness に導線を出す。plugin install / enable はユーザー local な Codex
環境の操作であり、runops project state には含めない。
開発ハーネス内の `.claude/agents/emses.md`, `.claude/agents/beach.md`,
`.agents/skills/emses`, `.agents/skills/beach` は runops 側の薄い橋渡しに保ち、
シミュレータ固有の長文 context は MPIEMSES3D / emout / BEACH などの外部 plugin
へ委譲する。

```bash
runops knowledge source attach git shared-kb git@github.com:lab/hpc-shared-knowledge.git
runops knowledge source attach path local-kb ../hpc-knowledge
runops knowledge source sync
runops knowledge source render
```

- `runops init` の対話時は GitHub の `*shared_knowledge*` リポジトリを候補表示し、選択されたものだけ接続
- `runops setup` 時は `runops.toml` に設定された知識ソースを自動同期
