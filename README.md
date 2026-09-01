# runops

runops は、HPC / Slurm 上のシミュレーション研究を AI エージェントと進めるための
実行管理基盤です。

研究者は目的・制約・判断を伝えます。Agent は候補をいくらでも提案できますが、runops は
問い・baseline・有限 budget・有効期限・終了条件を持つ Experiment を admission unit とし、明示的に
選ばれた条件だけを Run directory にします。Slurm job、解析結果、provenance までを一つの
project state として管理します。

## はじめる

新しい project を作る場合:

```bash
uvx --from runops runo init
uvx --from runops runo doctor
uvx --from runops runo plugins --check
```

既存 project を使う場合:

```bash
uvx --from runops runo setup https://github.com/user/my-project.git
cd my-project
uvx --from runops runo doctor
```

新しい `runo init` project は `[experiments.policy] require_experiment = true` です。
既存 project に policy section がない場合は互換性のため `false` として読み、移行前の
standalone Run 作成を突然止めません。

初期化後は、CLI を順番に覚える必要はありません。生成された project で Agent に
次のように依頼します。

```text
この研究では、月面への太陽風入射角が表面帯電に与える影響を調べたい。
既存の plasma.toml を基準に、仮説、独立変数、観測量を整理して。
まず Experiment と pilot survey の案を作り、候補だけ preview して。
Run directory の生成と submit は確認するまで行わないで。
```

詳しい始め方は [AI エージェントではじめる](docs/get-started-with-agent.md) を参照してください。

## 何を管理するか

| 対象 | 正本 | 役割 |
|---|---|---|
| 研究全体の憲章 | `campaign.toml` | 長期の仮説、変数、観測量 |
| 一つの実験判断 | `experiments/E...toml` | 問い、baseline、budget、有効期限、exit criteria、判断 |
| 再利用条件 | `cases/*/case.toml` | simulator、job、基本パラメータ |
| パラメータ候補 | `runs/*/survey.toml` | lazy な探索軸、phase、intent、materialize 上限 |
| 1 回の正式実行 | `manifest.toml` | Run ID、状態、意図、identity、review、storage |
| smoke / debug | `.runops/test-runs/T.../test-receipt.toml` | 正式 Run と分離した短命な TestAttempt |
| 現在の判断 | `research/CURRENT.md` | 今読むべき結論と次の判断 |
| 残す解析 | `research/results/` | claim と Result-local evidence edge を持つ成果 |

run directory が日常運用の主単位です。`run.id` は不変ですが、directory は整理や
archive のため移動できます。

## 基本の流れ

```text
研究意図
  -> campaign / bounded Experiment
  -> case / lazy survey plan
  -> selected pointsだけ Run 生成
  -> submit / sync
  -> review / 解析・比較
  -> Result seal / Experiment の判断更新
```

Agent は投入前に対象 run、queue、資源量を示します。投入後は `manifest.toml` を正本に
状態を同期し、解析結果には source run と再現 command を残します。

`runo runs sweep` の既定動作は read-only で、候補数、`p0001` 形式の参照、plan hash、
概算 core-hours を表示するだけです。directory を作るには `--apply` と
`--point ...`（または `--all`）、さらに preview の `--expect-plan` がすべて必要です。
smoke / debug は `runo test ...` を使い、通常の Run 一覧や Run ID 空間へ混ぜません。

## 安全性

次の操作は確認を挟みます。

- 初回または高コストな一括 submit
- Survey point の materialize と Experiment の `decision=expand`
- 資源量を増やす retry
- `cancel`、`archive`、`purge-work`、`delete`
- 研究仮説や campaign の意味を変える編集
- project-state migration と harness 更新

生成済みの `manifest.toml`、`input/`、`submit/job.sh` は直接編集せず、変更元の case や
survey に戻します。

## よく使う operator command

普段は Agent が実行します。手動確認では次の command が入口です。

```bash
runo context --json       # project の現在地
runo triage               # 増やす前に active work と整理候補を点検
runo experiments list     # admission 済みの問いと判断
runo runs sweep runs/scan # read-only candidate plan
runo runs list            # active run 一覧
runo runs status          # 状態表示
runo runs sync            # Slurm 状態を manifest に反映
runo lint                 # project state の health check
```

全 command は [.codex/rules/commands.md](.codex/rules/commands.md) にあります。

## ドキュメント

目的別の入口は [Documentation](docs/README.md) にまとめています。

| 読みたいこと | 文書 |
|---|---|
| 最初の project を動かす | [AI エージェントではじめる](docs/get-started-with-agent.md) |
| Agent の実行ルールを知る | [Agent User Guide](docs/agent-user-guide.md) |
| project state の置き場所を知る | [Layer Docs](docs/layers/README.md) |
| TOML field を調べる | [TOML リファレンス](docs/toml-reference.md) |
| runops を拡張する | [拡張ガイド](docs/extending.md) |
| 内部設計を調べる | [アーキテクチャ](docs/architecture.md) |

## 開発

```bash
git clone https://github.com/Nkzono99/runops.git
cd runops
uv sync --dev
uv run pytest
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/
```

## ライセンス

Apache-2.0
