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
* project schema (`runops.toml`, `campaign.toml`, Experiment TOML, `case.toml`, `survey.toml`,
  `simulators.toml`, `launchers.toml`, `site.toml`)
* `manifest.toml` schema と run state semantics
* TestAttempt `test-receipt.toml` と canonical Result manifest / seal semantics
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

### 3.8 候補と実体の分離

AI が提案できる条件数は directory 数の予算ではない。runops は候補の列挙を read-only な
lazy plan として扱い、次の gate をすべて通った点だけを正式 Run に materialize する。

* 一つの問い、baseline、有限 budget、有効期限、exit criteria を持つ active Experiment
* Survey に明示した `survey.id`, `experiment_id`, `phase`, `intent.purpose`
* preview 後の不変な plan hash
* `--point` または `--all` による明示選択
* Survey / Experiment の materialized Run、active Run、core-hour、未 review Run の上限

smoke / debug は Run の縮小版にせず、別 ID・別 directory・別 receipt の TestAttempt とする。
これにより通常の Run 一覧、Experiment budget、論文用 evidence へ偶然混入させない。

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

parameter 候補を lazy に列挙し、明示選択した Run をまとめる親単位。
Survey の候補数と materialize 済み Run 数は別に数える。

### Experiment

一つの研究上の問いを Execution Kernel に admission する単位。
`EYYYYMMDD-NNNN` ID と、baseline、有限 budget、有効期限、exit criteria、review decision を持つ。
空のアイデア backlog や長い proposal ledger ではなく、`experiments/*.toml` 1 file で表す。

### Run

1回の実行単位。
1つの `run_id` を持ち、入力・job script・状態・解析結果を保持する。

### TestAttempt

smoke / debug 用の短命な検証単位。`TYYYYMMDD-NNNN` ID を持ち、
`.runops/test-runs/` に置く。Run の `manifest.toml` ではなく `test-receipt.toml` を正本とし、
scientific Result の evidence にはできない。

### Result

残すと判断した claim と、その claim に対する evidence の inclusion / exclusion edge を
所有する単位。Run を project-global に「採用済み」とせず、同じ Run を Result ごとに
異なる判断で参照できる。canonical Result は seal 時に source hash を固定する。

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

  experiments/
    E20260327-0001--surface-charging.toml

  cases/
    cavity_base/
      case.toml
    layer_base/
      case.toml

  runs/
    cavity/
      rectangular/
        u_aspect_scan_20260327/
          survey.toml
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

  research/              # quantity-bounded research memory
    CURRENT.md           # mutable current state (20,000 chars hard; compact warnings)
    journal/
      active.md          # append-only active segment
      archive/           # intact JNNNN.md segments
    results/             # explicitly promoted durable results
    archive/results/     # reversible inactive results
  .runops/work/          # provisional goal output (gitignored)
  .runops/test-runs/     # smoke/debug TestAttempt (gitignored, T... ID)
  .runops/cache/         # derived cache (gitignored)
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

### `experiments/`

正式に admission した研究上の問いを 1 Experiment = 1 TOML で置く。候補メモを大量に
永続化する場所ではない。未 admission の案や生成途中の prose は `.runops/work/` に置く。

### `.runops/test-runs/`

smoke / debug の input snapshot と receipt を置く。通常の Run discovery、archive、Result
evidence から分離し、terminal attempt は年齢を指定して cleanup できる。

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
新規 run のディレクトリ名は、既定で不変な `run_id` と filesystem-safe な
`display_name` slug を `RYYYYMMDD-NNNN--<label>` の形で併記する。
`display_name` が空ならディレクトリ名は `run_id` のみとする。

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

人間向け narrative を `analysis/notes.md` に増やさない。生成途中の説明は
`.runops/work/`、時系列は journal、残す claim / interpretation は Result の
`README.md` 一枚に置く。既存 `analysis/notes.md` は legacy lint warning の対象とする。

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

`runs/_archive/` 自体は ignore しない。bundle archive 後も
`survey.toml`、`manifest.toml`、source input、curated analysis、
`.runops-archive.toml` は Git 管理可能とする。一方、上記の `runs/**` pattern は
archive 配下にも同様に適用し、`work/`、`status/`、cache / scratch、生成済み input は
Git 管理対象へ戻さない。

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

`job.walltime` は正の `H+:MM:SS` または `D-H+:MM:SS` とし、minute / second は
`00..59` に制限する。`120:00:00` と `5-00:00:00` はどちらも有効な 120 時間である。
負値、`00:00:00`、範囲外の minute / second は Case、Survey override、manifest 由来の
clone / extend / retry、job.sh 生成、core-hour admission の全経路で拒否する。

---

## 10.3 `params` の意味

`[params]` の意味は simulator ごとに異なってよい。
解釈は Simulator Adapter が行う。

## 10.4 Experiment admission

Experiment は `runo experiments create` で作る。CLI は空の draft を作らず、作成時点で
question、baseline、全 budget、UTC offset 付きの未来の有効期限、少なくとも一つの exit criterion を要求して
`lifecycle = "active"` とする。project 全体の active Experiment 数は
`runops.toml [experiments.policy]` で制限する。

```toml
schema_version = 1

[experiment]
id = "E20260327-0001"
title = "surface charging angle response"
question = "Does surface potential change monotonically with incidence angle?"
lifecycle = "active"
intent = "explore" # explore | confirm | validate | reproduce
decision = "pending" # pending | expand | revise | stop | accept
outcome = "unknown"
created_at = "2026-03-27T04:00:00+00:00"
created_by = "human"

[baseline]
run_ids = ["R20260320-0001"]
reason = "" # run_ids と reason はどちらか一方だけ non-empty

[budget]
max_planned_points = 30
max_materialized_runs = 6
max_active_runs = 3
max_core_hours = 100.0
max_unreviewed_runs = 6
expires_at = "2099-04-30T00:00:00+00:00"

[exit]
criteria = ["pilot の安定性と trend を判定できる"]
review_due = ""

[review]
reason = ""
reviewed_at = ""
successor = ""
```

