# HPCシミュレーション実行管理ツール 仕様書 v1.0

## 1. 目的

本ツールは、HPC 環境において `sbatch` を用いて投入する各種シミュレーションについて、以下を一貫して管理するための実行管理基盤を提供する。

* run ディレクトリ生成
* パラメータサーベイ展開
* Slurm job script 生成
* job 投入
* 状態追跡
* run 単位の解析補助
* 実験条件とコード provenance の記録
* 多数 run の分類・整理

本ツールは **シミュレーションコード本体ではなく、run 管理と実験運用のためのツール** である。

---

## 2. 対象運用

本仕様は、以下のような運用を主対象とする。

* `sbatch` により HPC 上でジョブ投入する
* 複数種類のシミュレータを扱う
* シミュレータごとにパラメータファイル形式や命名規則が異なる
* MPI 並列実行を行う
* parameter survey により多数の run が生成される
* `runs/` 以下を階層的に整理したい
* 実際の解析作業は run ディレクトリ内で行いたい
* 大容量出力は run の近くに置きたいが Git では管理したくない
* シミュレーションコードは package install とローカル build の両方を使いたい
* Agent/AI にも扱いやすい構造にしたい

---

## 3. 基本設計方針

### 3.1 中心思想

本ツールは、**run ディレクトリを日常運用の主単位** とする。

利用者は通常、`runs/.../Rxxxx/` に入って以下を行う。

* 入力確認
* job 投入
* ログ確認
* 出力確認
* 解析
* 図作成
* 状態確認

### 3.2 不変と可変の分離

* run の同一性は **`run_id`** によって表す
* run の所属パスや階層は **分類・整理のための可変情報** とする

### 3.3 共通化の範囲

共通化するのは以下に限定する。

* run の識別
* manifest
* job 管理
* provenance
* survey 展開
* 状態遷移
* 解析補助の枠組み

一方で、以下はシミュレータごとに異なってよい。

* 入力ファイル形式
* 入力ファイル名
* 実行コマンド本体
* 出力検出方法
* summary 抽出方法

### 3.4 大容量出力の扱い

v1 では、大容量出力は **run ディレクトリ配下に置いてよい**。
ただし Git 管理対象には含めず、`.gitignore` により除外することを標準とする。

### 3.5 MPI 実行方針

MPI 実行は `job.sh` 内で **`srun` / `mpirun` / `mpiexec` を直接実行** する。
Python ツールは MPI rank ごとのラッパにはならない。

### 3.6 Public contract 境界

runops が private / pre-public な v0 系である間は、古い CLI option、内部 API、
project file format の互換 shim を長く維持しない。project-state に影響する
breaking change は `docs/migrations/v0.md` に移行方法を残す。

v1 で public contract として固定する対象は、まず以下に絞る。

* CLI command surface (`runo ...`) と主要 option
* project schema (`runops.toml`, `campaign.toml`, `case.toml`, `survey.toml`,
  `simulators.toml`, `launchers.toml`, `site.toml`)
* `manifest.toml` schema と run state semantics
* analysis artifact schema (`analysis/summary.json`, `analysis/artifacts.toml`,
  survey `summary/` artifacts)
* MCP result envelope、tool registry、safety metadata

内部 Python API、console output の細かな文言、generated harness template の内部構造は、
別途明示しない限り public contract とはみなさない。

### 3.7 Bounded contexts と internal dependency

runops は 1 package の中を次の 4 context に分ける。

* **Execution Kernel**: run identity、manifest/state、run 生成・実行 lifecycle
* **Research Workspace**: notes、analysis、publication、knowledge、paper request
* **Agent Gateway**: action facade、MCP、project harness、plugin metadata
* **Operator/Developer utilities**: init、migration、lint、update、update-harness、
  diagnostics、demo replay

内側から外側へのレイヤは次の順である。

```text
core -> application -> interfaces/infrastructure
```

この矢印は責務の並びであり、全 import graph ではない。`core/` は application、CLI、
MCP、Slurm、Adapter 実装、harness を import しない。`core/demo/replay.py` から
`templates.render` への import は既存 demo rendering contract の legacy exception
とし、新しい依存を増やさない。application use case は外部 effect に port / injection
seam を使う。既存 run creation / analysis が Adapter・Launcher・jobgen registry を
compose する箇所は application に閉じ込める。CLI と MCP は同じ use case/plan を
翻訳し、domain rule を複製しない。

