# runops

runops は、HPC / Slurm 上のシミュレーションを run directory 単位で管理する CLI です。
case（入力テンプレート）から run を作り、job.sh を生成して投入し、状態を
`manifest.toml` に記録します。AI エージェントが `runo` コマンドで操作することを
前提に、project に `AGENTS.md` と skill を生成します。

管理する名詞は case、run、sweep の 3 つだけです。run が増えても、一覧は既定で
active と直近の run だけを表示し、`runo tidy` が整理候補を提案します。

## インストール

```bash
uv tool install runops        # または uvx --from runops runo ...
runo --version
```

## 5 分チュートリアル

```bash
mkdir lunar-sheath && cd lunar-sheath
runo init emses --site camphor      # runops.toml, AGENTS.md, skills, .venv を作る
runo doctor                         # adapter, executable, sbatch, skill を点検

runo case new flat --simulator emses
cp ~/somewhere/plasma.toml cases/flat/plasma.toml
$EDITOR cases/flat/case.toml        # [job] の partition / walltime / 資源量

runo new flat --why "基準条件" --scratch          # smoke 用の短命 run
runo new flat --why "wc を 0.147 に" --set plasma.wc=0.147
runo sweep flat --set plasma.wc=0,0.147,0.294 --set plasma.phiz=0,45   # 候補だけ表示
runo sweep flat --set plasma.wc=0,0.147,0.294 --set plasma.phiz=0,45 --apply --why "角度依存"

runo submit R20261015-0002          # job.sh を生成して sbatch
runo sync                           # squeue / sacct から状態を更新
runo list                           # active と直近 30 日の run
runo log R20261015-0002 --err
runo note R20261015-0002 "初期 sheath 形成に 2e4 step"
runo tidy                           # 整理候補（--apply で実行）
```

エージェントには目的だけ伝えれば十分です。生成された `AGENTS.md` に、確認が必要な
操作（投入、削除、整理）とノートの置き場所が書かれています。

## project の構成

```text
runops.toml            site / simulators / launchers / defaults
cases/<case>/          case.toml と base 入力ファイル
runs/<case>/<run_id>--<label>/
                       manifest.toml, input/, submit/job.sh, work/, analysis/
runs/_scratch/         smoke / debug 用の run（期限付き）
runs/_archive/         archive した run（元の相対 path を保つ）
LOG.md                 run をまたぐ結論と次の判断（追記のみ）
notes/<topic>.md       再利用する知見（1 topic 1 file）
AGENTS.md, CLAUDE.md   runops が生成する agent 向け入口
.agents/skills/, .claude/skills/
                       runops と simulator package の skill
```

## simulator の追加

simulator 固有の処理は adapter が担います。adapter は次のどれかで見つかります。

1. simulator の Python package が公開する `runops.adapters` entry point
2. project の `adapters/<name>.py`
3. runops 同梱の `generic`（Jinja2 テンプレートと任意のコマンド）

package は skill と reference も同梱でき、`runo init` / `runo update` が project に
展開します。詳しくは [adapter ガイド](docs/adapter.md) を参照してください。

## v1 からの移行

```bash
cd my-v1-project
runo migrate-v1 --dry-run     # 変更計画だけ表示
runo migrate-v1               # 適用（v1 の設定と harness は .runops/v1-backup/ に退避）
```

各 run の元の manifest は `manifest.v1.toml` として残ります。`research/`、
`materials/`、`refs/` などは移動しません。

## ドキュメント

| 文書 | 内容 |
|---|---|
| [リファレンス](docs/reference.md) | `runops.toml`、`case.toml`、`manifest.toml`、全 command |
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