`review` は active Experiment の最新判断を更新する。`close` は decision を
`revise|stop|accept`、outcome を `supported|refuted|inconclusive|invalid` のいずれかに
確定して lifecycle を閉じるが、所属 Run の state や path は変更しない。
project policy の `max_unreviewed_completed_runs` は全 formal Run を owner 横断で数え、
`budget.max_unreviewed_runs` は当該 Experiment の Run だけを数えて独立に判定する。
project policy は `require_experiment = false` の既存 project と Experiment 未所属 Run にも
適用し、create / Survey materialization / clone / extend / retry の全 formal Run admission を
同じ strict namespace snapshot で fail-closed に判定する。Experiment 未所属の場合に省略する
のは Experiment-local budget だけである。
どちらの判定でも `review_status = "reviewed"` だけでは backlog から除外しない。
non-empty な `reviewed_by` / `reason` と timezone-aware ISO-8601 `reviewed_at` を含む
完全な review record だけを reviewed とみなし、欠落・不正値は fail-closed で未 review に数える。
`budget.expires_at` は UTC offset 付き ISO-8601 timestamp を必須とし、create 時点より未来で
なければならない。期限到達時 (`now >= expires_at`) は lifecycle を暗黙変更せず、create /
Survey materialization / clone / extend / retry の全 formal Run admission を拒否する。
review / close は期限後も可能で、`runo triage` は active の期限切れを明示して close または
successor admission を促す。
clone は source だけで standalone / managed を分類しない。source が project 外でも
destination が runops project 内なら destination project の policy、Experiment、budget、
expiry、Run namespace lock を適用する。legacy standalone copy は source と destination の
どちらも managed project に属さない場合だけ許可する。managed clone / extend は staging
開始時の Experiment metadata と公開時の current definition を CAS し、公開直前・直後の
両方で current expiry / budget を再検査する。post-publication gate が失敗した場合は Run を
staging へ rollback し、rollback も失敗した場合は曖昧な公開物を保持して明示的に報告する。
Experiment 未所属 Run の retry も `require_experiment = true` なら reset 前の submission lock
preflight で拒否し、terminal state、attempt、durable claim を変更しない。

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
experiment_id = "E20260327-0001"
phase = "pilot" # pilot | main | followup

[intent]
purpose = "explore" # Experiment intent と一致させる
information_gap = "Which angle range shows the transition?"
baseline_run = "R20260320-0001"
created_by = "human"

[budget]
max_materialized_runs = 3
max_core_hours = 24.0

[retention]
class = "exploratory"
review_after = "2026-04-15"
expire_after = ""

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
directory = "{run_id}--{label}"
max_length = 48

[naming.aliases]
"tmgrid.dt" = "dt"

[[naming.groups]]
label = "size"
keys = ["tmgrid.nx", "tmgrid.ny", "tmgrid.nz"]
strategy = "uniform_ratio"

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

`display_name` が空の場合は、base case から変化した parameter を使って決定的な
label を生成する。`uniform_ratio` group の全 key が同じ倍率なら、例えば
`nx`, `ny`, `nz` の各3倍を `size-x3` に畳み込む。成立しない group は個別の
parameter 差分へフォールバックする。group 外の数値は倍率を仮定せず値を表示する。
group は単一 key にも使え、明示的に倍率表記へ opt-in できる。
LLM は survey 設計時に alias / group を
提案してよいが、run 展開時の命名は外部 model call を行わず決定的に処理する。

`[retention]` の日付は review hint であり、自動削除の権限ではない。
formal materialization では `survey.id` を明示し、同じ project の別 survey と重複させない。
新規 scaffold では Experiment が必須で、`experiment_id`, `phase`, `intent.purpose` も
materialization gate になる。既存 project との互換性は 11.5 に定める。

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
formal Survey directory は project の `runs/` tree 内に置く。

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

## 11.5 lazy plan と materialization

`runo runs sweep [DIR]` は既定で read-only plan である。Cartesian product を list として
全展開せず、候補数を積で求め、`--offset` / `--limit` の範囲だけを iterator から表示する。
この操作は Run directory を作らず、Run ID も消費しない。`--dry-run` は同じ plan 動作の
compatibility alias とする。

各候補は full effective parameter mapping の canonical SHA-256 を `point_id` とし、表示用に
`p0001` 形式の ordinal ref も持つ。plan hash は `survey.toml`、base `case.toml`、case tree の
file content、`simulators.toml`、`launchers.toml`、`site.toml` を含む。materialization は
次の形だけを許す。

```bash
runo runs sweep runs/example
runo runs sweep runs/example --apply --point p0001 --expect-plan sha256:...
# 全点を明示的に選ぶ場合（hard budget を越えれば拒否）
runo runs sweep runs/example --apply --all --expect-plan sha256:...
```