Execution Kernel は candidate-stable contract、Research Workspace と Agent Gateway は
evolving surface とする。story / narrative generation は experimental であり、v0 中の
regroup / removal を許す。

---

## 4. 非目標

v1 では以下を対象外とする。

* Web UI
* 常駐 Web/API と push 配信を持つ persistent real-time dashboard service
* DB 必須設計
* 複数 scheduler の完全汎用化
* すべての simulator の入力仕様の共通 schema 化
* 高度な workflow engine 化

---

## 5. 用語定義

### Project

本ツールで管理するシミュレーション管理用 repository 全体。

### Case

run や survey を生成するための再利用可能な基底定義。

### Survey

複数 run をまとめて生成・整理するための親単位。
通常は parameter sweep に対応する。

### Run

1回の実行単位。
1つの `run_id` を持ち、入力・job script・状態・解析結果を保持する。

### Simulator

個別のシミュレータ本体。

### Simulator Adapter

シミュレータ固有仕様を吸収するための拡張コンポーネント。

### Launcher Profile

HPC 上での起動方式を定義する設定単位。
`srun` / `mpirun` / `mpiexec` などを扱う。

### Manifest

各 run の台帳ファイル。
run の識別、状態、由来、入力、コード provenance、job 情報を記録する。

---

## 6. ディレクトリ構造

## 6.1 全体構造

```text
sim-manager/
  runops.toml
  simulators.toml
  launchers.toml
  .gitignore

  cases/
    cavity_base/
      case.toml
      notes.md
    layer_base/
      case.toml

  runs/
    cavity/
      rectangular/
        u_aspect_scan_20260327/
          survey.toml
          notes.md
          summary/
            survey_summary.csv
            figures/
          R20260327-0001/
            manifest.toml
            input/
            submit/
            work/
            analysis/
            status/
          R20260327-0002/
            ...
      particle_layer/
        fcc_seed_scan_20260328/
          survey.toml
          R20260328-0001/
            ...

  notes/                 # project-wide lab notebook (chronological)
    YYYY-MM-DD.md        # 日次の append-only ノート (`runo notes append`)
    reports/             # 長文 refined レポート
    README.md            # 二層 (curated vs lab notebook) 規約
  research/              # current high-level research decision ledger
    README.md
    agenda.md            # mutable current decision state
    proposals/           # optional pre-execution decisions
    reviews/             # optional checkpoint snapshots
```

---

## 6.2 構造の考え方

### `cases/`

再利用可能な雛形定義を置く場所。
通常ここから直接実行しない。

### `runs/`

日常運用の主場所。
利用者は主にここを触る。

### `runs/.../<survey_dir>/`

survey の親ディレクトリ。
同一テーマ・同一 parameter sweep の run をまとめる。

### `runs/.../<survey_dir>/R.../`

実際の run ディレクトリ。
実行、確認、解析の基本単位。

---

## 6.3 多重ネスト

`runs/` 以下は **多重ネストを正式に許可** する。

例:

```text
runs/
  cavity/
    rectangular/
      production/
        scan_u_aspect/
          R20260327-0001/
```

ただし、run の一意識別には path ではなく `run_id` を使う。

---

## 7. run の識別

## 7.1 run_id

run の主キー。
永続・不変とする。

形式例:

```text
RYYYYMMDD-NNNN
```

例:

```text
R20260327-0001
R20260327-0124
```

### 要件

* Project 内で一意
* path 変更の影響を受けない
* 人間が扱える程度に短い

---

## 7.2 survey_id

survey の識別子。
必須ではないが、`survey.toml` 内で持つことを推奨する。

形式例:

```text
S20260327-cavity-u-a
```

---

## 7.3 display_name

人間向けの短い表示名。
suffix 的な役割を持つ。

例:

```text
u400_a4_s03
phi30_seed2
periodic_fix2
```

これは補助情報であり、主キーではない。

---

## 8. run ディレクトリ構成

各 run ディレクトリは次の構成を標準とする。

```text
R20260327-0001/
  manifest.toml
  input/
  submit/
  work/
  analysis/
  status/
```

