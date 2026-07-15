# アーキテクチャ原則

## 現在のモデル

runops は 1 つの installable package を、次の 4 bounded context に分ける。

- **Execution Kernel**: project / case / survey / run、manifest、state、run 生成、
  submission plan/apply、Adapter、Launcher、Slurm port。
- **Research Workspace**: notes、analysis、publication、knowledge、paper request。
- **Agent Gateway**: action facade、MCP、project harness、plugin metadata。
- **Operator/Developer utilities**: init、migration、lint、update、update-harness、
  diagnostics、demo replay。

内側から外側へのレイヤの並びは次である。

```text
core -> application -> interfaces/infrastructure
```

これは責務の並びであり、全 package の import graph を表す矢印ではない。現在の
強制境界は `core/` が application、CLI、MCP、Slurm、Adapter 実装、harness を
import しないこと。`application/` は use case と port/injection seam を持つ一方、
run creation / analysis は既存の Adapter・Launcher・jobgen registry を composition
する。`core/demo/replay.py` から `templates.render` への import は既存 demo rendering
contract の明示的な legacy exception とし、新しい依存を増やさない。
`cli/` / `mcp/` は入力・表示、`slurm/` / `harness/` 等は外部 I/O を担う。

## 守るべき境界

- CLI と MCP は薄く保ち、同じ規則を再実装せず application use case を呼ぶ。
- CLI root は complete group app を合成し、group ごとの command registration は
  `cli/groups/` に閉じ込める。Typer signature から domain rule を生成しない。
- run 生成・submit・archive 等の orchestration を `core/` に戻さない。
- simulator 固有処理は `SimulatorAdapter`、MPI 起動方式は `Launcher` に閉じ込める。
- Python は MPI rank ごとのラッパにならず、job script が `srun` / `mpirun` /
  `mpiexec` を直接実行する。
- 外部実行や filesystem mutation は plan/apply に分け、apply 前に stale 条件を確認する。

責務が大きい use case は公開 facade と capability module に分ける。submission は
planning / claim / apply、notebook は access / archive、plugin gateway は discovery /
validation / inventory を境界とする。Simulator Adapter の registry class は
`adapter.py` に維持し、宣言情報は `metadata.py`、出力・状態判定は
`diagnostics.py` に置く。

## `manifest.toml` が正本

run の identity、state、origin、provenance、job 情報は `manifest.toml` に記録する。
run_id は `RYYYYMMDD-NNNN` 形式で不変、path は整理のため可変である。既知 field を
更新するときも未知 top-level / section field を lossless に保持する。現行 v0 schema
に migration protocol を伴わない `schema_version` は追加しない。

## Research Workspace の成熟度

成熟経路は次とする。

```text
research/journal + materials + .runops/work
  -> research/CURRENT.md OR research/results/RNNNN-topic
  -> insights/facts
```

`research/CURRENT.md` は現在判断、`research/results` は人が昇格した refined result、
`.runops/insights/` / `.runops/facts.toml` は再利用する整理済み知見を担う。
生成済み context や会話ログを正本にしない。story は experimental surface として
candidate-stable kernel から分ける。

## ハーネス二重構造

1. `.claude/`, `.codex/`, `.agents/skills/`: runops 開発ハーネス。
2. `src/runops/templates/` と `harness/builder.py`: project 側生成ハーネス。

project 側への反映は `runo update-harness` が担う。変更時は両者を混同せず、shared
guidance を変えた場合だけ意図的な drift を点検する。