`--apply` には `--point` または `--all` の exactly one と、現在の plan に一致する
`--expect-plan` が必要である。同じ `survey.id + point_id` が既に materialize 済みなら
existing Run を reuse し、retry で別 directory を増やさない。duplicate effective condition、
stale hash、budget 超過、inactive Experiment、purpose 不一致、または `main|followup` なのに
Experiment decision が `expand` でない場合は変更前に拒否する。
この exact-point retry は同一 owner / point / plan の同じ Run を返す idempotent recovery であり、
別 Run 間の scientific equivalence 推論ではない。従って strong provenance が未取得でも、保存済み
parameter、input tree、provenance と全 derived identity を再計算して一致する場合は同じ Run を返す。
異なる completed Run の再利用には引き続き 12.3 の strong provenance gate を要求する。
各未 materialize point の staged-directory 公開では、公開直前と直後に disk 上の current Project /
Experiment と strict formal Run snapshot から Survey / Experiment の materialized Run、active Run、
core-hour、project / Experiment の未 review backlog を再計算する。公開後の exact point が同じ
reserved Run ID で見つかった場合だけ budget increment を 0 として idempotent commit を検証し、
別 Run で同一点が現れた場合や post-publication gate が閉じた場合は fail-closed で公開を rollback する。

既存 project で `[experiments.policy]` がない場合は `require_experiment = false` として読む。
新しい `runo init` scaffold は明示的に `require_experiment = true` を書く。

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
git_state_observed = true
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

[intent]
experiment_id = "E20260327-0001"
survey_id = "S20260327-cavity-u-a"
phase = "pilot"
purpose = "explore"
created_by = "human"
information_gap = "Which angle range shows the transition?"
baseline_run = "R20260320-0001"

[identity]
point_id = "sha256:..."
condition_hash = "sha256:..."
input_hash = "sha256:..."
scientific_hash = "sha256:..."
execution_hash = "sha256:..."
provenance_hash = "sha256:..."
plan_hash = "sha256:..."

[curation]
review_status = "unreviewed"
reviewed_at = ""
reviewed_by = ""
reason = ""

[storage]
tier = "hot" # hot | cold
form = "full" # full | compacted | metadata_only
retention_class = "exploratory"
review_after = "2026-04-15"
expire_after = ""
pinned = false
pin_reason = ""

[files]
input_dir = "input"
submit_dir = "submit"
work_dir = "work"
analysis_dir = "analysis"
status_dir = "status"
```

4 種の derived identity (`condition_hash`, `input_hash`, `provenance_hash`,
`scientific_hash`) と `execution_hash` は runops が commit 境界で計算し、caller metadata
による上書きを許さない。`scientific_hash` は完全な parameter snapshot、閉じた input tree、
machine-local path を除いた executable/source identity、simulator configuration から作る。
completed 相当 Run の再利用時は、保存済み hash 文字列だけでなく manifest の parameter / source
provenance と実際の `input/` tree から 4 種の hash を再計算し、一つでも一致しない Run は
再利用しない。さらに hard reuse には canonical な `simulator_source.exe_hash` を必須とし、
`local_source` は commit と clean/dirty 状態の両方を Git command で取得できたことを示す
`git_state_observed = true`、non-empty commit、`git_dirty = false` のすべてを要求する。
Git command の失敗・欠落・不正型は fail-closed とする。compute node でしか解決できない
executable など強い provenance を採取できない Run も materialize はできるが、path や basename
だけを同一性の根拠として既存 Run を再利用してはならない。

`execution_hash` は scientific hash、launcher profile、site 名・resource style・module・environment、
partition と task/thread/resource layout、実行前後 command から作る。Run ID、Run の絶対 path、
job name、stdout/stderr path、`job_id`、submission/attempt 状態、生成された `job.sh` 全体は含めない。
従って同じ実行条件を別 Run directory に materialize しても一致し、site / job resource /
launcher 条件が変われば一致しない。

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
`[classification]`, `[variation]`, `[files]`, `[intent]`, `[identity]`,
`[curation]`, `[storage]` を含む canonical shape を使う。
既存 v0 manifest は optional table が欠けていても読み取り可能とする。

## 12.4 拡張データと read/write 保全

canonical な top-level table は `run`, `path`, `origin`, `classification`,
`simulator`, `launcher`, `simulator_source`, `job`, `variation`,
`params_snapshot`, `files`, `intent`, `identity`, `curation`, `storage` である。

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

scheduler / execution process が正常終了した状態。simulator 固有の完了条件や
analysis-required artifact の充足は別の readiness 軸で扱い、`completed` だけを
scientific evidence の受理条件にしない。

### `failed`

異常終了または失敗判定

### `cancelled`

途中停止

### `archived`

active view から退避済み。既定では run directory 全体を `runs/_archive/` へ移し、
入力・出力・restart・解析 artifact は保持する

親ディレクトリを `--bundle` で退避する操作は run lifecycle と直交する。
bundle 配下の `completed` / `cancelled` / `failed` / `created` 等の状態は変更せず、
`.runops-archive.toml` を親ディレクトリの archive marker とする。
archive destination が既に存在する場合は既定で拒否する。`--adopt-archived` を明示した
場合に限り、同じ親から同じ相対パスへ個別 archive 済みで、状態が `archived` または
`purged` の run のみを bundle へ採用できる。destination 内に対象 run 外の path がある、
元 path と相対位置が一致しない、または source 側と衝突する場合は全体を変更せず拒否する。

### `purged`

不要 work を削除済み

---

## 13.2 基本遷移

```text
created -> submitted -> running -> completed
created/submitted/running -> failed
submitted/running -> cancelled
completed -> archived -> purged
             |
             +-> completed  (restore)