---

## 8.1 `manifest.toml`

run の台帳。
最重要ファイル。

---

## 8.2 `input/`

実行に使用する入力ファイルを置く。
ファイル名・形式は simulator ごとに自由。

例:

* `input.toml`
* `plasma.nml`
* `mesh.inp`

---

## 8.3 `submit/`

job script を置く。

例:

* `job.sh`

必要なら submit 補助ファイルもここに置ける。

---

## 8.4 `work/`

実行時に生成されるファイルを置く。
原則として run の実作業空間。

例:

* stdout/stderr
* 出力ファイル
* restart
* tmp
* checkpoint
* bin

---

## 8.5 `analysis/`

run 単位の解析成果を置く。

例:

* `summary.json`
* `figures/`
* `notebooks/`
* `notes.md`

---

## 8.6 `status/`

状態追跡情報を置く。

例:

* `state.json`
* `sacct.txt`
* `submit.log`

---

## 9. Git 管理方針

## 9.1 標準方針

大容量出力は **run 配下に置いてよい**。
ただし Git 管理対象には含めず、`.gitignore` によって除外する。

---

## 9.2 管理対象

通常は以下を Git 管理対象とする。

* `runops.toml`
* `simulators.toml`
* `launchers.toml`
* `cases/**`
* `runs/**/survey.toml`
* `runs/**/manifest.toml`
* `runs/**/input/**`
* `runs/**/submit/**`
* `runs/**/status/**`
* `runs/**/analysis/summary.json`
* 軽量な図やノート
* Agent 用文書

---

## 9.3 非管理対象

通常は以下を Git 管理しない。

* `runs/**/work/outputs/**`
* `runs/**/work/restart/**`
* `runs/**/work/tmp/**`
* 巨大ログ
* 解析 cache
* notebook checkpoint

---

## 9.4 `.gitignore` 例

```gitignore
# heavy run outputs
runs/**/work/outputs/
runs/**/work/restart/
runs/**/work/tmp/

# logs
runs/**/work/*.out
runs/**/work/*.err
runs/**/work/*.log

# analysis cache
runs/**/analysis/cache/
runs/**/analysis/.ipynb_checkpoints/
```

---

## 9.5 symlink 方針

v1 では symlink は **必須ではない**。
必要になった場合のみ任意で利用可能とする。

想定用途:

* `work/outputs` の実体だけ別ストレージへ逃がす
* archive 移動後も run 側の見た目を保つ

ただし標準運用は `.gitignore` による in-place 管理とする。

---

## 10. Case 仕様

## 10.1 役割

Case は run や survey の生成元となる基底定義である。
Case 自体は通常、直接実行しない。

---

## 10.2 `case.toml` 例

```toml
[case]
name = "cavity_base"
simulator = "lunar_pic"
launcher = "slurm_srun"
description = "baseline cavity model"

[classification]
model = "cavity"
submodel = "rectangular"
tags = ["baseline"]

[job]
partition = "gr20001a"
nodes = 1
ntasks = 32
walltime = "12:00:00"

[params]
nx = 256
ny = 256
nz = 512
dt = 1.0e-8
u = 4.0e5
aspect = 4.0
seed = 1
```

---

## 10.3 `params` の意味

`[params]` の意味は simulator ごとに異なってよい。
解釈は Simulator Adapter が行う。

---

## 11. Survey 仕様

## 11.1 役割

Survey は parameter sweep などに対応する親単位である。
通常は `runs/` 配下の親ディレクトリに `survey.toml` を置く。

---

## 11.2 `survey.toml` 例

```toml
[survey]
id = "S20260327-cavity-u-a"
name = "u-aspect scan"
base_case = "cavity_base"
simulator = "lunar_pic"
launcher = "slurm_srun"

[classification]
model = "cavity"
submodel = "rectangular"
tags = ["scan", "paper1"]

[axes]
u = [2.0e5, 4.0e5, 8.0e5]
aspect = [2.0, 4.0, 8.0]
seed = [1, 2, 3]

[naming]
display_name = "u{u}_a{aspect}_s{seed}"

[job]
partition = "gr20001a"
nodes = 1
ntasks = 32
walltime = "12:00:00"
```

