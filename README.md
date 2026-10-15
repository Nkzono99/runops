# runops

runops は、HPC / Slurm 上のシミュレーションを AI エージェントと進めるための
run 管理ツールです。エージェントに「何を調べたいか」を伝えると、case（入力テンプレート）
から run directory を作り、job を投入し、結果と経緯を run ごとに記録します。

管理するものは case、run、sweep の 3 つだけです。run が増えても一覧は直近のものに絞られ、
古い run の整理もエージェントが提案します。

## はじめる

人が実行するコマンドは `runo init` だけです。

```bash
uv tool install runops
mkdir lunar-sheath && cd lunar-sheath
runo init emses --site camphor     # simulator 名と site を指定（どちらも省略可）
```

`runo init` は `runops.toml`、`cases/`、`runs/`、`LOG.md`、`notes/`、`AGENTS.md`、
skill を作り、simulator の package を `.venv` に入れます。あとはこの directory で
Codex や Claude Code を起動し、やりたいことを伝えます。

## エージェントへの依頼例

```text
cookbook の平板シースを元に case を作って。plasma.toml の基準値は Te=Ti=10 eV で、
camphor の gr20001a に 800 並列、120 時間で投げられるようにして。
```

```text
まず 100 step だけ smoke で試して、問題なければ wc を 0, 0.147, 0.294 と
phiz を 0, 45 で振った本計算の候補を見せて。投入は確認してから。
```

```text
先週投げた run の状況を見て。失敗していたら原因を調べてノートに残して。
```

```text
古い run を整理して。消すものと archive するものを先に見せて。
```

```text
BEACH も使えるようにして。パッチを当てた ~/BEACH-dev もビルドして別 simulator として登録して。
```

```text
runops と simulator を最新にして。
```

```text
この project は runops v1 で作ったので v2 に移行して（`runo migrate-v1` を dry-run で確認してから）。
```

エージェントは生成された `AGENTS.md` と skill に従って `runo` を実行します。投入、削除、
整理、移行のように影響の大きい操作は、対象と資源量を示して確認を取ってから行います。

## 何が残るか

```text
runops.toml            site / simulators / launchers / defaults
cases/<case>/          case.toml と base 入力ファイル
runs/<case>/<run_id>--<label>/
                       manifest.toml, input/, submit/job.sh, work/, analysis/, notes.md
runs/_scratch/         smoke / debug 用の run（期限付き）
runs/_archive/         archive した run（元の相対 path を保つ）
LOG.md                 run をまたぐ結論と次の判断（追記のみ）
notes/<topic>.md       再利用する知見（1 topic 1 file）
AGENTS.md, CLAUDE.md, .agents/skills/, .claude/skills/
                       runops が生成するエージェント向けの入口と skill
```

run の値違いは case を増やさずに run として作り、一覧は既定で実行中と直近の run だけを
表示します。古い run や期限切れの smoke は、エージェントが整理候補として提案します。

## simulator との連携

simulator 固有の処理（入力の書き換え、完了判定、要約）は adapter が担います。
MPIEMSES3D（`mpiemses3d-tools`）と BEACH（`beach-bem`）は package に adapter と
エージェント向け skill を同梱しており、`.venv` に入れるだけで使えます。plugin の
install や再起動は要りません。adapter を含む版がまだ入っていない場合は、runops 同梱の
移植版 adapter が `adapters/` に置かれます。自作の simulator を対応させる方法は
[adapter ガイド](docs/adapter.md) にあります。

## ドキュメント

| 文書 | 内容 |
|---|---|
| [リファレンス](docs/reference.md) | `runops.toml`、`case.toml`、`manifest.toml`、全 command（主にエージェントと開発者向け） |
| [adapter ガイド](docs/adapter.md) | simulator package 作者向けの adapter と skill 同梱 |
| [SPEC.md](SPEC.md) | 設計と決定事項 |

## 開発

```bash
uv sync --dev
uv run pytest
uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/
uv run mypy src/
```

## ライセンス

Apache-2.0