```

`runo runs cancel` は `submitted` / `running` の run に対して `scancel` と
`sync` を組み合わせて発行し、`cancelled` 状態に遷移させる。

ライフサイクル外操作として、`runo runs delete` は `created` /
`cancelled` / `failed` の run ディレクトリをハード削除する。
`completed` / `archived` の run には適用できず、その場合は
`archive → purge-work` を使う。

## 13.3 lifecycle、review、storage の直交性

Run を一つの `status` だけで分類しない。

* lifecycle: `run.status`
* review: `curation.review_status = unreviewed|reviewed`。`reviewed` は non-empty な
  `reviewed_by` / `reason` と timezone-aware ISO-8601 `reviewed_at` が揃った場合だけ有効
* storage tier: `storage.tier = hot|cold`
* representation: `storage.form = full|compacted|metadata_only`
* evidence selection: Result が所有する edge

新規 Run は `unreviewed`, `hot`, `full` で始まる。`runo runs review --reason ...` は
terminal Run の curation だけを更新し、科学的 evidence への採否は決めない。archive は
`tier=cold`、restore は `tier=hot`、purge-work は `tier=cold, form=compacted` を記録する。
retention date の到来だけで delete / purge してはならない。

## 13.4 TestAttempt lifecycle

TestAttempt は `prepared`, `submitted`, `passed`, `failed`, `skipped` を持つが、通常の Run
state machine には参加しない。現行 `runo test smoke|debug` は local receipt と input
snapshot の prepare までを行い、Slurm job は投入しない。terminal result は
`runo test record` で記録する。

cache key は kind、case、profile、source commit、executable hash、input hash、adapter、
adapter version の canonical hash である。source commit、executable hash、adapter version の
いずれかが空なら cache reuse を無効にする。TTL 内の同一 `passed` attempt がある場合は、
CLI は `SKIPPED` と表示して既存 T ID と `passed` receipt を返し、新しい T ID・directory・
receipt を作らない。cache hit 自体は既存 receipt の state を変更しない。
`record` と cache reuse は保存済み `input/` をその場で再ハッシュし、receipt の
`input_hash` と一致しなければ receipt を更新・再利用しない。
cleanup は年齢条件を満たす terminal attempt に限定し、同じ対象集合に active attempt が
あれば deletion 全体を拒否する。最初の move 前に cleanup receipt v2 へ各 directory の
device/inode、全 tree digest、entry fingerprint、TestAttempt receipt digest、input hash を
durable に固定する。staging rollback と初回削除前は完全 fingerprint を再検証する。deleting
phase の recovery は固定済み tree の未削除 entry が元 fingerprint の変更されていない部分集合
である場合だけ再開し、部分的な `rmtree` 失敗を許容する。差し替え、追加、残存 entry の drift
があれば receipt と tombstone を保持したまま fail closed とする。

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

    def probe_readiness(run_dir) -> dict:
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

`probe_readiness()` は scheduler terminal transition に付随する bounded probe とし、
full output enumeration や巨大 log の全読みを行わない。`simulator_status`, `outputs`,
`warnings` を返し、未対応 Adapter は `unknown` と explicit deep validation 導線を返す。

## 14.4 Attempt-aware output detection

再投入可能な simulator の Adapter は、manifest の current `job.job_id` と
`job.submitted_at` を attempt 境界として使う。current job の log が存在する場合、
過去 attempt の stdout / stderr / completion artifact を status や progress の根拠へ
混ぜない。`batch N/N` のような進捗表示は正常終了の証拠ではなく、simulator 固有の
completion artifact または scheduler の terminal state を完了判定に使う。

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
* `runo triage [PATH] [--json]` — 新規 state を作る前の read-only attention view。
  formal Run namespace を完全に列挙できない場合は件数を正常値として扱わず、walk error、
  symlink subtree、unsafe manifest を `run.namespace_unreadable` diagnostic として表示する

---

## 18.2 run 生成

* `runo experiments create TITLE --question QUESTION --intent INTENT --exit CRITERION
  --expires-at ISO (--baseline-run RUN | --baseline-reason WHY) [budget options]`
* `runo experiments list|inspect|review|close ...`
* `runo runs create CASE_NAME [--label LABEL] [--experiment E...] [--purpose PURPOSE]`
* `runo runs sweep [<survey.toml のあるディレクトリ>] [--offset N] [--limit N]` —
  既定は read-only plan。`--dry-run` も同じ動作
* `runo runs sweep <survey_dir> --apply --point REF... --expect-plan HASH`
* `runo runs sweep <survey_dir> --apply --all --expect-plan HASH`

新規 scaffold は `experiments.policy.require_experiment = true` のため、standalone Run にも
active Experiment が必要である。既存 project に policy section がない場合だけ互換既定値を
false とする。

---

## 18.3 job 実行

* `runo runs submit [<run_dir or run_id>]`
* `runo runs submit --all [<survey_dir>]` — ready plan の run を一括投入する。通常は確認を要求し、明示済みの自動実行では `--yes` で省略できる。

---

## 18.4 状態追跡

* `runo runs status [RUNS...]`
* `runo runs sync [RUNS...]`
* `runo runs review [RUN] --reason WHY [--reviewed-by ACTOR]`

`runs status` / `runs sync` は run_id・run dir・survey dir を複数指定できる。
`runs sync` を bulk モード (survey dir または複数指定) で呼び出した場合、
`job_id` 未記録の run と terminal state (`completed`, `failed`,
`cancelled`, `archived`, `purged`) の run は **silent skip** され、残りの
submitted / running な run のみが Slurm に問い合わせられる。
single-target モードでは "nothing to sync" notice を出してエラー扱いに
しない。

---

## 18.5 一覧

* `runo runs list [PATHS...]` — 既定では archived / purged と archived bundle 配下を除く active view
* `runo runs list [PATHS...] --include-archived` — archived / purged と archived bundle 配下を含める
* `runo runs list --status failed`
* `runo runs list --status archived` — 明示した archived run だけを表示する
* `runo runs list --tag production`
* `runo runs list --experiment E... --purpose explore`
* `runo runs list --review-status unreviewed`
* `runo runs list --storage-tier cold --storage-form compacted`

`--status archived|purged`、storage filter、`--include-archived` は all view を選ぶ。
それ以外の filter は active traversal を保つため、archived bundle 内の failed / cancelled Run を
意図せず混ぜない。

---

## 18.6 複製・派生

* `runo runs clone [<run_dir or run_id>] --dest <survey_dir>`
* `runo runs clone <run_id> --set key=value` — `origin.case` と `params_snapshot` から input/job を再生成し、manifest だけの差し替えで派生 run を作らない。
* `runo runs extend <run_id>` — completed 相当の snapshot から新しい immutable Run を作る。
* `runo runs regenerate <run_id> --dry-run` — frozen input と現在の case の差分確認だけを行う。

既存 Run の scientific identity は in-place 変更しない。差分を適用したい場合は clone / extend
により新しい Run ID を作る。completed scientific duplicate は同じ Experiment / Survey owner
edge のときだけ再利用し、別 owner の一致は baseline / Result evidence として明示参照する。

---

## 18.7 解析補助

* `runo analyze summarize [<run_dir or run_id>]`
* `runo analyze collect [<survey_dir>]`
* `runo analyze export [<run_dir or run_id>] --paper <paper-id>` — incomplete run を
  `--paper-status accepted` にする場合は `--accept-incomplete-reason <WHY>` を同じ
  command で必須とする

---

## 18.8 整理

* `runo runs archive <run_dir or run_id>` — completed → archived。既定では `runs/_archive/<元の runs/ 相対パス>` へ移動する。最初の metadata 変更・move より前に `.runops/lifecycle/archive_run-*.json` へ manifest/state の preimage と destination を durable に保存する。中断後は live manifest/state が receipt の exact preimage または receipt から一意に導ける transition/commit postimage と一致するときだけ forward-complete / rollback / receipt cleanup を許可し、同じ Run ID/state でも非所有 field が変化していれば一切上書き・move せず fail closed とする。Run ID、directory target、`--all` の再実行では通常 discovery より先に receipt の Run ID と元 source scope を検証し、既に移動済みの Run も recovery plan へ再列挙する。managed project の bulk discovery は canonical `runs/` active view に限定し、Result manifest と cold bundle child を含めない
* `runo runs archive <run_dir or run_id> --keep-in-place` — completed → archived の状態変更のみ行う
* `runo runs archive <run_dir or run_id> --move-to <archive_root>` — managed project では同一 filesystem の `runs/_archive/**` 内に限って archive root を変更する。project 外への退避は discovery、budget、Result protection を迂回するため拒否する
* `runo runs archive <parent_dir> --bundle` — `survey.toml` と配下 run を親ごと `runs/_archive/<元の runs/ 相対パス>` へ移動する。run state は保持し、submitted / running を含む場合は全体を変更せず拒否する。最初の marker write / move より前に source parent の `.runops-bundle-archive-*.receipt.toml` v1 へ source/destination、root directory identity、bundle scaffold identity、各 child の directory/tree identity と manifest exact pre/postimage、marker postimage を durable に固定する。中断後は同じ command が source/destination topology と全 image を再検証し、receipt が所有する未完了 phase だけを forward-complete する。drift / directory replacement / unknown artifact があれば rollback、上書き、move、receipt cleanup を行わず fail closed とする
* `runo runs archive <parent_dir> --bundle --adopt-archived` — 同じ親から個別 archive 済みの archived / purged run を検証して bundle へ採用する。確認前に対象 run ID と状態を表示し、競合や所有不明 path があれば変更せず拒否する。最初の move 前に `.tmp-adopt-*/receipt.toml` v2 を durable に保存し、各 Run の manifest pre/postimage digest、directory device/inode、tree identity と source bundle scaffold identity を固定する。中断後は同じ command が receipt、topology、live identity を再検査し、完全一致するときだけ forward-complete する。receipt 後の manifest drift、同じ ID/status を持つ directory への差し替え、未知 artifact は一切 move/update/cleanup せず fail-closed とし、receipt と staging を保持する。v1 以前の pending receipt は自動再開せず、pending transaction は `runo triage` に即時表示する
* `runo runs restore <run_dir or run_id>` — archived → completed。`archived_from` へフォルダごと戻し、全 artifact を保持する。in-place archive は状態だけ戻す。move 前に `.runops/lifecycle/restore_run-*.json` を durable に保存し、中断時は archive と同じ exact pre/postimage 検証を通る場合だけ同一 command で再開する。Run ID 再実行も通常 discovery より先に receipt から元 archive source を解決する
* `runo runs restore <archived_parent_dir> --bundle` — `.runops-archive.toml` の `archived_from` へ親ごと戻し、各 run state を保持する。source parent の `.runops-bundle-restore-*.receipt.toml` v1 に archive と同じ tree/manifest binding と marker preimage を move 前に保存し、process death 後は exact pre/postimage のみを同じ command で再開する。marker/manifest の drift 時は live data と receipt を診断用に保持し、自動 rollback しない
* `runo runs purge-work [<run_dir or run_id>]` — archived → purged。cached readiness が
  incomplete / unknown の場合は `--discard-incomplete --reason <WHY>` を同じ command に指定して
  review provenance を残す。sealed Result が削除対象の Run-owned path evidence を include して
  いる場合は拒否し、`storage.protected_by_results` に Result ID を記録する。reverse scan は
  canonical seal の `content_sha256`、README/evidence receipt、source integrity を再検証し、
  seal や include/exclude が改竄されていれば protection 不在として扱わず fail closed とする。対象 directory は
  同一 filesystem の tombstone へ全件退避してから metadata を確定し、途中失敗時は全件を
  rollback する。`status/.purge-pending.json` を最初の rename 前に保存し、manifest の
  `run.status=purged` を commit point とする。中断後は commit 前なら rollback、commit 後なら
  metadata と cleanup を forward-complete する。確定後の削除失敗は `cleanup_pending` として
  明示し、pending transaction は `runo triage` に表示する。receipt は commit 前後の canonical
  manifest digest、tombstone / target root の device/inode、purge target tree digest を固定する。
  commit 前の retry は完全な tree digest、commit 後の cleanup retry は固定済み root identity を
  照合するため、部分的な `rmtree` 失敗を再開でき、同名 directory への差し替えは拒否する。
  CLI は `purged` Run を通常は拒否し、厳密に検証できた pending receipt
  がある同一 path / Run ID retry だけを application の forward recovery へ通す
* `runo runs cancel [<run_dir or run_id>]` — submitted/running → cancelled (`scancel` と `sync` をまとめて実行する安全経路)
* `runo runs delete [<run_dir or run_id>]` — created / cancelled / failed の run ディレクトリをハード削除 (ライフサイクル外、completed/archived には不可)

smoke / debug は整理対象となる正式 Run を作らず、次の分離 command を使う。

* `runo test smoke CASE [identity/cache options]`
* `runo test debug CASE [identity/cache options]`
* `runo test list [PATH] [--json]`
* `runo test record T... --result passed|failed|skipped [--observation TEXT]`
* `runo test clean --older-than-days N [--path PATH]`

---

## 18.9 Quantity-bounded research workspace

研究記憶は日数ではなく Unicode 文字数、件数、bytes で上限を持つ。既定値は
`runops.toml [research.workspace]` に置く。

* `CURRENT.md`: mutable な現在判断。既定 20,000 文字を hard limit とし、50 行、
  path 参照 10 件、日付・時刻で始まる時系列見出し 3 件を compact guidance の warning
  threshold とする
* `journal/active.md`: append-only。既定 64,000 文字を越える前に原文のまま
  `journal/archive/JNNNN.md` へ rotation
* `results/RNNNN-topic/README.md`: Result ごとの唯一の narrative。既定 30,000 文字
* `results/RNNNN-topic/manifest.toml`: claim、outcome、Result-local evidence edge、seal receipt
* `results/RNNNN-topic/artifacts/`: Markdown 禁止。既定 50 files / 200 MiB
* active result は既定 8 件。archive/restore は rename による可逆操作
* `.runops/work/<goal-id>/` は provisional output で Git 管理しない

AI は重要度を推測して既存 evidence を削除・要約置換しない。journal entry には
`--kind` と `--subject` で Experiment / Survey / Run を軽量に紐付けられる。rotation は
原文を保持し、durable result への昇格は明示的に行う。
compact guidance の超過は通常 lint/check を失敗させない。`runo lint --strict` を
明示した場合だけ warning を gate として扱う。`CURRENT.md` に作業日誌や artifact inventory
を再展開せず、時系列は journal、残す詳細解析は result、網羅的な artifact provenance は
export/source index に置く。

```text
research/journal + materials + .runops/work
  -> research/CURRENT.md OR research/results/RNNNN-topic
  -> .runops/insights / .runops/facts.toml (必要な場合だけ)