`survey.toml` の `[classification]` と `[job]` は、`base_case` の
`case.toml` に対する field-wise override として扱う。書かれていない
field は case 側から継承する。scalar field は survey 側の値が空でない
場合に上書きし、list field は survey 側に field が存在する場合にリスト
全体を置換する（空リストも明示的な置換として扱う）。

## 11.2.1 連動パラメータ (`[[linked]]`)

`[axes]` は各パラメータを独立に直積展開するが、`[[linked]]` を使うと複数パラメータを連動（zip）して変化させられる。

```toml
[axes]
seed = [1, 2, 3]

# nx と ny は連動して変化 (zip)
[[linked]]
nx = [32, 64, 128]
ny = [32, 64, 128]
# → (32,32), (64,64), (128,128) の 3 組
```

上記の場合、最終展開は `3 seeds × 3 linked pairs = 9 runs`。

**ルール:**
- 同一 `[[linked]]` グループ内のパラメータは同じ長さでなければならない
- 複数の `[[linked]]` グループを定義可能。グループ間は直積で展開される
- `[axes]` と `[[linked]]` のパラメータ名は重複不可
- `[axes]` のみ、`[[linked]]` のみ、両方組み合わせ、いずれも可

**複数グループの例:**

```toml
[axes]
seed = [1, 2]

# グリッド解像度の連動
[[linked]]
nx = [32, 64]
ny = [32, 64]

# 時間ステップの連動
[[linked]]
dt = [0.1, 0.01]
steps = [100, 1000]
```

展開: `2 seeds × 2 grid pairs × 2 time pairs = 8 runs`

---

## 11.3 run 生成位置

Survey から生成される run は、**その `survey.toml` のあるディレクトリ直下** に配置する。

---

## 11.4 survey summary

survey 単位の summary や図は survey 親ディレクトリに置いてよい。

例:

```text
u_aspect_scan_20260327/
  survey.toml
  summary/
    survey_summary.csv
    figures/
```

---

## 12. Manifest 仕様

## 12.1 役割

Manifest は各 run の正本情報を保持する台帳である。

---

## 12.2 `manifest.toml` 例

```toml
[run]
id = "R20260327-0001"
display_name = "u400_a4_s03"
status = "created"
created_at = "2026-03-27T13:00:00+09:00"

[path]
run_dir = "runs/cavity/rectangular/u_aspect_scan_20260327/R20260327-0001"

[origin]
case = "cavity_base"
survey = "S20260327-cavity-u-a"
parent_run = ""

[classification]
model = "cavity"
submodel = "rectangular"
tags = ["scan", "paper1", "production"]

[simulator]
name = "lunar_pic"
adapter = "lunar_pic_adapter"
resolver_mode = "local_source"

[launcher]
name = "slurm_srun"

[simulator_source]
resolver_mode = "local_source"
source_repo = "/home/user/work/lunar-pic"
git_commit = "abc1234"
git_dirty = false
build_command = "make -j"
executable = "/home/user/work/lunar-pic/build/solver"
exe_hash = "sha256:..."
package_version = ""

[job]
scheduler = "slurm"
job_id = ""
partition = "gr20001a"
nodes = 1
ntasks = 32
walltime = "12:00:00"
submitted_at = ""

[variation]
changed_keys = ["u", "aspect", "seed"]

[params_snapshot]
u = 4.0e5
aspect = 4.0
seed = 3

[files]
input_dir = "input"
submit_dir = "submit"
work_dir = "work"
analysis_dir = "analysis"
status_dir = "status"
```

---

## 12.3 必須記録項目

`manifest.toml` は最低限、次の table と field を保持する。

* `[run]`: `id`, `status`
* `[origin]`: `case`
* `[simulator]`: `name`
* `[launcher]`: `name`
* `[simulator_source]`: code provenance table
* `[job]`: `scheduler`, `job_id`, `submitted_at`
* `[params_snapshot]`: run 生成時の完全な parameter snapshot（空 table も可）

runops が新しく生成する manifest は、上記に加えて `[path]`,
`[classification]`, `[variation]`, `[files]` を含む canonical shape を使う。
既存 v0 manifest は optional table が欠けていても読み取り可能とする。

## 12.4 拡張データと read/write 保全

