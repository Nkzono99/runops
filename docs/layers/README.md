# Layer Docs

runops の project 側状態は複数の層に分かれます。
層ごとの責務で迷った場合は、以下の文書を正本として参照してください。

ここでいう Layer は、単なる runops 実装内部の module ではなく、project 運用上の
正本・生成物・更新ルールが分かれる面です。Layer として扱う目安は次の通りです。

- project 側に永続的な状態、生成物、または正本がある
- 人間と Agent の両方が読み書き・参照する
- 他の層と混ぜると再現性、判断、handoff、upstream 化が壊れる
- 置き場所、更新方法、昇格/同期ルールを明文化する価値がある

## 全体像

![runops project layers](../figures/layers/overview.png)

図では、日常運用の流れを `研究意図 -> 探索設計 -> 実行 -> 解析・可視化 -> 判断・知識`
として描いています。各 Layer はこの流れの一部を担当しますが、重要なのは
「どの状態がどこを正本にするか」を混ぜないことです。

Agent は Interface Layer と Harness Layer の制約を通して project state に触り、
Experiment / Execution / Analysis / Research / Knowledge の各 Layer にある正本を
読み書きします。Upstream Integration Layer は、運用中に見つかった runops 本体への
改善や local patch を project の研究状態から切り離して扱うための境界です。

| Layer | Canonical Doc | 役割 |
|-------|---------------|------|
| Interface Layer | [interface.md](interface.md) | Agent / harness / operator が project state に触る command surface と gate |
| Experiment Layer | [experiment.md](experiment.md) | `campaign.toml` → `case.toml` → `survey.toml` の実験設計正本 |
| Execution Kernel | [execution-kernel.md](execution-kernel.md) | run / submit / sync / manifest / provenance の実行状態正本 |
| Analysis Layer | [analysis.md](analysis.md) | 解析・可視化成果物、summary、survey 集計、cross-run 比較 |
| Research Layer | [research.md](research.md) | `research/agenda.md` による現在判断の台帳 |
| Knowledge Layer | [knowledge.md](knowledge.md) | Agent が再利用する知識、notes、materials、`.runops/insights/` |
| Harness Layer | [harness.md](harness.md) | Agent の手順、権限、skills、rules、project-local harness |
| Upstream Integration Layer | [upstream.md](upstream.md) | runops local patch、feedback issue、PR、update / migration の境界 |

`src/runops/cli/` は Interface Layer の実装の一部ですが、module 構成としての
`cli/`, `core/`, `adapters/`, `launchers/`, `slurm/` は runops 実装内部の
architecture layer です。実装構造は [architecture.md](../architecture.md) を正本とします。

runops 更新で project 側状態を移行する手順は layer そのものではなく、
Upstream Integration Layer に付随する運用です。
詳細は [../migrations/README.md](../migrations/README.md) を参照してください。

各 layer が Agent から読める状態に保たれているかは cross-layer の health check として
[../project-health.md](../project-health.md) と `runo lint` を使います。
