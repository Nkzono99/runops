# TOML Configuration Reference

runops が読み書きする設定、manifest、解析 metadata の field リファレンスです。
各設定 file は先頭の `#:schema` comment で JSON Schema を参照できます。

通読用ではありません。対象 file の節へ移動し、必要な field だけ参照してください。

## File index

| 対象 | 節 |
|---|---|
| project | [runops.toml](#runopstoml) |
| simulator / launcher / site | [simulators.toml](#simulatorstoml)、[launchers.toml](#launcherstoml)、[site.toml](#sitetoml) |
| experiment / case / survey | [experiment TOML](#experiment-toml)、[case.toml](#casetoml)、[survey.toml](#surveytoml) |
| run state | [manifest.toml](#manifesttoml)、[Run Directory Structure](#run-directory-structure) |
| smoke / debug | [test-receipt.toml](#test-receipttoml) |
| analysis / publication | [analysis outputs](#analysissummaryjson)、[survey summary](#survey-summary-outputs)、[publication export](#publication-export-outputs) |
| research result / design / environment | [Result manifest](#canonical-result-manifest)、[campaign.toml](#campaigntoml)、[environment.toml](#runopsenvironmenttoml) |

利用手順は [AI エージェントではじめる](get-started-with-agent.md)、内部責務は
[アーキテクチャ](architecture.md) を参照してください。

---

## runops.toml

Project-level configuration. One per project root.

```toml
[project]
name = "emses-sheath"           # Required. Project name
description = "EMSES sheath simulations"  # Optional.
version = "1.0"                 # Optional.

[project.codex_plugins.analysis-context]
display_name = "Analysis Context"
visibility = "private-or-gated"
reason = "Project-specific analysis and handoff workflow guidance."
capabilities = ["analysis-workflow", "handoff"]
install_hint = "codex plugin add analysis-context@project"

[experiments.policy]
require_experiment = true
max_active_experiments = 5
default_max_materialized_runs = 3
max_unreviewed_completed_runs = 12
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `project.name` | string | Yes | Project identifier |
| `project.description` | string | No | Human-readable description |
| `project.version` | string | No | Project version |
| `project.codex_plugins` | table | No | Project-wide Codex plugin recommendations not tied to one simulator or site. |

### `[project.codex_plugins.<plugin>]`

project 全体に紐づく外部 Codex plugin 推薦。解析 workflow、チーム内
handoff、project 固有の reference plugin など、simulator / site どちらにも
属さない導線を置く。runops は plugin を自動 install / enable しない。
`runo plugins`、`runo setup` の出力、`runo update-harness` で再生成される
`AGENTS.md` / `CLAUDE.md` はこの project-wide 推薦を同じ inventory として扱う。

| Field | Type | Description |
|-------|------|-------------|
| `display_name` | string | 表示名 |
| `visibility` | string | `"public"` または `"private-or-gated"` |
| `reason` | string | 推奨理由 |
| `capabilities` | string[] / string | plugin に委譲する役割ラベル。配列を推奨し、単一 role は文字列でも可。例: `"input-review"`, `"run-diagnose"` |
| `install_hint` | string | 導入コマンドまたは手順 |
| `activation_hint` | string | install 後の有効化・再起動手順 |

同じ plugin 名が adapter、simulator、project、site の複数スコープから推薦された場合、
表示名、理由、導入手順、visibility は最初の推薦を使い、`source` と
`capabilities` は統合される。project / site 側は adapter を編集せずに追加の委譲
役割だけを載せられる。

### `[research.workspace]` section (optional)

active research memory の量と `CURRENT.md` の compact guidance を設定する。

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `current_chars` | integer | `20000` | `CURRENT.md` の hard limit |
| `current_lines` | integer | `50` | `CURRENT.md` の推奨最大行数。超過は warning |
| `current_path_references` | integer | `10` | local path-like 参照の推奨最大数。超過は warning |
| `current_chronological_headings` | integer | `3` | 日付・時刻で始まる見出しの推奨最大数。超過は warning |
| `journal_segment_chars` | integer | `64000` | active journal segment の文字数上限 |
| `result_readme_chars` | integer | `30000` | result README の文字数上限 |
| `active_results` | integer | `8` | active result 数の上限 |
| `result_artifact_files` | integer | `50` | result ごとの artifact file 数上限 |
| `result_artifact_bytes` | integer | `209715200` | result ごとの artifact 合計 bytes 上限 |

compact guidance は普段の作業を止めない。`runo lint --strict` を選んだ場合だけ
warning を gate として扱う。

### `[experiments.policy]` section (optional)

formal Run materialization の project-wide admission / WIP policy。

| Field | Type | Legacy default | New scaffold | Description |
|-------|------|----------------|--------------|-------------|
| `require_experiment` | boolean | `false` | `true` | standalone Run と Survey materialization に active Experiment を要求 |
| `max_active_experiments` | integer >= 1 | `5` | `5` | 同時に active にできる Experiment 数 |
| `default_max_materialized_runs` | integer >= 1 | `3` | `3` | Survey-local cap 未指定時の directory 上限 |
| `max_unreviewed_completed_runs` | integer >= 0 | `12` | `12` | 全 Experiment と未所属を横断して formal Run を数える、未 review completed Run の project 上限 |

section がない既存 project は互換性のため `require_experiment = false`。`runo init` が作る
新規 project は section を明示し、`true` にする。policy を有効化する前に active な問いを
Experiment として作り、今後生成する Survey へ `experiment_id` を追加する。
`max_unreviewed_completed_runs` は `require_experiment` と独立した project gate であり、
Experiment 未所属の create / Survey materialization / clone / extend / retry にも適用する。
このときも `runs/` の strict scan が不完全なら件数を 0 とみなさず admission を拒否する。

### `[knowledge]` section (optional)

External shared knowledge source integration. If absent, only local knowledge (insights and facts) is used.

```toml
[knowledge]
enabled = true                       # Enable knowledge integration
mount_dir = "refs/knowledge"         # Base mount directory
derived_dir = ".runops/knowledge"    # Generated files directory
auto_sync_on_setup = true            # Sync sources during `runo setup`
generate_claude_imports = true       # Generate CLAUDE.md @import stubs

[[knowledge.sources]]
name = "shared-lab-knowledge"        # Source identifier
type = "git"                         # "git" or "path"
url = "git@github.com:lab/kb.git"   # Git URL (for type = "git")
ref = "main"                         # Git ref to checkout
mount = "refs/knowledge/shared-lab-knowledge"  # Mount path
profiles = ["common-analysis", "emses-basic"]  # Enabled profiles

[[knowledge.sources]]
name = "personal-knowledge"
type = "path"
path = "../hpc-knowledge"            # Filesystem path (for type = "path")
mount = "refs/knowledge/personal-knowledge"
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `knowledge.enabled` | bool | No | `true` | Enable knowledge integration |
| `knowledge.mount_dir` | string | No | `"refs/knowledge"` | Base directory for source mounts |
| `knowledge.derived_dir` | string | No | `".runops/knowledge"` | Directory for generated files |
| `knowledge.auto_sync_on_setup` | bool | No | `true` | Auto-sync on `runo setup` |
| `knowledge.generate_claude_imports` | bool | No | `true` | Generate `imports.md` for CLAUDE.md |
| `knowledge.sources[].name` | string | Yes | — | Source identifier |
| `knowledge.sources[].type` | string | Yes | — | `"git"` or `"path"` |
| `knowledge.sources[].url` | string | Conditional | — | Git URL (required when type = "git") |
| `knowledge.sources[].path` | string | Conditional | — | Filesystem path (required when type = "path") |
| `knowledge.sources[].ref` | string | No | `"main"` | Git ref to checkout |
| `knowledge.sources[].mount` | string | No | `"<mount_dir>/<name>"` | Relative mount path |
| `knowledge.sources[].profiles` | string[] | No | `[]` | Enabled profile names |

Profiles can be toggled later with:

```bash
runo knowledge profile enable shared-lab-knowledge common-analysis
runo knowledge profile disable shared-lab-knowledge emses-basic
```

For `kind = "profiles"` repositories, an optional repo-root `entrypoints.toml` can declare the exact files imported into `.runops/knowledge/enabled/imports.md`:

```toml
imports = ["docs/agent-user-guide.md"]

[profiles.common-analysis]
imports = ["profiles/common-analysis.md", "analysis/recipes/common.toml"]
```

---

## simulators.toml

Simulator adapter definitions. Declares which simulators are available in the project.

```toml
[simulators.emses]
adapter = "emses"
resolver_mode = "package"
executable = "mpiemses3D"
modules = ["intel/2023.2", "intelmpi/2023.2"]

[simulators.beach]
adapter = "beach"
resolver_mode = "package"
executable = "beach"
```

### `[simulators.<name>]`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `adapter` | string | Yes | Adapter name (`emses`, `beach`, `generic`) |
| `resolver_mode` | string | No | How to find the executable: `package` (pip installed), `local_executable` (PATH), `local_source` (build from source) |
| `executable` | string | No | Executable name or path |
| `source_repo` | string | No | Source repository path (`local_source` mode only) |
| `build_command` | string | No | Build command (`local_source` mode only) |
| `modules` | string[] | No | Simulator-specific HPC modules (e.g. hdf5, fftw). Site-common modules (intel, intelmpi) are defined in `launchers.toml`. Both are merged in job.sh. |
| `codex_plugins` | table | No | Project-side Codex plugin recommendations for this simulator. Used when workflow guidance lives outside runops / adapter packages. |

### `[simulators.<name>.codex_plugins.<plugin>]`

simulator 設定に紐づく外部 Codex plugin 推薦。Adapter の `codex_plugins()` を
変更できない project 固有 workflow や、外部 adapter package が未導入の時にも、
推薦 metadata を project 側で明示できる。runops は plugin を自動 install / enable
しない。

| Field | Type | Description |
|-------|------|-------------|
| `display_name` | string | 表示名 |
| `visibility` | string | `"public"` または `"private-or-gated"` |
| `reason` | string | 推奨理由 |
| `capabilities` | string[] / string | plugin に委譲する役割ラベル。配列を推奨し、単一 role は文字列でも可。例: `"parameter-design"`, `"output-analysis"`, `"cookbook"` |
| `install_hint` | string | 導入コマンドまたは手順 |
| `activation_hint` | string | install 後の有効化・再起動手順 |

### resolver_mode

- **`package`** (recommended): Executable is pip-installed into `.venv` from the adapter's package spec. For simulator packages backed by Git repositories, this means a git-pinned/package install rather than an editable checkout. This is the default for reproducible runs because provenance can record the resolved source and `runo update` can follow upstream package specs. When generated `job.sh` activates the project `.venv`, runops prefers `.venv/bin/<executable>` over a command path resolved from the run-creation shell and warns if that shell path would bypass the job environment.
- **`local_executable`**: Executable is on PATH or specified as an absolute path.
- **`local_source`**: Build from source. `source_repo` and `build_command` must be set.

Editable installs, such as `uv pip install -e refs/MPIEMSES3D`, are an opt-in
development workflow for hacking on the simulator itself. They are not the
default project runtime. `runo update` upgrades the package specs declared by
the active adapters; if a target package is currently editable-installed, it
warns before replacing that editable install. Use `runo update --yes` or
`runo update --force` only when that replacement is intentional.

Adapter 名は runops 同梱 adapter または外部 Python package が公開する
`runops.adapters` entry point に対応する。外部化された simulator adapter を使う
場合は、runops CLI と同じ Python environment にその package を入れる。例:

```bash
uvx --from runops --with my-solver-runops runo runs create
```

---

## launchers.toml

MPI launcher profiles. Defines how simulators are launched (srun, mpirun, mpiexec) and site-specific job configuration.

### Basic srun (standard Slurm)

```toml
[launchers.srun]
kind = "srun"
use_slurm_ntasks = true
```

### camphor site profile

```toml
[launchers.camphor]
kind = "srun"
use_slurm_ntasks = true
resource_style = "rsc"
modules = [
    "intel/2023.2",
    "intelmpi/2023.2",
    "hdf5/1.12.2_intel-2023.2-impi",
    "fftw/3.3.10_intel-2022.3-impi",
]
stdout = "stdout.%J.log"
stderr = "stderr.%J.log"
```

### mpirun

```toml
[launchers.openmpi]
kind = "mpirun"
command = "mpirun"
args = "--bind-to core"
modules = ["openmpi/4.1"]
```

### `[launchers.<name>]`

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `kind` | string | Yes | — | Launcher kind: `srun`, `mpirun`, `mpiexec` |
| `command` | string | No | same as `kind` | Launcher executable command |
| `use_slurm_ntasks` | bool | No | `false` | Rely on `SLURM_NTASKS` env var instead of explicit `--ntasks` flag |
| `args` | string | No | `""` | Extra launcher arguments (space-separated string) |
| `extra_options` | string[] | No | `[]` | Extra launcher options (list form, alternative to `args`) |
| `resource_style` | string | No | `"standard"` | SBATCH resource style: `standard` or `rsc` |
| `modules` | string[] | No | `[]` | HPC modules to load in job.sh |
| `stdout` | string | No | `%j.out` | Custom stdout file format |
| `stderr` | string | No | `%j.err` | Custom stderr file format |
| `extra_sbatch` | string[] | No | `[]` | Additional raw `#SBATCH` directives |
| `env` | table | No | `{}` | Site-specific environment variables |

### resource_style

- **`standard`**: Emits `#SBATCH --ntasks=N`, `#SBATCH --nodes=N`, etc.
- **`rsc`**: Emits `#SBATCH --rsc p=N:t=T:c=C` (camphor/FUJITSU-style). `p` = processes, `t` = threads per process, `c` = cores per process.

---

## site.toml

HPC サイト固有の環境設定。`runo init` でサイトプロファイル選択時に自動生成される。
Launcher (MPI 起動方式) とは独立に、ジョブスクリプト生成に影響する環境設定を管理する。

```toml
[site]
name = "camphor"
resource_style = "rsc"
modules = ["intel/2023.2", "intelmpi/2023.2"]
stdout = "stdout.%J.log"
stderr = "stderr.%J.log"

[site.env]
OMP_PROC_BIND = "spread"

[site.simulators.emses]
modules = ["hdf5/1.12.2_intel-2023.2-impi", "fftw/3.3.10_intel-2022.3-impi"]

[site.codex_plugins.kudpc-hpc-codex-plugin]
display_name = "KUDPC HPC"
visibility = "private-or-gated"
reason = "KUDPC host routing and Slurm workflow guidance."
install_hint = "codex plugin marketplace add ..."
activation_hint = "Start a new Codex thread after installing."
```

### `[site]`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | No | サイト名 |
| `resource_style` | string | No | `"standard"` or `"rsc"` |
| `modules` | string[] | No | サイト共通モジュール |
| `stdout` | string | No | カスタム stdout ファイル名 |
| `stderr` | string | No | カスタム stderr ファイル名 |
| `extra_sbatch` | string[] | No | 追加 `#SBATCH` ディレクティブ |
| `setup_commands` | string[] | No | 実行前セットアップコマンド |

### `[site.env]`

ジョブスクリプト内で `export` する環境変数。

### `[site.simulators.<name>]`

| Field | Type | Description |
|-------|------|-------------|
| `modules` | string[] | シミュレータ固有の追加モジュール (サイト共通モジュールとマージされる) |

### `[site.codex_plugins.<name>]`

サイト選択に応じて推奨する外部 Codex plugin。`runo init` / `runo setup` の
出力と生成 harness に導入導線として表示される。runops は plugin を自動 install
せず、ユーザー local な Codex 環境で `/plugins` または `codex plugin ...` により
有効化する。

| Field | Type | Description |
|-------|------|-------------|
| `display_name` | string | 表示名 |
| `visibility` | string | `"public"` または `"private-or-gated"` |
| `reason` | string | 推奨理由 |
| `capabilities` | string[] / string | plugin に委譲する役割ラベル。配列を推奨し、単一 role は文字列でも可。例: `"host-role-routing"`, `"slurm-jobs"` |
| `install_hint` | string | 導入コマンドまたは手順 |
| `activation_hint` | string | install 後の有効化・再起動手順 |

---

## Experiment TOML

`experiments/EYYYYMMDD-NNNN--slug.toml` は、一つの問いを formal Run の生成対象として
admit する single-file contract。`runo experiments create` が atomic に作成し、ID と
filename prefix は不変である。

```toml
schema_version = 1

[experiment]
id = "E20260901-0001"
title = "incidence-angle pilot"
question = "At which angle does the surface-potential trend change?"
lifecycle = "active"
intent = "explore"
decision = "pending"
outcome = "unknown"
created_at = "2026-09-01T00:00:00+00:00"
created_by = "human"

[baseline]
run_ids = ["R20260831-0001"]
reason = ""

[budget]
max_planned_points = 30
max_materialized_runs = 6
max_active_runs = 3
max_core_hours = 100.0
max_unreviewed_runs = 6
expires_at = "2099-10-01T00:00:00+00:00"

[exit]
criteria = ["pilot の安定性と trend を判定できる"]
review_due = ""

[review]
reason = ""
reviewed_at = ""
successor = ""
```

| Field | Type | Rule |
|-------|------|------|
| `schema_version` | integer | `1` |
| `experiment.id` | string | `EYYYYMMDD-NNNN`; file basename はこの ID で始める |
| `experiment.lifecycle` | enum | `draft`, `active`, `closed`。CLI create は active を作る |
| `experiment.intent` | enum | `explore`, `confirm`, `validate`, `reproduce` |
| `experiment.decision` | enum | `pending`, `expand`, `revise`, `stop`, `accept` |
| `experiment.outcome` | enum | `unknown`, `supported`, `refuted`, `inconclusive`, `invalid` |
| `baseline.run_ids` | string[] | canonical Run ID の unique list |
| `baseline.reason` | string | baseline Run を使わない理由 |
| `budget.max_planned_points` | integer >= 1 | lazy plan の候補数上限 |
| `budget.max_materialized_runs` | integer >= 1 | この Experiment が所有する Run directory 数上限 |
| `budget.max_active_runs` | integer >= 1 | `created|submitted|running` の WIP 上限 |
| `budget.max_core_hours` | number > 0 | 宣言 resource による累積上限 |
| `budget.max_unreviewed_runs` | integer >= 0 | 当該 Experiment が所有する未 review completed Run の上限。完全な review record がない Run も数える |
| `budget.expires_at` | timezone-aware ISO-8601 string | 必須の formal Run admission deadline。作成時は未来、到達後は review / close 以外の新規 Run 生成を拒否 |
| `exit.criteria` | non-empty string[] | 観測可能な stop / decision criterion |
| `exit.review_due` | string | 任意の ISO-8601 review deadline |

`baseline.run_ids` と `baseline.reason` は exactly one を non-empty にする。
`max_materialized_runs <= max_planned_points`、`max_active_runs <= max_materialized_runs`
でなければならない。`review` / `close` は同じ file を更新するが、所属 Run の lifecycle や
path は変更しない。

---

## case.toml

Case template definition. Recommended location: `cases/<simulator>/<case_name>/case.toml`.
Legacy `cases/<case_name>/case.toml` is still readable for backward compatibility.

`runo case new` は simulator ごとのベース入力テンプレート
(`plasma.toml`, `beach.toml` など) を case ルートに生成する。
追加の入力ファイルは `cases/<simulator>/<case_name>/input/` に置ける。
`runo runs create` / `runo runs sweep` 実行時、`input/` 以下は
ディレクトリ構造ごと run の `input/` に自動コピーされ、その後 adapter が
ベーステンプレートに `[params]` を適用した入力で上書きする。

```
cases/
  emses/
    flat_surface/
      case.toml          # メタデータ・パラメータ定義
      plasma.toml        # simulator 固有のベース入力テンプレート
      summarize.py       # run 後の解析・可視化フック
      input/             # 追加ファイル (optional)
```

```toml
[case]
name = "flat_surface"
simulator = "emses"
launcher = "srun"
description = "Flat surface sheath simulation"

[classification]
model = "sheath"
submodel = "flat_surface"
tags = ["2d", "electrostatic"]

[job]
partition = "gr20001a"
nodes = 1
ntasks = 800
walltime = "120:00:00"

[params]
"tmgrid.nx" = 4000
"tmgrid.ny" = 1
"tmgrid.nz" = 800
"tmgrid.dt" = 0.002
"jobcon.nstep" = 400000
"plasma.wc" = 0.0
"plasma.phiz" = 0.0
```

### `[case]`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Case name (used in run_id generation) |
| `simulator` | string | Yes | Simulator name (must match `simulators.toml`) |
| `launcher` | string | No | Launcher profile name (must match `launchers.toml`) |
| `description` | string | No | Human-readable description |

### `[classification]`

Optional metadata for organizing runs.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `model` | string | No | Physical model category (e.g. `sheath`, `wave`) |
| `submodel` | string | No | Subcategory (e.g. `flat_surface`, `periodic`) |
| `tags` | string[] | No | Free-form tags for filtering |

### `[job]`

Slurm job parameters. These become `#SBATCH` directives in `job.sh`.

#### Standard mode (`resource_style = "standard"`)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `partition` | string | No | Partition/queue name. Can be overridden at submit time with `runo runs submit -qn <name>` |
| `qos` | string | No | Slurm QOS name. Emits `#SBATCH --qos=<value>`. Can be overridden with `runo runs submit --qos <name>`. Note: camphor では使用不可 (partition 経由で暗黙決定) |
| `nodes` | integer | No | Number of nodes |
| `ntasks` | integer | No | Number of MPI tasks |
| `walltime` | string | Yes | 正の wall time (`H+:MM:SS` または `D-H+:MM:SS`; minute / second は `00..59`) |

#### RSC mode (`resource_style = "rsc"`, camphor 等)

`site.toml` で `resource_style = "rsc"` の場合、`runo case new` は以下のフィールドを生成する:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `partition` | string | No | Partition/queue name |
| `qos` | string | No | Slurm QOS name (camphor では使用不可) |
| `processes` | integer | No | MPI プロセス数 (`--rsc p=N`) |
| `threads` | integer | No | プロセスあたりスレッド数 (`--rsc t=T`) |
| `cores` | integer | No | プロセスあたりコア数 (`--rsc c=C`, ≥ threads) |
| `memory` | string | No | プロセスあたりメモリ (`--rsc m=MEM`, e.g. `"8G"`) |
| `gpus` | integer | No | GPU 数 (`--rsc g=N`) |
| `walltime` | string | Yes | 正の wall time (`H+:MM:SS` または `D-H+:MM:SS`; minute / second は `00..59`) |

> **RSC モードのフィールド名について (>= 0.1.10)**
>
> `case.toml` / `survey.toml` の `[job]` セクションでは上記の **`processes` / `threads` / `cores`** が user-facing
> な名前です。ジョブスクリプトのレンダリングは内部で `ntasks` / `threads_per_process` / `cores_per_thread` の
> 名前で受け取りますが、`runops.application.run_creation._build_job_config` が `site.toml` の `resource_style` を
> 見て翻訳するので、`case.toml` / `survey.toml` 側で内部名を書く必要はありません (書いても無視されます)。
> どちらの site タイプでも `[job]` の正しい書き方は次のとおりです:
>
> - 標準 Slurm site (`resource_style = "standard"`): `nodes`, `ntasks`, `walltime`
> - RSC site (`resource_style = "rsc"`): `processes`, `threads`, `cores`, `walltime`
>
> `120:00:00` と `5-00:00:00` はどちらも有効です。負値、`00:00:00`、minute / second が
> `60` 以上の値は core-hour を 0 または過小評価し得るため、planning、materialization、
> clone / extend / retry、job.sh 生成のすべてで拒否されます。
>
> 0.1.9 以前は `processes` を書いてもレンダラに伝わらず、`--rsc p=1:t=1:c=1` が出る不具合がありました
> ([Fix RSC mode field-name plumbing](https://github.com/Nkzono99/runops/commit/0f7aac3))。

#### 共通フィールド

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `modules` | string[] | No | 追加モジュール (site modules にマージされる) |
| `pre_commands` | string[] | No | 実行前シェルコマンド |
| `post_commands` | string[] | No | 実行後シェルコマンド |

### `[params]`

Parameter overrides using dot-notation keys. These modify the simulator's input file.

```toml
[params]
"tmgrid.nx" = 4000       # config["tmgrid"]["nx"] = 4000
"species.0.wp" = 1.0     # config["species"][0]["wp"] = 1.0
```

- Keys are dot-separated paths into the simulator's TOML input
- Numeric segments are treated as array indices
- Values can be integers, floats, strings, booleans, or arrays

---

## survey.toml

Parameter survey definition. Cartesian product / linked groups は候補を表し、file を読んだだけでは
Run を生成しない。`runo runs sweep` の既定 plan は read-only で、明示選択した点だけを
materialize する。

```toml
[survey]
id = "S20260328-mag-angle"
name = "Magnetic field angle scan"
base_case = "flat_surface"
simulator = "emses"
launcher = "srun"
experiment_id = "E20260901-0001"
phase = "pilot"

[intent]
purpose = "explore"
information_gap = "Which angle range contains the transition?"
baseline_run = "R20260831-0001"
created_by = "human"
goal_id = ""

[budget]
max_materialized_runs = 3
max_core_hours = 36.0

[retention]
class = "exploratory"
review_after = "2026-09-15"
expire_after = ""

[classification]
model = "sheath"
submodel = "with_mag"
tags = ["magnetic", "angle_scan"]

[axes]
"plasma.wc" = [0.0, 0.147, 0.294]
"plasma.phiz" = [0.0, 45.0, 90.0]

[naming]
# Empty means: derive labels from changes relative to the base case.
display_name = ""
directory = "{run_id}--{label}"
max_length = 48

[naming.aliases]
"plasma.phiz" = "angle"

[job]
partition = "gr20001a"
nodes = 1
ntasks = 800
walltime = "120:00:00"
```

### `[survey]`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | Formal apply: Yes | Project 内で一意な Survey identifier。省略時の自動値は preview 用だけで、materialization gate は明示値を要求 |
| `name` | string | No | Human-readable name |
| `base_case` | string | Yes | Case name to use as template |
| `simulator` | string | Yes | Simulator name |
| `launcher` | string | No | Launcher profile name |
| `experiment_id` | string | Policy dependent | Owning `EYYYYMMDD-NNNN`; 新規 scaffold では必須 |
| `phase` | enum | Formal apply: Yes | `pilot`, `main`, `followup`。main/followup は Experiment `decision=expand` が必要 |

### `[intent]`, `[budget]`, `[retention]`

| Field | Type | Description |
|-------|------|-------------|
| `intent.purpose` | enum | `explore`, `confirm`, `validate`, `reproduce`; owning Experiment intent と一致必須 |
| `intent.information_gap` | string | この Survey が解消する不確実性 |
| `intent.baseline_run` | string | 任意の `RYYYYMMDD-NNNN` baseline |
| `intent.created_by` | string | materialized Run に freeze する actor |
| `intent.goal_id` | string | 任意の Agent goal / workflow identity |
| `budget.max_materialized_runs` | integer >= 1 | Survey-local directory hard cap。省略時は project default |
| `budget.max_core_hours` | number > 0 | Survey-local core-hour hard cap |
| `retention.class` | string | storage / review classification hint |
| `retention.review_after` | string | review hint。自動 archive/delete authority ではない |
| `retention.expire_after` | string | expiry hint。自動 purge/delete authority ではない |

### `[axes]`

Parameter axes for Cartesian product expansion. Each key is a dot-notation parameter, value is an array of values to sweep.

```toml
[axes]
"plasma.wc" = [0.0, 0.147, 0.294]    # 3 values
"plasma.phiz" = [0.0, 45.0, 90.0]     # 3 values
# Total runs: 3 x 3 = 9
```

### `[[linked]]`

Co-varying parameter groups. Parameters within each `[[linked]]` group are **zipped** (must have equal-length arrays). Multiple `[[linked]]` groups are combined via Cartesian product with each other and with `[axes]`.

```toml
[axes]
seed = [1, 2, 3]

# nx and ny co-vary (zip): (32,32), (64,64), (128,128)
[[linked]]
nx = [32, 64, 128]
ny = [32, 64, 128]
# Total runs: 3 seeds × 3 linked pairs = 9
```

| Constraint | Description |
|-----------|-------------|
| Equal length | All arrays in one `[[linked]]` group must have the same length |
| No overlap | Parameter names must not appear in both `[axes]` and `[[linked]]` |
| Multiple groups | Each `[[linked]]` group is independent; groups are Cartesian-multiplied |

**Multiple groups example:**

```toml
[[linked]]
nx = [32, 64]
ny = [32, 64]

[[linked]]
dt = [0.1, 0.01]
steps = [100, 1000]
# Total runs: 2 grid pairs × 2 time pairs = 4
```

### `[naming]`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `display_name` | string | No | 明示的な表示名 template。空なら base case との差分から semantic label を自動生成 |
| `directory` | string | No | directory basename template。既定 `{run_id}--{label}`。`{run_id}` は必須 |
| `max_length` | integer | No | directory に使う label の最大文字数。既定 `48` |
| `aliases` | table | No | parameter key から短い人間向け名称への対応 |
| `groups` | array of tables | No | 一つ以上の parameter を倍率ベースの意味へ畳み込む規則 |

`[[naming.groups]]` の現在の `strategy` は `uniform_ratio`。group の全 key が
base case から同じ倍率で変化した場合だけ、`size-x3` のようにまとめる。
倍率が揃わない場合は `nx-x3-ny-x2` のような個別差分へフォールバックする。
group 外の数値は倍率と仮定せず、`angle-30` のように値そのものを表示する。
明示的な `display_name` template がある場合は、semantic label より優先される。

```toml
[[naming.groups]]
label = "size"
keys = ["tmgrid.nx", "tmgrid.ny", "tmgrid.nz"]
strategy = "uniform_ratio"
```

生成例:

```text
R20260717-0001--baseline/
R20260717-0002--size-x3/
R20260717-0003--size-x3-dt-x0-5/
```

LLM/agent は survey 設計時に aliases と groups を提案できるが、`runs sweep` は
model API を呼ばず、保存済み規則をローカルで決定的に適用する。

### Plan / apply contract

```bash
# lazy read-only preview。directory 0、Run ID 消費 0
runo runs sweep runs/mag-angle --offset 0 --limit 50

# preview の ref と hash を明示して selected point だけ materialize
runo runs sweep runs/mag-angle \
  --apply --point p0001 --point p0003 --expect-plan sha256:...
```

`--apply` は `--point`（repeatable）または `--all` の exactly one と、現在の plan hash に
一致する `--expect-plan` を要求する。同じ `survey.id + point_id` は existing Run を reuse し、
同じ条件の再 apply で directory を増やさない。plan hash は survey、base case、case tree、
simulator / launcher / site config の内容に依存する。

### `[job]`

Same as `case.toml [job]`. Shared across all generated runs.

### Survey-level overrides

`[classification]` and `[job]` in `survey.toml` are partial overlays on the
`base_case`. Only fields written in `survey.toml` are considered; omitted fields
are inherited from `case.toml`.

Scalar fields replace the case value when the survey value is non-empty.
List fields replace the case list when present, including an explicit empty
list. Supported list fields are `classification.tags`, `job.modules`,
`job.pre_commands`, and `job.post_commands`.

For example, this keeps the base case model, partition, nodes, and task count,
while changing only tags, walltime, and modules:

```toml
[classification]
tags = ["scan"]

[job]
walltime = "02:30:00"
modules = ["custom/module"]
```

---

## manifest.toml

Run manifest. The source of truth for a run's state, provenance, and history. Located at `<run_dir>/manifest.toml`. **Managed by runops** — do not edit manually.

```toml
[run]
id = "R20260329-0001"
display_name = "wc0147_phi45"
status = "completed"
created_at = "2026-03-29T10:30:00+09:00"

[path]
run_dir = "runs/sheath/wc_scan/R20260329-0001"

[origin]
case = "flat_surface"
survey = "S20260329-sheath-wc"
parent_run = ""

[classification]
model = "sheath"
submodel = "with_mag"
tags = ["magnetic"]

[simulator]
name = "emses"
adapter = "emses"
resolver_mode = "package"

[launcher]
name = "slurm_srun"

[simulator_source]
resolver_mode = "package"
executable = "mpiemses3D"
exe_hash = "sha256:..."
git_commit = "abc1234"
git_dirty = false
git_state_observed = false
source_repo = ""
build_command = ""
package_version = "1.2.3"

[job]
scheduler = "slurm"
job_id = "12345"
partition = "gr20001b"
nodes = 1
ntasks = 32
walltime = "12:00:00"
submitted_at = "2026-03-29T10:31:00+09:00"

[variation]
changed_keys = ["plasma.wc", "plasma.phiz"]

[params_snapshot]
"tmgrid.nx" = 4000
"tmgrid.nz" = 800
"plasma.wc" = 0.147
"plasma.phiz" = 45.0

[intent]
experiment_id = "E20260901-0001"
survey_id = "S20260329-sheath-wc"
phase = "pilot"
purpose = "explore"
created_by = "human"

[identity]
point_id = "sha256:..."
condition_hash = "sha256:..."
input_hash = "sha256:..."
execution_hash = "sha256:..."
provenance_hash = "sha256:..."
plan_hash = "sha256:..."

[curation]
review_status = "unreviewed"
reviewed_at = ""
reviewed_by = ""
reason = ""

[storage]
tier = "hot"
form = "full"
retention_class = "exploratory"
review_after = ""
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

### `[run]`

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique run ID (`R<YYYYMMDD>-<NNNN>`) |
| `status` | string | Current state (see state machine below) |
| `created_at` | datetime | ISO 8601 creation timestamp |

### `[origin]`

| Field | Type | Description |
|-------|------|-------------|
| `case` | string | Source case name |
| `survey` | string | Source survey ID; empty for a non-survey run |
| `parent_run` | string | Parent run ID for cloned/extended runs |

### `[simulator]` / `[launcher]`

| Field | Type | Description |
|-------|------|-------------|
| `simulator.name` | string | Simulator name |
| `simulator.adapter` | string | Adapter registry name |
| `simulator.resolver_mode` | string | Configured runtime resolver mode |
| `launcher.name` | string | Launcher profile name |

### `[path]`

| Field | Type | Description |
|-------|------|-------------|
| `run_dir` | string | Current physical run directory. Updated when archive or restore relocates a run. |
| `created_at_path` | string | Original run directory before archive relocation, when known. |
| `archived_from` | string | Source directory used for the latest archive relocation. |
| `archived_at` | datetime string | ISO 8601 timestamp for the latest archive relocation. |
| `restored_from` | string | Archived directory used for the latest restore. |
| `restored_at` | datetime string | ISO 8601 timestamp for the latest restore. |
| `bundle_archived_from` | string | Run path before its parent directory was bundle-archived. Does not change `run.status`. |
| `bundle_archived_at` | datetime string | ISO 8601 timestamp for the latest parent bundle archive. |
| `bundle_restored_from` | string | Run path inside the archived parent used for the latest bundle restore. |
| `bundle_restored_at` | datetime string | ISO 8601 timestamp for the latest parent bundle restore. |

### `.runops-archive.toml`

`runo runs archive PARENT --bundle` が archived parent の直下へ生成する restore marker。
Git 管理可能な小さな provenance file であり、配下 run の lifecycle state は表さない。

| Field | Type | Description |
|-------|------|-------------|
| `bundle.format_version` | integer | Bundle archive metadata format. Currently `1`. |
| `bundle.archived_from` | absolute path string | Parent directory restored by `runo runs restore --bundle`. |
| `bundle.archived_at` | datetime string | ISO 8601 archive timestamp. |
| `bundle.run_count` | integer | Number of run manifests moved with the parent. |
| `bundle.adopted_run_ids` | array of strings | Individually archived/purged run IDs adopted with `--adopt-archived`; empty for a normal bundle archive. |

`runs/_archive/` 自体は `.gitignore` 対象にしない。ただし `runs/**/work/`、
`runs/**/status/`、analysis cache / scratch、生成済み input の除外規則は archive 配下にも
適用される。

### `.runops-bundle-{archive,restore}-*.receipt.toml`

通常の `--bundle` archive / restore が source parent へ move 前に作る durable transaction
receipt。現行 `transaction.format_version = 1` は action、canonical source/destination、時刻、
root directory device/inode、Run subtree を除く scaffold identity、marker の exact pre/postimage を
固定する。各 `[[runs]]` は Run ID/state/相対 path、manifest exact pre/postimage（base64 と
SHA-256）、Run directory device/inode、manifest を除く tree identity を持つ。

再開時は source/destination の一方だけに同じ root directory が存在し、scaffold、各 Run tree、
manifest、marker が receipt の許可する phase と完全一致する必要がある。不一致時は receipt と
live data を変更せず、自動 rollback もしない。全 child と marker の commit postimage を再検証した
後だけ receipt を削除する。

### `.tmp-adopt-*/receipt.toml`

`--bundle --adopt-archived` が最初の move より前に archive destination の親へ作る durable
transaction receipt。現行 format は `adoption.format_version = 2` で、source / destination、
件数、時刻に加え source directory device/inode と scaffold identity digest を持つ。各
`[[runs]]` item は Run ID、相対 path、元 path、state、adopted flag、manifest の preimage /
expected postimage SHA-256、Run directory device/inode、manifest を除く tree identity digest を
固定する。tree identity は path と filesystem metadata を対象とし、大容量 artifact 本文を
再 hash しない。

再開は manifest が固定した preimage または runops が生成する postimage と一致し、directory
と tree/scaffold identity も一致する場合だけ許可する。不一致時は receipt、staging、live tree を
変更しない。v1 以前の pending receipt は inode/tree binding を証明できないため自動変換・自動
cleanup せず、`runo triage` と手動確認の対象にする。

### State Machine

```
created -> submitted -> running -> completed
created/submitted/running -> failed
submitted/running -> cancelled
completed -> archived -> purged
             |
             +-> completed  (restore)
```

### Execution state と analysis readiness

`run.status = "completed"` は scheduler / lifecycle 上の完了を表す。解析に必要な
成果物が揃っているかは別レイヤとして扱い、`runo runs status` と
`runo context --json` が adapter の `detect_status()` と
`required_outputs()` から analysis readiness を計算する。

`runo runs sync` が current attempt を初めて `completed` にしたときは、Adapter の
bounded `probe_readiness()` を同じ action 内で 1 回実行し、派生 cache を
`status/readiness.json` に保存する。cache は `job_id`, `submitted_at`, `attempt` と
結び付けられ、attempt が変わると無効になる。manifest の canonical lifecycle state
ではなく、後続の status / context / MCP が同じ output inspection を繰り返さないための
再計算可能な observation である。bounded result が `unknown` の場合だけ後続 consumer
が deep evaluation を 1 回行って cache を置き換え、deep result は `unknown` でも再利用する。
ただし `runs list`、`runs dashboard --all`、MCP `runops.run.list` は bulk latency を
bounded に保つ cache-only consumer であり、cache miss は `readiness_not_cached` として
返すだけで deep evaluation を起動しない。

readiness result は `reason_codes`, `partial_outputs`, `recommended_action`,
`recommended_command`, `requires_human`, `evaluation_mode` を含む。通常の terminal
診断は sync result だけで次 action まで決められる。

- EMSES は `hdf5_fields` (field HDF5) を required output として扱う
- BEACH は `summary` (`summary.txt`) を required output として扱う
- required output が欠ける completed run は `analysis_status = "incomplete"`
  として表示されるが、manifest の `run.status` は書き換えない

### Retry / partial output metadata

`runo runs retry --plan` は `failed` / `cancelled` run の状態を `created` に戻さず、
retry intent と partial output の検出結果だけを manifest に記録する。

| Field | Type | Description |
|-------|------|-------------|
| `run.retry_status` | string | `partial`, `retry_planned`, `retry_ready`, `manual_review`, `not_retryable` |
| `run.partial_outputs` | table | adapter の `detect_outputs()` から検出した partial output category と件数 |
| `run.retry_note` | string | `--note` で記録した任意メモ |
| `run.readiness_disposition` | string | known non-ready output を破棄した場合の `discarded_incomplete` |
| `run.readiness_review_reason` | string | `purge-work --discard-incomplete --reason` で記録した判断理由 |
| `run.readiness_reviewed_at` | datetime string | readiness disposition を記録した UTC timestamp |
| `job.retry_adjustments` | table | 次 attempt に適用予定の調整値 |
| `job.next_attempt` | int | plan 時点で予定される次 attempt 番号 |

通常の `runo runs retry` は failed/cancelled run を `created` に戻し、
`run.retry_status = "retry_ready"` を記録する。partial output は消さずに
`run.partial_outputs` に件数を残す。

### `[params_snapshot]`

Frozen parameter snapshot at run creation time.

### `[job]`

| Field | Type | Description |
|-------|------|-------------|
| `scheduler` | string | Scheduler name (`slurm`) |
| `job_id` | string | Slurm job ID |
| `submitted_at` | datetime | Submission timestamp |

### `[simulator_source]`

| Field | Type | Description |
|-------|------|-------------|
| `resolver_mode` | string | How the executable was resolved |
| `executable` | string | Executable path or name |
| `exe_hash` | string | SHA256 hash of executable |
| `git_commit` | string | Git commit hash |
| `git_dirty` | boolean | Whether working tree had uncommitted changes |
| `git_state_observed` | boolean | Whether both commit and clean/dirty Git queries succeeded |
| `source_repo` | string | Source repository path |
| `build_command` | string | Command used to build the simulator |
| `package_version` | string | Installed simulator package version |

### `[intent]`

Experiment / Survey の研究意図を Run 作成時に freeze する。`experiment_id`, `survey_id`,
`phase`, `purpose`, `created_by`, `goal_id`, `information_gap`, `baseline_run` を持てる。
standalone Run でも新規 project policy が有効なら active Experiment が必要で、purpose は
Experiment intent と一致する。

### `[identity]`

| Field | Meaning |
|-------|---------|
| `point_id` | Survey point の full effective params hash |
| `condition_hash` | `params_snapshot` の canonical hash |
| `input_hash` | frozen `input/` tree の content hash |
| `execution_hash` | launcher / job / simulator configuration hash |
| `provenance_hash` | simulator source provenance hash |
| `plan_hash` | materialization を承認した Survey plan hash |

### `[curation]`

`review_status = "unreviewed"|"reviewed"`, `reviewed_at`, `reviewed_by`, `reason` を持つ。
`reviewed` として扱うには `reviewed_by` と `reason` が non-empty で、`reviewed_at` が
timezone-aware ISO-8601 timestamp でなければならない。欠落・不正値は未 review として
Experiment/project backlog に数え、Result evidence の quality gate も通さない。
`runo runs review RUN --reason ...` は terminal Run の確認を記録するだけで、Result evidence
への採否を決めない。

### `[storage]`

| Field | Values / meaning |
|-------|------------------|
| `tier` | `hot` / `cold`; 物理的な active storage class |
| `form` | `full` / `compacted` / `metadata_only`; artifact representation |
| `retention_class` | Survey から freeze した分類 hint |
| `review_after`, `expire_after` | review hint。自動削除 authority ではない |
| `pinned`, `pin_reason` | retention 対象から守る明示情報 |
| `protected_by_results` | purge 対象 path evidence を include する sealed Result ID。purge 時に reverse scan して更新 |

生成時は `hot/full`、individual archive は `cold`、restore は `hot`、purge-work は
`cold/compacted` へ更新する。lifecycle、curation、storage、Result evidence selection は
直交するため、`archived == cold` や `reviewed == selected` と解釈しない。

### Required contract and extensions

The required top-level tables are `[run]`, `[origin]`, `[simulator]`,
`[launcher]`, `[simulator_source]`, `[job]`, and `[params_snapshot]`.
Within them, `run.id`, `run.status`, `origin.case`, `simulator.name`,
`launcher.name`, `job.scheduler`, `job.job_id`, and `job.submitted_at` are
required. A parameter-less run still records an empty `[params_snapshot]`.

Newly generated canonical manifests additionally include `[path]`,
`[classification]`, `[variation]`, `[files]`, `[intent]`, `[identity]`,
`[curation]`, and `[storage]`. They remain optional on legacy v0 reads.

runops preserves parsed values in unknown top-level tables and unknown fields in
canonical tables across read/write and update cycles. Third-party metadata should
use `[extensions.<namespace>]`, for example `[extensions.example_plugin]`, to avoid
name collisions. Canonical tables take precedence if extension data attempts to
shadow one of their names. TOML comments and table ordering are not preserved.

---

## Run Directory Structure

```
R20260329-0001/
  manifest.toml        # Run state and metadata (source of truth)
  input/               # Simulator input files (frozen at creation)
    plasma.toml
  submit/
    job.sh             # Generated Slurm batch script
  work/                # Execution directory (cd here before srun)
    stdout.12345.log   # Job stdout
    stderr.12345.log   # Job stderr
    outputs/           # Simulator output files
    restart/           # Restart/checkpoint files
  analysis/            # Post-processing results
    summary.json       # Key metrics (generated by runo analyze summarize)
    figures/            # Plots and visualizations
```

---

## test-receipt.toml

smoke / debug は `.runops/test-runs/TYYYYMMDD-NNNN/` に置き、通常 Run の
`manifest.toml` と区別する。

```toml
schema_version = 1

[test]
id = "T20260901-0001"
kind = "smoke" # smoke | debug
state = "prepared" # prepared | submitted | passed | failed | skipped
case = "flat_surface"
profile = "smoke"
source_commit = "abc123"
executable_hash = "sha256:..."
input_hash = "sha256:..."
adapter = "emses"
adapter_version = "1.2.3"
cache_key = "sha256:..."
created_at = "2026-09-01T00:00:00+00:00"
updated_at = "2026-09-01T00:00:00+00:00"
started_at = ""
finished_at = ""
observation = ""
cached_from = ""
```

`source_commit`, `executable_hash`, `adapter_version` がすべて non-empty のときだけ cache
reuse が可能。TTL 内に同じ key の `passed` receipt があれば既存 attempt を返し、新しい
T ID / directory / receipt は作らない。TestAttempt は `runo runs list` に現れず、T ID や
`.runops/test-runs/**` は canonical Result evidence として拒否される。

---

## analysis/summary.json

`runo analyze summarize` が生成する run の要約ファイル。Adapter が基本メトリクスを出力し、プロジェクトスクリプトで拡張できる。
解析・可視化レイヤ全体の運用ルールは [Analysis Layer](layers/analysis.md) を正本とする。
`runo analyze collect` は既存の `analysis/summary.json` を集める。completed run に summary が無い場合は missing summary として記録し、自動では `summarize` しない。
`runo analyze summarize` は同時に `analysis/artifacts.toml` も生成する。

### 基本構造

```jsonc
{
  // Adapter が出す基本情報
  "status": "completed",
  "nstep": 400000,

  // プロジェクトスクリプトが追加するメトリクス
  "ion_flux_max": 1.23,

  // プロット参照 (analysis/ からの相対パス)
  "figures": [
    {
      "path": "figures/potential_profile.png",
      "caption": "Potential profile along z-axis"
    }
  ]
}
```

スキーマは固定しない。Adapter とプロジェクトスクリプトが任意のキーを追加できる。`figures` キーのみ以下の規約に従う:

| Field | Type | Description |
|-------|------|-------------|
| `figures[].path` | string | `analysis/` からの相対パス |
| `figures[].caption` | string | 図の説明 |

### プロジェクトスクリプトによる拡張

`runo analyze summarize` は Adapter の `summarize()` 実行後、以下の順でプロジェクトスクリプトを探索し、見つかれば実行する:

1. `cases/<case>/summarize.py` — legacy レイアウトのケース解析
2. `cases/<simulator>/<case>/summarize.py` — 現行の multi-simulator layout のケース解析
3. `scripts/summarize.py` — プロジェクト共通の解析

新規 project では `cases/<simulator>/<case>/summarize.py` を推奨する。

スクリプトは `summarize(run_dir, base_summary)` 関数を定義する:

```python
# cases/emses/flat_surface/summarize.py
from pathlib import Path

def summarize(run_dir: Path, base_summary: dict) -> dict:
    """Adapter の summary を受け取り、拡張して返す。"""
    # work/ の出力を読んで独自メトリクスを追加
    base_summary["ion_flux_max"] = compute_ion_flux(run_dir)

    # プロット生成 → analysis/figures/ に保存
    fig_dir = run_dir / "analysis" / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    plot_path = fig_dir / "potential_profile.png"
    make_plot(run_dir, plot_path)

    base_summary.setdefault("figures", [])
    base_summary["figures"].append({
        "path": "figures/potential_profile.png",
        "caption": "Potential profile along z-axis",
    })
    return base_summary
```

スクリプトが例外を投げた場合は Warning を出力し、Adapter の summary のみで続行する。

## analysis/artifacts.toml

run-local な解析成果物の索引。`path` は `analysis/` からの相対 path。
`summary.json` は metric の正本、`artifacts.toml` は figure / table / report / script
などの成果物の正本として扱う。

```toml
schema_version = 1
scope = "run"
generated_by = "runo analyze summarize"

[[artifacts]]
kind = "figure"
path = "figures/density_xz_final.png"
title = "Final density XZ slice"
description = "Final-frame log10 density on the y-center XZ plane."
status = "draft"
script = "cases/emses/vertical_hole/summarize.py"
data = ["work/*.h5"]
run_id = "R20260424-0007"
quantity = "density"
plane = "xz"
frame = "final"
```

最初は厳密 schema にしない。最低限、`kind`, `path`, `title`, `description`,
`status`, `script`, `data` を揃える。未知 field は許容する。

### Metrics schema の安定性 (cross-series 比較のために)

`analyze collect` は survey 配下の run の `summary.json` を平坦化して CSV / JSON に集計する。
`cases` や `variation` を跨いで比較可能にするため、**同じ geometry では同じ metric を常に出す** ことを推奨する:

- Boundary condition やパラメータ違いで metric が存在しない run があると、集計 CSV で `nan` 埋め列が発生し、
  cross-series の decomposition (例: floating plate と fixed-potential plate を並べて sheath 寄与を分離) が困難になる。
- 物理的に定義不可能な metric は `nan` や `null` ではなく、定義的に埋められる値 (例: fixed 0V plate では `phi_s_mean = 0`) を出力するか、
  常に同じ nan を書き込んで列存在を維持する。
- Depletion isoline fit のように BC 非依存で計算可能な metric は、すべての BC で生成する。

新しい metric を追加するときは、同じ geometry の他のケースでも同名キーを出力するよう summarize.py 側で統一する。

---

## survey summary outputs

`runo analyze collect <survey_dir>` は survey 配下の run を走査し、`<survey_dir>/summary/` に集計成果物を生成する。
`runo analyze plot <survey_dir> --x <column> --y <column>` はこの集計結果を使って図を生成する。
adapter が `default_plot_recipes()` を持つ場合は `--recipe <name>` でも既定の診断図を呼び出せる。
置き場所と運用ルールは [Analysis Layer](layers/analysis.md) を正本とする。

### 生成されるファイル

| File | Description |
|------|-------------|
| `summary/survey_summary.csv` | ネストをフラット化した run 一覧。list/dict は JSON 文字列として保持。`origin.*`, `classification.*`, `variation.*`, `param.*`, `analysis_status`, `missing_required_artifacts` なども含む |
| `summary/survey_summary.json` | run ごとの summary 原本、状態数、analysis readiness、数値統計、warning を含む集計 JSON |
| `summary/artifacts.toml` | survey summary 出力と run artifact の索引。`path` は `summary/` からの相対 path |
| `summary/survey_summary.md` | すぐ読める Markdown レポート |
| `summary/plots/*.png` | `runo analyze plot` が生成する survey 可視化 |

### 収集ルール

- `analysis/summary.json` がある run はそれを利用する
- completed run でも `analysis/summary.json` が無い場合は missing summary として記録する
- completed 以外の run は state count には含めるが、summary が無ければ集計対象外
- completed run は adapter の `required_outputs()` と `detect_status()` で
  `analysis_status = ready | incomplete | unknown` を診断する
- `analysis/summary.json` の `status` が `completed` 以外、または `partial = true`
  の場合は partial summary として `analysis_status = incomplete` にする
- `summary/artifacts.toml` は各 run の `analysis/artifacts.toml` を集約する。
  run 側 index が無い場合は `summary.figures[]` と `analysis/figures/` から fallback 生成する
- `summary/figures_index.json` は生成しない。旧互換出力は M0-0003 で削除する

### survey_summary.json の概要

```jsonc
{
  "generated_at": "2026-04-01T10:57:41+00:00",
  "survey_dir": "runs/beach_smoke",
  "total_runs": 2,
  "summaries_collected": 2,
  "generated_summaries": 0,
  "missing_summaries": 0,
  "state_counts": {
    "completed": 2
  },
  "readiness_counts": {
    "ready": 1,
    "incomplete": 1
  },
  "readiness_issues": [
    {
      "run_id": "R20260401-0002",
      "analysis_status": "incomplete",
      "missing_required_artifacts": ["hdf5_fields"],
      "warnings": ["Missing required artifact: hdf5_fields (EMSES HDF5 field output files)"]
    }
  ],
  "numeric_stats": {
    "potential_final_v": {
      "count": 2,
      "min": -1.35,
      "max": 1.15,
      "mean": -0.1
    }
  },
  "warnings": [],
  "runs": [
    {
      "run_id": "R20260401-0001",
      "status": "completed",
      "analysis_status": "ready",
      "analysis_ready": true,
      "missing_required_artifacts": [],
      "summary": {
        "potential_final_v": 1.15
      }
    }
  ]
}
```

### plot command

`runo analyze plot` は `survey_summary.json` の各 run から `flat_metadata` と `flat_summary` を統合した表を読み、指定列で可視化する。

```bash
runo analyze plot runs/sheath/angle_scan --list-columns
runo analyze plot runs/sheath/angle_scan --list-recipes
runo analyze plot runs/sheath/angle_scan --recipe completion-vs-dt
runo analyze plot runs/sheath/angle_scan --x param.tmgrid_dt --y floating_potential_final
runo analyze plot runs/sheath/angle_scan --x origin.case --y energy_total_ratio --kind bar
runo analyze plot runs/sheath/angle_scan --x param.angle --y ion_flux --group param.seed
```

| Option | Description |
|--------|-------------|
| `--recipe` | adapter-aware plot recipe 名。`--x` / `--y` の既定値を recipe から解決 |
| `--x` | x 軸列名 |
| `--y` | y 軸列名 (数値列) |
| `--kind` | `auto`, `line`, `scatter`, `bar` |
| `--group` | シリーズ分割に使う列名 |
| `--output` | 保存先パス |
| `--list-columns` | 利用可能な列を表示して終了 |
| `--list-recipes` | 利用可能な adapter recipe を表示して終了 |

`--kind auto` では、x 列が数値なら line、非数値なら bar を選ぶ。

---

## Canonical Result manifest

`runo research new-result NAME` は `research/results/RNNNN-topic/` に README 1 枚、
`manifest.toml`、`artifacts/` を作る。draft を編集した後、明示 evidence と claim を指定して
seal する。

```toml
[result]
schema_version = 1
id = "R0001-angle-transition"
status = "sealed" # draft | sealed
title = "angle transition"
claim = "The transition occurs between 40 and 60 degrees."
outcome = "supported" # supported | refuted | inconclusive | invalid

[[evidence]]
kind = "run"
run_id = "R20260831-0001"
disposition = "include" # include | exclude
role = "baseline"
reason = ""
source_path = "runs/scan/R20260831-0001/manifest.toml"
receipt_kind = "run-scientific-snapshot-v1"
sha256 = "...64 lowercase hex..."
bytes = 1234

[[evidence]]
kind = "path"
path = "runs/scan/R20260831-0001/analysis/summary.json"
disposition = "include"
role = "metric"
reason = ""
source_path = "runs/scan/R20260831-0001/analysis/summary.json"
owner_kind = "run"
owner_id = "R20260831-0001"
owner_relative_path = "analysis/summary.json"
receipt_kind = "file-bytes-v1"
sha256 = "...64 lowercase hex..."
bytes = 567

[seal]
sealed_at = "2026-09-01T00:00:00+00:00"
content_sha256 = "...64 lowercase hex..."
readme_sha256 = "...64 lowercase hex..."
readme_bytes = 2048
```

Result は少なくとも一つの `disposition = "include"` evidence を要求する。exclude edge は
non-empty `reason` が必須。Run evidence は project 内の canonical `RYYYYMMDD-NNNN` を
manifest から解決し、運用 state を除いた scientific snapshot を hash する。path evidence は
Run 配下または Result `artifacts/` 配下の regular file に限定し、owner-relative path と
file receipt を記録する。

```bash
runo research check-result R0001-angle-transition
runo research seal R0001-angle-transition \
  --claim "The transition occurs between 40 and 60 degrees." \
  --outcome supported \
  --selection-reason "Selected reviewed evidence for this claim." \
  --evidence-run R20260831-0001 \
  --evidence-path runs/scan/R20260831-0001/analysis/summary.json
```

T ID と `.runops/test-runs/**` は scientific evidence ではないため常に拒否する。seal 後は
README、evidence source、claim、outcome、selection の変化を `check-result` が検出する。
同一内容の reseal は no-op、異なる内容の reseal は拒否される。

included Run evidence と Run-owned path evidence には seal 前の source quality gate がある。
owner Run は `completed|archived|purged`、理由付き `reviewed` でなければならず、
`condition_hash`, `input_hash`, `execution_hash`, `provenance_hash`、source commit、
executable hash、simulator version、baseline Run、non-empty input snapshot が必要である。
dirty source の場合は diff 参照も必須となる。これは Run review と evidence selection を
同一化するものではなく、review は evidence 候補になるための前提にすぎない。
Run-owned path が `work/outputs`, `work/restart`, `work/tmp` 配下にある場合、sealed Result の
include edge が存在する間は `runo runs purge-work` が削除を拒否する。reverse scan は
`seal.content_sha256` と README/evidence receipt を同時に検証し、sealed content の改竄時は
参照なしとみなさず fail closed で拒否する。

## retained comparison result (legacy / analysis workspace)

複数 run / survey をまたぐ比較・可視化では、比較単位の成果物を
`research/results/RNNN-<comparison_id>/` にまとめる。
置き場所と運用ルールは [Analysis Layer](layers/analysis.md) を正本とする。

```bash
runo analyze new-comparison "landau model comparison" --source runs/series_a
runo analyze new-comparison "no_plate vs flat_plate" \
  --source runs/no_plate_scan \
  --source runs/flat_plate_scan
```

### 生成されるファイル

| File | Description |
|------|-------------|
| `research/results/RNNN-<id>/manifest.toml` | source run/survey/path と artifact index を記録 |
| `research/results/RNNN-<id>/README.md` | 結論、根拠、限界を集約する唯一の narrative |
| `research/results/RNNN-<id>/artifacts/scripts/` | 比較専用 script |
| `research/results/RNNN-<id>/artifacts/data/` | 比較用 CSV/JSON/中間表。Markdown は置かない |
| `research/results/RNNN-<id>/artifacts/figures/` | 比較図・contact sheet |

### manifest.toml の概要

```toml
[comparison]
schema_version = 1
id = "landau-model-comparison"
name = "landau model comparison"
created_at = "2026-05-08T12:00:00+00:00"
status = "draft"
description = ""

[[sources]]
kind = "survey"
path = "runs/series_a"
run_ids = ["R20260501-0001", "R20260501-0002"]

[paths]
scripts = "scripts"
data = "data"
figures = "figures"

[artifacts]
scripts = []
data = []
figures = []
```

`runo analyze collect` / `plot` が作る survey-local な `summary/` とは別に、
cross-run comparison workspace は複数 survey や手書き script を束ねるための
project-level analysis layer として使う。

`[comparison]` layout は read-only inspection のため引き続き認識するが、canonical seal の
対象ではない。残す claim は `runo research new-result` で canonical Result を作り、必要な
artifact / Run を evidence として明示する。

---

## story acceptance audit workspace

研究 campaign の narrative / claim が、既存の解析 artifact でどこまで支えられているかを確認するには、
`analysis/stories/<story_id>/` を使う。

```bash
runo analyze new-story "surface adhesion scaling" --source runs/sheath_scan
runo analyze audit-story analysis/stories/surface-adhesion-scaling
```

### 生成されるファイル

| File | Description |
|------|-------------|
| `analysis/stories/<story_id>/story.toml` | user-editable な story spec。source と narrative step、必要 artifact selector、claim ceiling を記録 |
| `analysis/stories/<story_id>/audit.json` | 機械可読な audit 結果。step ごとの covered / partial / missing と matched artifacts を含む |
| `analysis/stories/<story_id>/audit.md` | 人間/Agent 向けの concise report。research agenda には長い evidence inventory ではなく、この report へのリンクを置く |

### story.toml の概要

```toml
schema_version = 1
id = "surface-adhesion-scaling"
title = "Surface adhesion scaling"
status = "draft"

[[sources]]
kind = "survey"
path = "runs/sheath_scan"

[[steps]]
id = "surface-potential"
title = "Surface-potential visualization"
required_artifacts = ["figure:surface_potential"]
acceptable_status = ["main", "accepted", "draft"]
claim_ceiling = "static field evidence; not dynamic adhesion proof"
notes = ""
```

`required_artifacts` は v0 では `kind:name` 形式の文字列 selector とする。
`name` は artifact の `name`, `id`, `title`, `quantity`, `path` stem, `tags`
と照合される。`acceptable_status` に含まれない status の artifact は weak evidence
として report され、missing と同様に overall status を `partial` に落とす。
この audit は物理的妥当性を自動判定せず、artifact provenance と story step の対応を明示する。

---

## publication export outputs

`runo analyze export <run-or-survey> --paper <paper-id>` は、paper repo に渡しやすい
project 側 snapshot を `exports/papers/<paper-id>/<export-name>/` に生成する。

### 生成されるファイル

| File | Description |
|------|-------------|
| `exports/papers/<paper-id>/<export-name>/manifest.json` | export の機械可読 manifest。paper/export/project/source/files の各 section を持ち、run provenance と file hash を含む |
| `exports/papers/<paper-id>/<export-name>/README.md` | 人がざっと確認するための要約 |
| `exports/papers/<paper-id>/<export-name>/files/**` | 実際の exported artifact 群。既定は copy、`--mode symlink` で symlink 化可 |

### export 対象

- run export: `manifest.toml`, `analysis/summary.json`, `analysis/artifacts.toml`, `analysis/figures/**`
- survey export: `summary/survey_summary.csv`, `survey_summary.json`, `artifacts.toml`, `survey_summary.md`, `summary/plots/**`, 参照された run figure 群
- `survey.toml` がある場合は survey export に同梱される

### `manifest.json` の要点

- `paper`: paper repo 側での識別子 (`id`, `slug`)
- `export`: export 自身の識別子、生成日時、mode、runops version
- `project`: 元 project の名前と git 状態
- `source`: `run` / `survey` のどちらを切り出したか、対象 run 一覧、集計状況
- `files[]`: 各 exported file の `role`, `source_path`, `export_path`, `size_bytes`, `sha256`, `media_type`, `run_id`, `caption`

`source.runs[]` では execution と paper-facing status を分けて記録する。

| Field | Description |
|-------|-------------|
| `execution_status` | runops lifecycle / scheduler 由来の状態 (`completed`, `failed`, `cancelled` など) |
| `analysis_status` | required artifact と summary を踏まえた解析 readiness (`ready`, `incomplete`, `unknown`) |
| `paper_status` | paper 側の扱い (`accepted`, `placeholder`, `retry_planned`, `excluded`, `superseded`) |
| `retry_status` | retry workflow の状態 (`retry_planned`, `retry_ready`, `partial` など) |

`runo analyze export --paper-status placeholder` のように指定すると、export 内の
source run に対する paper-facing status を上書きできる。指定しない場合、
analysis-ready な completed run は `accepted`、required artifact が欠ける completed
run は `placeholder`、retry planned run は `retry_planned` として推定する。
analysis-incomplete な run を明示的に `accepted` とする場合だけ、同じ command に
`--accept-incomplete-reason <WHY>` を指定する。理由は export の source run record の
`readiness_acceptance_reason` に保存される。

### 例

```bash
runo analyze export runs/sheath/angle_scan --paper draft-a
runo analyze export R20260412-0003 --paper draft-a --name fig2-baseline
runo analyze export R20260412-0003 --paper draft-a --paper-status placeholder
runo analyze export R20260412-0003 --paper draft-a --paper-status accepted \
  --accept-incomplete-reason "qualitative comparison only"
runo analyze export runs/sheath/angle_scan --paper draft-a --mode symlink
```

## JSON Schema

All TOML files support schema validation via `#:schema` comments:

```toml
#:schema https://raw.githubusercontent.com/Nkzono99/runops/main/schemas/case.json
[case]
...
```

Schema files: `schemas/runops.json`, `schemas/simulators.json`,
`schemas/launchers.json`, `schemas/site.json`, `schemas/case.json`,
`schemas/survey.json`, `schemas/experiment.json`, `schemas/manifest.json`,
`schemas/result.json`, `schemas/campaign.json`.
Codex plugin 推薦 metadata は共通 sub-schema
`schemas/codex-plugin-recommendation.json` を参照する。
`runo plugins --json` / MCP `runops.project.plugins` の JSON 出力 contract は
`schemas/codex-plugin-inventory.json` と
`schemas/codex-plugin-check-result.json` に定義する。JSON payload は `$schema`
field に対応する schema path を含む。

---

## campaign.toml

プロジェクトルートに配置する研究意図の記述ファイル。AI エージェントに「何を調べたいか」を伝える。

### [campaign]

| フィールド | 型 | 必須 | 説明 |
|-----------|-----|------|------|
| `name` | string | Yes | キャンペーン名 |
| `description` | string | No | 研究の動機・背景 |
| `hypothesis` | string | No | 検証する仮説 |
| `simulator` | string | No | 使用するシミュレータ名 |

### [variables]

パラメータ名 (dot 記法) をキーとし、変数定義を値とする。

| フィールド | 型 | 必須 | 説明 |
|-----------|-----|------|------|
| `role` | string | Yes | `independent` / `dependent` / `fixed` / `controlled` |
| `range` | [number, number] | No | 独立変数の [min, max] |
| `values` | array | No | 明示的な値のリスト |
| `unit` | string | No | 物理単位 |
| `reason` | string | No | この値に設定した理由 |

### [observables]

観測量名をキーとし、出力定義を値とする。

| フィールド | 型 | 必須 | 説明 |
|-----------|-----|------|------|
| `source` | string | No | 出力ファイルのパスまたは glob |
| `column` | int/string | No | 出力ファイル内のカラム |
| `description` | string | No | 観測量の説明 |
| `unit` | string | No | 物理単位 |

### 例

```toml
[campaign]
name = "magnetic-angle-dependence"
hypothesis = "磁力線入射角 45 度付近でイオンフラックスが最大になる"
simulator = "emses"

[variables]
"plasma.wc" = { role = "independent", range = [0.0, 0.5], unit = "omega_pe" }
"tmgrid.dt" = { role = "fixed", values = [1.0], reason = "CFL 条件" }

[observables]
ion_flux = { source = "work/influx", column = 1, description = "イオンフラックス" }
```

---

## .runops/environment.toml

`runo doctor` で自動生成される実行環境記述ファイル。

### [cluster]

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `name` | string | クラスタ名 |
| `scheduler` | string | ジョブスケジューラ (`slurm`) |
| `scratch_path` | string | スクラッチパステンプレート |

### [cluster.partitions.{name}]

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `max_nodes` | int | 最大ノード数 |
| `max_walltime` | string | 最大実行時間 |
| `gpu` | bool | GPU 利用可否 |
| `default` | bool | デフォルトパーティションか |

### [cluster.constraints]

任意のキー・値ペアでクラスタ制約を記述 (例: `max_jobs_per_user = 100`)。

### [modules]

名前付きモジュールセット。値はモジュール名のリスト。

---

## [knowledge.sources]

外部 knowledge source は `runops.toml` の `[[knowledge.sources]]` で定義する。

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `name` | string | source 名 |
| `type` | string | `git` または `path` |
| `kind` | string | `profiles` / `project` / `insights` |
| `url` | string | `type = "git"` のときの Git URL |
| `path` | string | `type = "path"` のときのファイルシステムパス |
| `ref` | string | Git checkout ref。省略時は `main` |
| `mount` | string | ローカル同期先。`profiles` source と git source で利用 |
| `profiles` | array[string] | 有効化する profile 名一覧 (`kind = "profiles"` のみ) |

```toml
[[knowledge.sources]]
name = "shared-kb"
type = "git"
kind = "profiles"
url = "git@github.com:lab/shared-kb.git"
mount = "refs/knowledge/shared-kb"
profiles = ["common", "emses"]

[[knowledge.sources]]
name = "previous-campaign"
type = "path"
kind = "project"
path = "../previous-campaign"
```