canonical な top-level table は `run`, `path`, `origin`, `classification`,
`simulator`, `launcher`, `simulator_source`, `job`, `variation`,
`params_snapshot`, `files` である。

将来の runops や外部 tool が追加した未知の top-level table と、canonical table
内の未知 field は、runops が解釈しなくても read/write または update の前後で
値を保持する。内部表現で拡張データと canonical table 名が衝突した場合は、
canonical table を正本として優先する。

第三者固有の metadata は、名前衝突を避けるため
`[extensions.<namespace>]` 以下へ置くことを推奨する。TOML の comment や table
順序は保全対象ではなく、parse された値の semantic preservation を保証する。

---

## 13. 状態遷移

run の状態は以下を持つ。

* `created`
* `submitted`
* `running`
* `completed`
* `failed`
* `cancelled`
* `archived`
* `purged`

---

## 13.1 状態の意味

### `created`

run ディレクトリ・manifest・入力・job script が生成済み

### `submitted`

`sbatch` 済みで job_id を取得済み

### `running`

実行中

### `completed`

正常終了

### `failed`

異常終了または失敗判定

### `cancelled`

途中停止

### `archived`

必要に応じて出力整理済み

### `purged`

不要 work を削除済み

---

## 13.2 基本遷移

```text
created -> submitted -> running -> completed
created/submitted/running -> failed
submitted/running -> cancelled
completed -> archived -> purged
```

`runo runs cancel` は `submitted` / `running` の run に対して `scancel` と
`sync` を組み合わせて発行し、`cancelled` 状態に遷移させる。

ライフサイクル外操作として、`runo runs delete` は `created` /
`cancelled` / `failed` の run ディレクトリをハード削除する。
`completed` / `archived` の run には適用できず、その場合は
`archive → purge-work` を使う。

---

## 14. Simulator Adapter 仕様

## 14.1 役割

Simulator Adapter は simulator 固有仕様を吸収する。

責務は以下とする。

* 入力ファイル生成
* 入力ファイル名決定
* 実行コマンド本体生成
* 出力検出
* 成功判定
* summary 抽出
* provenance 取得

---

## 14.2 抽象インタフェース

概念仕様:

```python
class SimulatorAdapter:
    name: str

    def render_inputs(case_data, run_dir) -> list[str]:
        ...

    def resolve_runtime(simulator_config, resolver_mode) -> dict:
        ...

    def build_program_command(runtime_info, run_dir) -> list[str]:
        ...

    def detect_outputs(run_dir) -> dict:
        ...

    def detect_status(run_dir) -> str:
        ...

    def summarize(run_dir) -> dict:
        ...

    def collect_provenance(runtime_info) -> dict:
        ...
```

---

## 14.3 性能要件

Adapter は **実行準備と後処理のみ** を担当する。
MPI 実行中の rank ごとのホットパスには介入しない。

---

## 15. Launcher Profile 仕様

## 15.1 役割

Launcher Profile は HPC 上での起動方式を定義する。

例:

* `srun`
* `mpirun`
* `mpiexec`

---

## 15.2 `launchers.toml` 例

```toml
[launchers.slurm_srun]
kind = "srun"
command = "srun"
use_slurm_ntasks = true

[launchers.openmpi]
kind = "mpirun"
command = "mpirun"
np_flag = "-np"
use_slurm_ntasks = true

[launchers.mpiexec]
kind = "mpiexec"
command = "mpiexec"
n_flag = "-n"
use_slurm_ntasks = true
```

---

## 15.3 責務

Launcher Profile は以下を担当する。

* MPI launcher コマンド選択
* task 数との結合
* 付加オプションの組み立て
* OpenMP 環境変数の補助
* `job.sh` の実行行生成

---

## 15.4 実行方式

Simulator Adapter が返す本体コマンドを Launcher Profile が包む。

例:

Adapter が返す本体:

```text
./work/bin/solver input/input.toml
```

Launcher が生成する最終実行:

```text
srun ./work/bin/solver input/input.toml
```

または

```text
mpirun -np ${SLURM_NTASKS} ./work/bin/solver input/input.toml
```

---

## 15.5 性能要件

最終的な `job.sh` では、MPI 実行を **直接** 行う。
たとえば以下のようにする。

