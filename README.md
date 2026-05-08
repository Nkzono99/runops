# runops

runops は、HPC / Slurm 上のシミュレーション研究を **AI エージェントと進める**
ための実行基盤です。

人間が多数の CLI コマンドを覚えて日々叩くための道具ではありません。CLI は
存在しますが、それは Agent が project state を安全に読み書きするための
execution kernel です。人間は研究意図、制約、判断、確認を与え、Agent が
`campaign.toml`、case、survey、run、manifest、notes、analysis を整えます。

最初に読むべき入口は [AI エージェントではじめる](docs/get-started-with-agent.md) です。

## なぜ runops が必要か

HPC シミュレーション研究では、研究そのものよりも周辺の運用が重くなりがちです。

- 入力ファイルと投入スクリプトがどの仮説から来たのか分からなくなる
- survey のパラメータ、run directory、Slurm job、解析結果がばらける
- 失敗 run の retry や continuation の由来が追えなくなる
- ノート、知見、論文用 export、共有知識が別々の場所で腐る
- AI Agent に任せようとしても、どこを触ってよくてどこが正本か伝わらない

runops はこの問題を、単なる CLI ではなく **Agent が扱える研究 project state** として
整理します。

## AI 前提の作業ループ

日常運用の主役は、CLI ではなく Agent との会話です。

1. 人間が研究意図を伝える
2. Agent が `campaign.toml`、case、survey を設計する
3. runops が run directory と `manifest.toml` を生成する
4. Agent が投入前 plan、対象 run、queue、資源量を提示する
5. 人間が高コスト操作や破壊的操作だけ確認する
6. Agent が状態同期、log 読解、解析、notebook、report、知見整理を進める
7. 判断が変わったら `research/agenda.md` と次の survey に戻す

このループの具体的な始め方は
[docs/get-started-with-agent.md](docs/get-started-with-agent.md) を見てください。
全体像は [docs/project-flow.md](docs/project-flow.md) に図でまとめています。

## 人間と Agent の分担

人間が主に行うこと:

- 研究テーマ、仮説、探索範囲、観測量を言語化する
- ベース入力や物理的制約の意図を伝える
- 初回 bulk submit、retry、archive、delete などの gate を確認する
- 結果の科学的な解釈や次の判断をレビューする

Agent が主に行うこと:

- project context、既存 notes、materials、refs、environment を読む
- `campaign.toml`、case、survey の草案を作る
- run 生成、submit、sync、status、log、analysis を runops 経由で進める
- `notes/YYYY-MM-DD.md`、`notes/reports/`、`research/agenda.md` を更新する
- runops 本体への改善要望や local patch 候補を整理する

CLI を手で直接使う場面は、bootstrap、debug、CI、Agent 実装確認、緊急時の
operator 作業に限るのが基本です。必要な場合の詳細は
[Interface Layer](docs/layers/interface.md) に移しました。

## コア設計思想

runops の中心にある思想は、以下の分離です。

- **run directory が日常運用の主単位**
  すべての実行、状態、解析、履歴は `runs/.../RYYYYMMDD-NNNN/` を基点に扱う。

- **`manifest.toml` が run の正本**
  run id、状態、由来、job id、Slurm 状態、provenance、parameter snapshot を
  manifest に記録する。notes や会話ログは補助情報であり、正本ではない。

- **不変と可変を分ける**
  `run.id` は不変。path は分類・整理のために変わりうる。run の由来と
  parameter snapshot を残すことで、移動や再分類に耐える。

- **case / survey / run を混ぜない**
  case は reusable な基本定義、survey は parameter expansion、run は実行単位。
  run の input を場当たり的に直さず、再利用すべき変更は case / survey に戻す。

- **Simulator Adapter に閉じ込める**
  simulator 固有の input rendering、runtime 解決、出力検出、summary は Adapter が持つ。
  core は simulator に依存しない。

- **Launcher Profile に閉じ込める**
  `srun` / `mpirun` / `mpiexec`、site 固有の Slurm directive、module load は
  Launcher と site profile に寄せる。Python は MPI rank の wrapper にならない。

- **Agent harness は project state の一部**
  `.claude/`、`.agents/`、`.codex/`、`AGENTS.md`、`CLAUDE.md` は、Agent に
  触ってよい場所、確認すべき gate、使う skill を伝える運用面の正本です。

## Project が memory になる

`runo init` で生成される project は、単なる実行ディレクトリではなく、
人間と Agent の共有 memory です。

```
project/
  campaign.toml          # 研究意図、仮説、変数、観測量
  cases/                 # reusable case definitions
  runs/                  # survey と run directory
  notes/                 # append-only lab notebook と refined reports
  research/agenda.md     # 現在の研究判断
  materials/             # papers, manuals, figures, snippets
  refs/                  # simulator docs / external knowledge sources
  .runops/               # environment, generated Agent context, facts
  .claude/ .agents/ .codex/
                         # Agent harness, skills, rules, permissions
```

この構造の意味は [レイヤー一覧](docs/layers/README.md) から辿れます。

## Safety Gates

runops は AI 前提ですが、何でも自動化するという意味ではありません。
次の操作では人間の確認を挟みます。

- 初回または高コストな `submit --all`
- queue、QOS、node 数、walltime、memory を増やす retry
- `cancel`、`archive`、`purge-work`、`delete`
- 研究仮説や campaign の意味が変わる編集
- project-state migration や harness 更新

Agent は確認前に、対象 run、queue、資源量、想定 core-hour、変更理由を提示します。

## 最小セットアップ

新規 project:

```bash
uvx --from runops runo init
source .venv/bin/activate
runo doctor
```

既存 project:

```bash
uvx --from runops runo setup https://github.com/user/my-project.git
cd my-project
source .venv/bin/activate
runo doctor
```

ここまで終わったら、CLI を順に叩くのではなく Agent に研究内容を渡します。
依頼例は [docs/get-started-with-agent.md](docs/get-started-with-agent.md) にあります。

## runops 自体の開発

```bash
git clone https://github.com/Nkzono99/runops.git
cd runops
uv sync --dev

uv run pytest
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/
```

## ドキュメント

- [AI エージェントではじめる](docs/get-started-with-agent.md) — 最初の実用導線
- [AI Agent 運用概念図](docs/project-flow.md) — project と Agent の見る世界
- [Agent ユーザーガイド](docs/agent-user-guide.md) — Agent が守る基本ルール
- [Interface Layer](docs/layers/interface.md) — CLI / action surface / human gate の境界
- [レイヤー一覧](docs/layers/README.md) — project state の責務分離
- [実験層](docs/layers/experiment.md) — campaign / case / survey の設計正本
- [Execution Kernel](docs/layers/execution-kernel.md) — run / submit / sync / manifest
- [解析層](docs/layers/analysis.md) — 解析・可視化成果物の運用
- [研究判断層](docs/layers/research.md) — `research/agenda.md`
- [知識層](docs/layers/knowledge.md) — notes / materials / refs / knowledge
- [ハーネス層](docs/layers/harness.md) — Agent instructions / skills / rules
- [Upstream 連携層](docs/layers/upstream.md) — local patch / feedback / PR
- [Project health check](docs/project-health.md) — `runo lint` による検査
- [TOML リファレンス](docs/toml-reference.md) — 設定ファイルのフィールド定義
- [アーキテクチャ](docs/architecture.md) — 内部設計とモジュール構成
- [拡張ガイド](docs/extending.md) — Adapter / Launcher の追加方法
- [移行ガイド](docs/migrations/README.md) — runops 更新時の migration
- [SPEC.md](SPEC.md) — 詳細仕様

## ライセンス

Apache-2.0
