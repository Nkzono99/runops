# Documentation

runops の文書は、最初から順番に読むマニュアルではありません。目的に合う入口から
必要なページだけ参照してください。

## 利用者向け

| 目的 | 最初に読む文書 |
|---|---|
| project を始める | [AI エージェントではじめる](get-started-with-agent.md) |
| Agent に任せる範囲を確認する | [Agent User Guide](agent-user-guide.md) |
| project の問題を検査する | [Project Health Check](project-health.md) |
| runops 更新時の移行を確認する | [Migration Guide](migrations/README.md) |

## Project state を調べる

[Layer Docs](layers/README.md) が全体の索引です。

| 対象 | 文書 |
|---|---|
| campaign / case / survey | [Experiment Layer](layers/experiment.md) |
| run / manifest / submit / sync | [Execution Kernel](layers/execution-kernel.md) |
| CLI / action / human gate | [Interface Layer](layers/interface.md) |
| 解析・可視化成果物 | [Analysis Layer](layers/analysis.md) |
| current / journal / retained result | [Research Layer](layers/research.md) |
| plugin / materials / reusable knowledge | [Knowledge Layer](layers/knowledge.md) |
| Agent harness / skills / rules | [Harness Layer](layers/harness.md) |
| feedback / local patch / upstream | [Upstream Integration](layers/upstream.md) |

## リファレンス

以下は通読より検索に向く文書です。

| 調べるもの | 文書 |
|---|---|
| TOML schema と field | [TOML リファレンス](toml-reference.md) |
| 内部 module と設計 | [アーキテクチャ](architecture.md) |
| Adapter / Launcher / site 拡張 | [拡張ガイド](extending.md) |
| MCP tool と contract | [MCP Provider](mcp.md) |
| simulator knowledge bundle | [Simulator KB Spec](simulator-kb-spec.md) |
| session replay | [Demo Replay](demo-replay.md) |

詳細仕様の正本は [SPEC.md](../SPEC.md)、開発用 command 一覧は
[.codex/rules/commands.md](../.codex/rules/commands.md) です。

## 文書を更新する人へ

- README は概要と最短導線に限定する。
- 手順は入門、運用規則は Layer docs、field 定義は reference に置く。
- 同じ説明を複数ページへコピーせず、正本へリンクする。
- 長い列挙は表や箇条書きにし、段落には一つの論点だけを書く。
- technical reference は短さより、冒頭の索引と検索しやすい見出しを優先する。