```bash
exec srun ./work/bin/solver input/input.toml
```

Python や別 wrapper を rank ごとに挟まないことを原則とする。

---

## 16. Resolver 仕様

同一 simulator について、コード実体の解決方法を複数持つ。

### `package`

インストール済み package を使う

### `local_source`

ローカル source repo を参照し、必要に応じて build する

### `local_executable`

ローカル build 済み実行ファイルを直接使う

---

## 16.1 方針

* 開発中は `local_source` / `local_executable` を許可
* 本番では provenance を厳密に記録
* 毎回 `pip install -e .` を必須にはしない

---

## 17. Provenance 要件

各 run について以下を記録する。

* simulator 名
* resolver mode
* source repo path
* git commit hash
* dirty 状態
* package version
* executable path
* executable hash
* build command
* launcher 名
* job_id
* params snapshot

---

## 17.1 本番 run の追加要件

production tag を持つ run では、以下を推奨または要求する。

* clean working tree
* commit 固定
* executable hash 記録
* 可能なら run 用の bin を固定配置

---

## 18. CLI 仕様

preferred executable は `runo` で、`runops` は同じ command tree を指す alias とする。
現行 v0 surface は grouped command である。全 command path、required positional
argument、主要 safety option の正本は `.codex/rules/commands.md` とし、parser の
完全な option 一覧は `runo <group> <command> --help`、この仕様は behavior contract
を定める。
確認省略の正規 option は `--yes` とする。`runo update --force` は既存 script 用の
hidden compatibility alias で、`--yes` と別 semantics を持たない。

## 18.1 初期化

* `runo init`
* `runo doctor`

---

## 18.2 run 生成

* `runo runs create CASE_NAME`
* `runo runs sweep [<survey.toml のあるディレクトリ>]`

---

## 18.3 job 実行

* `runo runs submit [<run_dir or run_id>]`
* `runo runs submit --all [<survey_dir>]` — ready plan の run を一括投入する。通常は確認を要求し、明示済みの自動実行では `--yes` で省略できる。

---

## 18.4 状態追跡

* `runo runs status [RUNS...]`
* `runo runs sync [RUNS...]`

`runs status` / `runs sync` は run_id・run dir・survey dir を複数指定できる。
`runs sync` を bulk モード (survey dir または複数指定) で呼び出した場合、
`job_id` 未記録の run と terminal state (`completed`, `failed`,
`cancelled`, `archived`, `purged`) の run は **silent skip** され、残りの
submitted / running な run のみが Slurm に問い合わせられる。
single-target モードでは "nothing to sync" notice を出してエラー扱いに
しない。

---

## 18.5 一覧

* `runo runs list [PATHS...]`
* `runo runs list --status failed`
* `runo runs list --tag production`

---

## 18.6 複製・派生

* `runo runs clone [<run_dir or run_id>] --dest <survey_dir>`
* `runo runs clone <run_id> --set key=value` — `origin.case` と `params_snapshot` から input/job を再生成し、manifest だけの差し替えで派生 run を作らない。

---

## 18.7 解析補助

* `runo analyze summarize [<run_dir or run_id>]`
* `runo analyze collect [<survey_dir>]`

---

## 18.8 整理

* `runo runs archive <run_dir or run_id>` — completed → archived。既定では `runs/_archive/<元の runs/ 相対パス>` へ移動する
* `runo runs archive <run_dir or run_id> --keep-in-place` — completed → archived の状態変更のみ行う
* `runo runs archive <run_dir or run_id> --move-to <archive_root>` — custom archive root へ移動する
* `runo runs purge-work [<run_dir or run_id>]` — archived → purged
* `runo runs cancel [<run_dir or run_id>]` — submitted/running → cancelled (`scancel` と `sync` をまとめて実行する安全経路)
* `runo runs delete [<run_dir or run_id>]` — created / cancelled / failed の run ディレクトリをハード削除 (ライフサイクル外、completed/archived には不可)

---

## 18.9 Lab notebook (実験ノート)

curated knowledge (`.runops/insights/`, `.runops/facts.toml`) と並列に運用する
**append-only な時系列ノート**。1 ファイル = 1 日 (`notes/YYYY-MM-DD.md`)、
各エントリは `## HH:MM <title>` で始まる。