```

旧 `notes/`, `analysis/cross_run/`, `analysis/**/*.md`, HarnessOps metadata 等は
`runo research migrate-legacy` が `MIGRATION.json` 付き recovery archive へ移し、
`--restore` で復元できる。自動 purge は提供しない。

正式な experiment narrative は分散させない。case / survey root の `notes.md` と
Run `analysis/notes.md` は legacy slot として `runo lint` が warning を返す。生成途中は
`.runops/work/`、時系列は journal、現在判断は `CURRENT.md`、残す説明は Result の
`README.md` 一枚へ置く。

### 18.9.2 Story acceptance audit (experimental)

`analysis/stories/<story-id>/story.toml` は `schema_version = 1` を持ち、各 step の
`required_artifacts` と `acceptable_status` は 1 件以上の非空文字列からなる TOML array
とする。source `kind` は `run`, `survey`, `comparison`, `path` のいずれかで、実際に
検出した source 種別と一致しなければ audit を生成しない。relative source path は
process の cwd ではなく project root から解決する。

source が 1 件でも欠落した audit は、別 source に十分な artifact があっても
`blocked` とする。artifact index 不在などの warning がある場合、全 step が covered
でも overall status は `partial` を上限とする。story の明示 `--id` は validation 後も
変更せず、人間向け name が ASCII slug を生成できない場合だけ deterministic な
`story-<hash>` を生成する。

---

## 19. コマンド動作定義

## 19.1 `create`

* Case を読み込む
* project policy が要求する場合は active Experiment と purpose 一致を検査する
* project-wide lock と monotonic sequence で `run_id` を予約する。失敗で番号に gap が
  生じても再利用しない。ただし completed-equivalent の scientific reuse が成功し、
  新規 Run を一切公開しなかった最新予約は同じ lock 下で解放し、反復する AI request が
  日次 sequence を消費しない
* 指定 survey ディレクトリ配下に run ディレクトリを作成
* input 生成
* `job.sh` 生成
* `manifest.toml` 生成
* intent、condition/input/execution/provenance hash、unreviewed curation、hot/full storage を freeze
* 状態を `created` にする

---

## 19.2 `sweep`

* `survey.toml` を読み込む
* parameter 組合せの候補数を lazy に計数し、requested page だけを列挙する
* 既定動作は candidate ref、point hash、plan hash、概算 core-hours、admission issue を返し、
  directory と Run ID を作らない
* apply は plan hash を再計算し、明示選択と全 budget / Experiment gate を再検査する
* 選択した未 materialize point だけを survey 親ディレクトリ直下に生成する
* 既存 `survey.id + point_id + plan_hash` は frozen parameter / input / provenance identity を
  再検証して同じ Run を idempotently 返す。これは別 Run 間の scientific reuse ではない
* 各 manifest に Experiment / Survey intent、point / plan identity、retention を記録する

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
  新規 lock の directory entry も親 run directory の fsync で永続化する。claim は
  definitive な scheduler rejection または manifest/state の保存完了時だけ clear する
* scheduler timeout、exit 0 後の job_id parse failure、その他受付結果を確定できない
  error は outcome-unknown として `pending` claim を保持する。自動再 submit せず、
  scheduler と local state を reconcile する
* persistence failure や process interruption で残った durable claim は後続 submit を
  block する。明示的 retry は同じ lock 内で terminal state を再検証し、claim を
  durable に clear してから `created` へ reset する
* `created` のまま `pending` / `accepted:<job_id>` claim が残る場合は scheduler の
  acceptance を照合し、manifest と claim を手動 reconcile するまで submit を block する
* scheduler failure では manifest と pre-submit state を変更しない
* scheduler acceptance 後に job attempt、job_id、`submitted` state を manifest へ保存する。
  `submitted_at` は attempt 前の artifact と同一秒内でも順序を判別できるよう、clock が
  持つ subsecond 精度を切り捨てず ISO 8601 で保存する
  manifest の atomic replace は temp file と親 run directory を fsync してから claim を
  clear する
* acceptance 後の persistence failure は accepted job_id と failure phase を持つ typed
  error として返し、同じ plan を自動再 submit しない
* `runs delete` は top-level symlink を拒否し、submit と同じ run lock を保持して state
  と claim を再確認する。許可後は run directory を同一親の hidden tombstone へ atomic
  rename して元 path を先に閉じ、non-empty claim、submit 済み state、並行 submit の
  いずれからも orphan job を作らない

---

## 19.4 `status` / `sync`

`status` は観測表示、`sync` は manifest 更新を担当する。

### `status`

* manifest の `run.status` を表示する
* `job_id` がある場合は `squeue` / `sacct` で live Slurm state を best-effort 表示する
* manifest と `status/state.json` は更新しない
* `--short` / `--summary` では live Slurm query を行わず、manifest のみを読む
* completed run では current attempt の `status/readiness.json` があれば再利用し、
  analysis status、reason code、recommended action / exact command を表示する
* bounded cache が `unknown` の場合だけ deep evaluation を 1 回行い、その結果で
  cache を置き換える。deep evaluation が `unknown` でも以後は再利用する
* `runs list`、`runs dashboard --all`、MCP `runops.run.list` は bulk latency を
  bounded に保つため cache だけを読み、completed run の cache miss は
  `unknown` / `readiness_not_cached` / `deep_validate` と exact status command を返す。
  bulk view 自体は deep evaluation を起動しない

### `sync`

* `squeue` / `sacct` により Slurm 状態を RunState に変換する
* scheduler query は mutation lock 外で行い、結果の反映時は per-Run submission lock 内で
  run ID、job ID、現在 state を manifest から再読込する。query 後に identity / state が
  変わった stale observation は manifest / state を変更せず拒否する
* managed Run を completed へ遷移させる場合は Experiment → per-Run submission →
  Run namespace の順で lock を保持する。formal admission の最終 budget scan / publication と
  completed-equivalent backlog の増加を同じ namespace boundary で直列化する
* `status/state.json` を更新する
* manifest の `run.status` と `run.last_slurm_state` を同期する
* completed へ遷移した run では Adapter の bounded `probe_readiness()` を同じ action
  内で 1 回実行し、attempt-aware な `status/readiness.json` を保存する
* action result は execution / simulator / analysis status、reason code、partial output、
  recommended action / exact command をまとめて返し、通常の診断に別 status call を要求しない
* bulk モード (survey dir または複数 RUNS) では `job_id` 未記録 / terminal
  state な run を silent skip し、残りのみを処理する

---

## 19.5 `research`

* `status/check`: configured budget に対する文字数、件数、bytes、layout issue を返す
* `append TITLE BODY [--kind KIND] [--subject ID]`: JST timestamp と任意の分類・subject を
  active journal に append し、必要なら先に rotation
* `rotate [--force]`: active journal 全文を次の `JNNNN.md` へ no-clobber で保存
* `new-result NAME`: `RNNNN-slug/{README.md,manifest.toml,artifacts/}` を作る
* `check-result RESULT`: canonical / legacy layout、claim、outcome、evidence owner、source receipt、
  seal integrity を read-only に検査する
* `seal RESULT --claim ... --outcome ... --selection-reason WHY --evidence-run ...|--evidence-path ...`: 少なくとも一つの
  included evidence を要求し、README と evidence source の hash / bytes を固定する。同一内容の
  再実行は idempotent、異なる内容での reseal は拒否する
* `archive/restore RESULT_ID`: result directory を内容変更せず移動する
* `migrate-legacy [--dry-run|--restore]`: 旧 workspace を決定的・可逆に移行する
* 空タイトル/本文、symlink、hardlink、不正 UTF-8、overwrite は fail closed

evidence selection は Result の local edge とし、Run manifest に global `selected` flag を
書かない。`--evidence-run` は project の canonical `RYYYYMMDD-NNNN` manifest を解決する。
T ID と `.runops/test-runs/**` の path は scientific Result evidence として必ず拒否する。
path evidence は Run 配下または Result `artifacts/` 配下の regular file に限定する。Run owner は
project-wide strict discovery が返す canonical Run root から決め、payload 内の nested
`manifest.toml` による owner の差し替えを許さない。
included Run または Run-owned path を seal する前に、その Run が completed 相当で理由付き
review 済みであり、4 種の identity hash、source commit、canonical executable hash、
simulator/package version の三つすべて、baseline、input snapshot を持つことを検査する。
dirty source は source commit の有無にかかわらず diff 参照も必要である。
seal commit の直前にも evidence receipt に加えて実 input hash、Run status、curation を
再検査し、初回 quality gate 後に source readiness が変わった Result は draft のまま拒否する。
sealed Result が include した `work/outputs|restart|tmp` の Run-owned path evidence は
`purge-work` の reverse-reference gate で保護する。この scan 自体が seal content hash と
README/evidence receipt を再検証し、改竄された sealed Result が参照を隠しても削除を許可しない。

## 19.5.1 `test`

* `smoke|debug`: case input を `.runops/test-runs/T.../input/` に snapshot し、
  `test-receipt.toml` を `prepared` で作る。scheduler は呼ばない
* `record`: prepared / submitted attempt に `passed|failed|skipped` と観測を記録する
* `clean`: cutoff より古い terminal attempt を preflight 後に削除する
* cache hit は既存 passed attempt を返すだけで、新しい directory を作らない

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

ツールは `runs/` 以下を **再帰探索** し、`manifest.toml` を持つディレクトリを Run とみなす。

これにより、`runs/` 以下の多重ネストに対応する。

query view は CLI、MCP、Agent context で同じ application service を使う。

* active view（既定）: `archived|purged` state と archive marker 配下を除く
* all view: archived / purged と archive bundle 配下も含む
* explicit status filter: `--status archived` のような filter は必要な all view を選ぶ

`.runops/test-runs/` は `manifest.toml` を持たず、Run discovery の対象外である。project root
から query した場合も canonical `runs/` tree を scope とし、TestAttempt を混ぜない。
`.tmp-*` / `.delete-*` transaction directory も通常 discovery から除外する。24時間以上残った
ものは `runo triage` が orphan candidate として可視化するが、自動削除しない。
したがって formal Run / Survey の出力先は、`runs/` からの相対 path のどの component にも
`.tmp-*` / `.delete-*` を含めてはならない。また既存 `manifest.toml` を持つ Run directory
自身またはその子孫には新しい formal Run / Survey を作らない。どちらも strict discovery
から不可視になるため、create / sweep / clone / extend は materialization 前に拒否する。
この検査は preflight だけでなく、project-wide Run namespace guard を保持した staged
directory の公開 CAS 直前にも再実行する。preflight 後に親 directory が formal Run として
公開された場合は、nested Run を公開せず staging を除去して fail-closed とする。

canonical Agent context と MCP `runops.project.status|inspect` は、active view の件数を
公開する前に all view を安全に完全走査できることを確認する。walk error、symlink subtree、
unsafe manifest 等で完全走査できない場合、`runs.namespace_available = false`、
`runs.total = null` とし、run 由来の Experiment 件数と `recent_failures` も `null` にする。
canonical tree 内に invalid TOML、unreadable file、または formal Run identity/status contract
を満たさない manifest が一つでもある場合も同様に、正常な Run だけの部分集計は公開しない。
既知の Experiment metadata は捨てずに返し、context diagnostic と MCP warning envelope で
不完全性を明示する。これは「Run が 0 件」という正常結果とは異なる。

---

## 20.1 一意性

同一 Project 内で `run_id` の重複は不可とする。canonical context、triage、MCP
`runops.project.status|inspect` の strict 集計は active view だけでなく archived / purged を含む
canonical `runs/` namespace 全体で重複を検査する。一つでも重複があれば件数を公開せず、
namespace unavailable と duplicate ID / path の diagnostic を返す。

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

* `experiments/E...toml`
* `case.toml`
* `survey.toml`
* `manifest.toml`
* `.runops/test-runs/T.../test-receipt.toml`
* `status/state.json`
* `analysis/summary.json`
* `research/results/RNNNN-*/manifest.toml`

Agent による主要操作:

* bounded Experiment と Case / Survey 生成補助
* read-only Survey plan と explicit point selection
* smoke / debug TestAttempt の分離実行
* 選択済み Run の生成
* 失敗 run 抽出
* summary 収集
* 図生成補助
* tags 更新
* terminal Run review と Result evidence seal

Agent は候補を列挙しただけで directory を作らない。`sweep` の apply、`--all`、Experiment
`decision=expand`、submit、archive / purge / delete はそれぞれ独立した gate とする。
retention hint や AI の重要度推測だけで evidence を削除しない。

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
* bounded Experiment admission / review
* Case 読込
* lazy Survey plan / explicit materialization
* run 生成
* run_id 採番
* `manifest.toml` 生成
* TestAttempt namespace / receipt / cache reuse
* Simulator Adapter
* Launcher Profile
* Slurm submit
* 状態同期
* run 一覧取得
* survey 単位集計
* Result-local evidence / immutable seal
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
* Experiment は問い・baseline・budget・有効期限・exit criteria を持つ 1 file admission unit
* Survey plan は既定 read-only、選んだ point だけを明示 materialize
* smoke / debug は T ID の TestAttempt として正式 Run から分離
* lifecycle、review、storage、Result evidence selection は直交する
* simulator 固有処理は Adapter
* MPI 起動方式は Launcher Profile
* `job.sh` で `srun` / `mpirun` / `mpiexec` を直接実行
* `pip install -e .` は必須ではなく、resolver で柔軟に扱う

---