* `runo notes append TITLE [BODY]` — 今日 (JST) の lab notebook に追記。
  本文は引数 (inline) または `-` / 引数省略で stdin から読む。
* `runo notes list [-n N]` — 最近の lab notebook 日付一覧 (新しい順, デフォルト 14 日)
* `runo notes show [DATE|today|latest]` — 指定日の内容を表示
* `runo notes archive [--older-than 7d]` — 古い active note を year 別 history へ no-clobber で移動

書き込みポリシー:

* **append-only**: 既存 entry は触らない。新しい entry を末尾に追加する
* 1 ファイル = 1 日。日付は ISO 形式 (`2026-04-08.md`)
* 既存ファイルが無ければ `# YYYY-MM-DD — lab notebook` ヘッダ付きで新規作成
* 各 entry は `## HH:MM <title>` 直下に本文 (markdown 自由)

curated layer との関係:

```text
raw notes/materials
  -> research/agenda.md (current decision) OR notes/reports/<topic>.md
  -> analysis/publication artifact
  -> .runops/insights/<name>.md / .runops/facts.toml
```

raw evidence、現在判断/refined narrative、解析・出版 artifact、再利用可能知識を
同じ正本として混ぜない。

### 18.9.1 Research layer

`research/` は現在の高レベルな研究判断を隔離する project workspace。
`research/agenda.md` は TODO リストではなく、mutable な decision ledger とする。

* 本文は日本語で書く。コード・コマンド・ファイルパス・run_id は実際の表記のまま残す
* `notes/YYYY-MM-DD.md` は append-only な時系列ログ、`research/agenda.md` は現在判断の正本
* `research/proposals/` は高コスト・方向転換・新 model などの実行前判断を必要時に残す
* `research/reviews/` は主要 result / failed run / pause / kill / pivot などの checkpoint snapshot を残す

---

## 19. コマンド動作定義

## 19.1 `create`

* Case を読み込む
* `run_id` を採番
* 指定 survey ディレクトリ配下に run ディレクトリを作成
* input 生成
* `job.sh` 生成
* `manifest.toml` 生成
* 状態を `created` にする

---

## 19.2 `sweep`

* `survey.toml` を読み込む
* parameter 組合せを展開 (`[axes]` 直積 × `[[linked]]` zip)
* 各 run を survey 親ディレクトリ直下に生成
* 各 manifest に survey 情報を記録

---

## 19.3 `submit`

* plan は run を特定し、`created` state、未記録の `job_id`、空の durable claim、
  `submit/job.sh` の存在・readable・`#SBATCH` directive、non-empty input を確認する
* plan が返す exact scheduler command と precondition snapshot は CLI dry-run、
  MCP、bulk submit、実 submit で共有する
* apply は run 単位の process-safe advisory lock を保持し、scheduler 呼び出し直前に
  run_id、state、job_id、work directory 選択、durable claim を再確認する。stale plan は
  scheduler を呼ばず拒否し、lock は scheduler acceptance と local persistence の
  完了まで保持する
* run root の `.runops-submit.lock` は lock inode を安定させるため unlink しない内部
  artifact であり、manifest/state の正本ではなく Git 管理もしない。lock 内では
  scheduler 呼び出し前に `pending`、acceptance 後に `accepted:<job_id>` を fsync し、
  scheduler rejection または manifest/state の保存完了時だけ clear する
* persistence failure や process interruption で残った durable claim は後続 submit を
  block する。明示的 retry は同じ lock 内で terminal state を再検証し、claim を
  durable に clear してから `created` へ reset する
* `created` のまま `pending` / `accepted:<job_id>` claim が残る場合は scheduler の
  acceptance を照合し、manifest と claim を手動 reconcile するまで submit を block する
* scheduler failure では manifest と pre-submit state を変更しない
* scheduler acceptance 後に job attempt、job_id、`submitted` state を manifest へ保存する
* acceptance 後の persistence failure は accepted job_id と failure phase を持つ typed
  error として返し、同じ plan を自動再 submit しない

---

## 19.4 `status` / `sync`

`status` は観測表示、`sync` は manifest 更新を担当する。

### `status`

* manifest の `run.status` を表示する
* `job_id` がある場合は `squeue` / `sacct` で live Slurm state を best-effort 表示する
* manifest と `status/state.json` は更新しない
* `--short` / `--summary` では live Slurm query を行わず、manifest のみを読む

### `sync`

* `squeue` / `sacct` により Slurm 状態を RunState に変換する
* `status/state.json` を更新する
* manifest の `run.status` と `run.last_slurm_state` を同期する
* bulk モード (survey dir または複数 RUNS) では `job_id` 未記録 / terminal
  state な run を silent skip し、残りのみを処理する

---

## 19.5 `notes append`

* `notes/<JST today>.md` を解決 (project root 直下を優先、なければ cwd/notes)
* ファイルが無ければ `# YYYY-MM-DD — lab notebook` ヘッダを付けて新規作成
* 末尾に `## HH:MM <title>` 見出しと本文を append (既存 entry には触らない)
* 本文ソース: 引数 inline / `-` または引数省略時は stdin
* 空タイトル・空本文はエラー (exit 2)

---

## 19.6 `summarize`

* Adapter により出力を読み取り
* 主要指標を抽出
* `analysis/summary.json` を生成または更新

---

## 19.7 `collect`

* 指定 survey 配下の各 run の summary を収集
* `survey_summary.csv` などを生成

---

## 20. run 探索仕様

ツールは `runs/` 以下を **再帰探索** し、`manifest.toml` を持つディレクトリを run とみなす。

これにより、`runs/` 以下の多重ネストに対応する。

---

## 20.1 一意性

同一 Project 内で `run_id` の重複は不可とする。

---

## 21. 解析運用方針

### 21.1 基本方針

解析は原則として **各 run の `analysis/` 配下で行う**。

### 21.2 survey 解析

複数 run を横断する解析は survey 親ディレクトリ配下の `summary/` 等で扱ってよい。

### 21.3 共通解析コード

共通解析スクリプトは Project 外または別ディレクトリで管理してよい。
ただし生成物は各 run または survey に保存可能とする。

---

## 22. Agent/AI 統合方針

Agent が扱う主対象は以下とする。

* `case.toml`
* `survey.toml`
* `manifest.toml`
* `status/state.json`
* `analysis/summary.json`

Agent による主要操作:

* Case / Survey 生成補助
* run 生成
* 失敗 run 抽出
* summary 収集
* 図生成補助
* tags 更新

破壊的操作は慎重に制限する。

---

## 23. 運用モード

## 23.1 development

* `local_source` / `local_executable` 可
* dirty tree 可
* provenance 記録必須
* tag に `dev` を推奨

## 23.2 production

* clean tree 推奨または要求
* commit 固定
* executable hash 必須
* tag に `production` を推奨

---

## 24. エラー処理

## 24.1 `doctor`

以下を検査する。

* Project 設定妥当性
* simulator 解決可否
* launcher 定義妥当性
* `sbatch` 利用可否
* build command 存在
* template 未解決変数
* `run_id` 重複

---

## 24.2 submit 前検査

* 入力ファイル存在
* 実行ファイル存在
* provenance 取得可否
* production 条件
* `job.sh` 妥当性

---

## 25. v1 必須機能

* Project 初期化
* Case 読込
* Survey 展開
* run 生成
* run_id 採番
* `manifest.toml` 生成
* Simulator Adapter
* Launcher Profile
* Slurm submit
* 状態同期
* run 一覧取得
* survey 単位集計
* `.gitignore` 前提の heavy output 運用

---

## 26. v1.1 以降の拡張候補

* symlink/external output mode
* SQLite index
* failed run 一括再投入
* richer query
* scheduler 複数対応
* archive policy 自動化
* notebook テンプレート連携

---

## 27. 採用方針の要約

本仕様では以下を正式採用する。

* `runs/` 配下の多重ネストを許可
* run ディレクトリを主作業単位とする
* survey は `runs/` 配下で親ディレクトリとして管理可能
* 大容量出力は run 配下に置き `.gitignore` で除外
* symlink は optional
* run の一意性は `run_id`
* simulator 固有処理は Adapter
* MPI 起動方式は Launcher Profile
* `job.sh` で `srun` / `mpirun` / `mpiexec` を直接実行
* `pip install -e .` は必須ではなく、resolver で柔軟に扱う

---
