# アーキテクチャ

このドキュメントでは、runops のシステムアーキテクチャと設計思想を説明します。

## 設計原則

1. **run ディレクトリが主単位**: すべての操作は run_id または run ディレクトリを基点とする
2. **不変と可変の分離**: run_id は不変、パスは可変（分類・整理用）
3. **Simulator Adapter パターン**: シミュレータ固有処理は Adapter に閉じ込める。core はシミュレータに依存しない
4. **Launcher Profile パターン**: MPI 起動方式は Launcher に閉じ込める
5. **MPI に介入しない**: Python ツールは MPI rank ごとのラッパにならない。job.sh で srun/mpirun を直接実行
6. **manifest.toml が正本**: run の状態・由来・provenance はすべて manifest.toml に記録

---

## モジュール構成

```
runops/
  cli/                 -----> CLI 層 (typer)
    |                         ユーザー入力のパース・出力フォーマット
    v
  core/                -----> ドメインロジック層
    |                         Project / Case / Survey / Run / Manifest / State
    |
    +----> adapters/   -----> Simulator Adapter 層
    |                         シミュレータ固有処理の抽象化
    |
    +----> launchers/  -----> Launcher Profile 層
    |                         MPI 起動方式の抽象化
    |
    +----> jobgen/     -----> Job Script 生成
    |                         Slurm batch script のテンプレート生成
    |
    +----> slurm/      -----> Slurm 連携層
                              sbatch / squeue / sacct のラッパー
```

### モジュール依存関係

```
cli/
 |
 +--> core/project    (プロジェクト読込)
 +--> core/case       (Case 読込)
 +--> core/survey     (Survey 展開)
 +--> core/run        (Run 生成)
 +--> core/manifest   (Manifest 読書き)
 +--> core/state      (状態遷移)
 +--> core/discovery  (Run 探索)
 +--> core/provenance (Provenance 収集)
 +--> adapters/       (Adapter 取得・使用)
 +--> launchers/      (Launcher 取得・使用)
 +--> jobgen/         (job.sh 生成)
 +--> slurm/          (Slurm 連携)

core/
 +--> core/exceptions (共通例外)

adapters/
 +--> adapters/base   (抽象基底)
 +--> adapters/registry (登録・lookup)

launchers/
 +--> launchers/base  (抽象基底 + ファクトリ)
```

重要なルール: `core/` の大半は simulator 非依存を保ちますが、現在の実装では
`core/actions/` と `core/run_creation/` が orchestration 層として
`adapters/`、`launchers/`、`core/site/`、`jobgen/`、`slurm/` を接続しています。

特に run 生成時は `core/run_creation/` が project、case、survey override を読み、
simulator entry から Adapter を解決し、launcher profile と site profile を組み合わせて
`jobgen.generate_job_script()` に渡します。つまり Adapter は「何を実行するか」と
「入出力がどう見えるか」、Launcher は「program command を MPI でどう包むか」、
Site は「cluster が job script に何を要求するか」を担当します。

`src/runops/sites/` は runtime site 設定そのものではなく、`runo init` が一度だけ読む
bundled preset 集です。実行時に使われる site の本体は project root の `site.toml` で、
解決ロジックは `src/runops/core/site/` にあります。

---

## コアコンセプト

### Project

プロジェクト全体を表す最上位のエンティティです。

- **定義ファイル**: `runops.toml` (必須)、`simulators.toml` (任意)、`launchers.toml` (任意)
- **データクラス**: `ProjectConfig` (`core/project.py`)
- **主な責務**: プロジェクトルートの検出、設定ファイルの読込・検証

```python
@dataclass(frozen=True)
class ProjectConfig:
    name: str
    description: str
    root_dir: Path
    simulators: dict[str, dict[str, Any]]
    launchers: dict[str, dict[str, Any]]
    raw: dict[str, Any]
```

プロジェクトルートは `runops.toml` が存在するディレクトリです。`find_project_root()` が cwd から上位ディレクトリを辿って自動検出します。

### Case

run を生成するための再利用可能な雛形です。

- **定義ファイル**: `cases/<name>/case.toml`
- **データクラス**: `CaseData` (`core/case.py`)
- **主な責務**: シミュレーション条件（パラメータ・ジョブ設定・分類情報）の定義

```python
@dataclass(frozen=True)
class CaseData:
    name: str
    simulator: str
    launcher: str
    description: str
    classification: ClassificationData
    job: JobData
    params: dict[str, Any]
    case_dir: Path
    raw: dict[str, Any]
```

Case 自体は直接実行しません。create コマンドまたは survey の base_case として参照されます。

### Survey

パラメータサーベイの親単位です。

- **定義ファイル**: `runs/.../survey.toml`
- **データクラス**: `SurveyData` (`core/survey/`)
- **主な責務**: パラメータ軸の定義、直積展開、連動展開、display_name のテンプレート生成

```python
@dataclass(frozen=True)
class SurveyData:
    id: str
    name: str
    base_case: str
    simulator: str
    launcher: str
    classification: ClassificationData
    axes: dict[str, list[Any]]       # 直積展開
    linked: list[dict[str, list[Any]]]  # 連動 (zip) 展開
    naming_template: str
    job: JobData
    survey_dir: Path
    raw: dict[str, Any]
```

`expand_survey()` 関数が `[axes]`（直積）と `[[linked]]`（zip）を組み合わせて展開します:

```python
# axes のみ（従来の直積）
expand_survey({"u": [2e5, 4e5], "aspect": [2.0, 4.0]}, [])
# => [{"u": 2e5, "aspect": 2.0}, {"u": 2e5, "aspect": 4.0},
#     {"u": 4e5, "aspect": 2.0}, {"u": 4e5, "aspect": 4.0}]

# axes × linked（直積 × 連動）
expand_survey({"seed": [1, 2]}, [{"nx": [32, 64], "ny": [32, 64]}])
# => [{"seed": 1, "nx": 32, "ny": 32}, {"seed": 1, "nx": 64, "ny": 64},
#     {"seed": 2, "nx": 32, "ny": 32}, {"seed": 2, "nx": 64, "ny": 64}]
```

### Run

1 回のシミュレーション実行を表す最小単位です。

- **定義ファイル**: `runs/.../Rxxxx/manifest.toml`
- **データクラス**: `RunInfo` (`core/run/`)
- **ディレクトリ構造**: `input/`, `submit/`, `work/`, `analysis/`, `status/`

```python
@dataclass(frozen=True)
class RunInfo:
    run_id: str        # "R20260327-0001"
    run_dir: Path
    display_name: str
    created_at: str
    params: dict[str, Any]
```

run_id は `RYYYYMMDD-NNNN` 形式で、プロジェクト内で一意です。`next_run_id()` が既存の run_id を走査して次の連番を決定します。

### Manifest

run の正本情報を保持する台帳です。

- **ファイル**: `manifest.toml`
- **データクラス**: `ManifestData` (`core/manifest.py`)
- **主な責務**: run の識別・状態・由来・provenance・ジョブ情報の永続化

ManifestData は以下のセクションで構成されます:

| セクション | 内容 |
|-----------|------|
| `run` | id, display_name, status, created_at |
| `path` | run_dir |
| `origin` | case, survey, parent_run |
| `classification` | model, submodel, tags |
| `simulator` | name, adapter, resolver_mode |
| `launcher` | name |
| `simulator_source` | git_commit, exe_hash, source_repo 等 |
| `job` | scheduler, job_id, partition, nodes, ntasks, walltime |
| `variation` | changed_keys (survey で変化したパラメータ) |
| `params_snapshot` | 全パラメータのスナップショット |
| `files` | 標準ディレクトリ名 |

---

## Adapter パターン

### 目的

シミュレータごとに異なる以下の処理を Adapter に閉じ込めます:

- 入力ファイルの形式と生成方法
- 実行コマンドの構築
- 出力ファイルの検出
- 成功/失敗の判定
- summary の抽出
- provenance の収集

### クラス階層

```
SimulatorAdapter (ABC)     ← 抽象基底クラス
  |
  +-- GenericAdapter       ← 汎用実装（組み込み）
  +-- BundledAdapter       ← runops 同梱 contrib adapter
  +-- ExternalAdapter      ← Python entry point で配布
  +-- YourCustomAdapter    ← ユーザー定義
```

### 抽象インタフェース

`SimulatorAdapter` (`adapters/base.py`) は以下の 7 つの抽象メソッドを定義します:

```python
class SimulatorAdapter(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def render_inputs(self, case_data, run_dir) -> list[str]: ...

    @abstractmethod
    def resolve_runtime(self, simulator_config, resolver_mode) -> dict: ...

    @abstractmethod
    def build_program_command(self, runtime_info, run_dir) -> list[str]: ...

    @abstractmethod
    def detect_outputs(self, run_dir) -> dict: ...

    @abstractmethod
    def detect_status(self, run_dir) -> str: ...

    @abstractmethod
    def summarize(self, run_dir) -> dict: ...

    @abstractmethod
    def collect_provenance(self, runtime_info) -> dict: ...
```

`required_outputs()` は任意メソッドで、`detect_outputs()` の top-level key のうち
analysis-ready 判定に必須のカテゴリを宣言します。`runo runs status` と
`runo context` は、scheduler の `completed` と required artifact の充足を分けて表示します。

### GenericAdapter

`adapters/generic.py` に組み込みの汎用 Adapter が実装されています。多くのシンプルなシミュレータはこの Adapter で対応可能です:

- **入力**: `params` を `input/params.json` として書き出す。`case.input_files` があればコピーする
- **ランタイム解決**: `package` / `local_source` / `local_executable` の 3 モードに対応
- **実行コマンド**: `[executable, input/params.json]`
- **出力検出**: `work/` ディレクトリを走査
- **状態検出**: `work/exit_code` ファイルの値で判定 (0 = completed, 非 0 = failed)
- **provenance**: 実行ファイルの SHA-256 ハッシュ、git commit 情報

### Adapter Registry

`adapters/registry.py` の `AdapterRegistry` が Adapter の登録と検索を管理します。

```
register(adapter_cls)     # Adapter クラスを登録
get(name)                 # 名前で Adapter クラスを取得
load_from_config(config)  # simulators.toml から自動登録
```

自動登録の順序:

1. `runops.adapters` entry point group にある外部 Python package の Adapter
2. runops 同梱 `runops.adapters.contrib.<adapter_name>`
3. 互換用 `runops.adapters.<adapter_name>`

現在の `emses` / `beach` は runops 同梱 contrib adapter として登録される。将来外部
package へ切り出す場合は、同じ adapter 名を entry point として公開すれば
`simulators.toml` の表面は維持できる。

---

## Launcher パターン

### 目的

MPI 起動方式の違いを Launcher に閉じ込めます。Simulator Adapter が返す本体コマンドを Launcher が MPI ラッパーで包みます。

### クラス階層

```
Launcher (ABC)         ← 抽象基底クラス
  |
  +-- SrunLauncher     ← Slurm srun
  +-- MpirunLauncher   ← OpenMPI mpirun
  +-- MpiexecLauncher  ← mpiexec
```

### 処理の流れ

```
Adapter.build_program_command()
  => ["./solver", "input/params.json"]

Launcher.build_exec_line()
  => "srun ./solver input/params.json"
```

### ファクトリメソッド

`Launcher.from_config(name, config)` が `launchers.toml` の `kind` フィールドに基づいて適切な Launcher サブクラスをインスタンス化します:

| kind | クラス | コマンド例 |
|------|--------|-----------|
| `srun` | `SrunLauncher` | `srun ./solver input.toml` |
| `mpirun` | `MpirunLauncher` | `mpirun -np 32 ./solver input.toml` |
| `mpiexec` | `MpiexecLauncher` | `mpiexec -n 32 ./solver input.toml` |

`use_slurm_ntasks = true` の場合、タスク数の明示指定が省略され、Slurm の `SLURM_NTASKS` 環境変数が使用されます。

---

## 状態マシン

### 状態の定義

`core/state.py` の `RunState` 列挙型:

```python
class RunState(str, Enum):
    CREATED = "created"
    SUBMITTED = "submitted"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"
    PURGED = "purged"
```

### 遷移図

```
                  +----------+
                  | created  |
                  +----+-----+
                       |
                       v
                  +----------+
              +---| submitted|---+
              |   +----+-----+   |
              |        |         |
              v        v         v
         +--------+ +-------+ +----------+
         |cancelled| |running| |  failed  |
         +--------+ +---+---+ +----------+
                         |
              +----------+----------+
              |          |          |
              v          v          v
         +--------+ +----------+ +--------+
         |cancelled| |completed | | failed |
         +--------+ +----+-----+ +--------+
                         |
                         v
                    +----------+
                    | archived |
                    +----+-----+
                         |
                         v
                    +----------+
                    |  purged  |
                    +----------+
```

### 遷移の実装

`VALID_TRANSITIONS` ディクショナリが許可された遷移を定義し、`transition_state()` が遷移の正当性を検証します。不正な遷移は `InvalidStateTransitionError` を送出します。

`update_state()` は以下を実行します:
1. manifest.toml から現在の状態を読み取り
2. 遷移の正当性を検証
3. manifest.toml の `run.status` を更新
4. `status/state.json` にタイムスタンプ付きの状態変更を記録

---

## 主要操作のデータフロー

### create (単一 run 生成)

```
CLI: runo runs create CASE --dest DIR
  |
  +--> find_project_root() --> load_project()
  |      ProjectConfig を取得
  |
  +--> resolve_case() --> load_case()
  |      CaseData を取得
  |
  +--> get_adapter_instance()
  |      AdapterRegistry から SimulatorAdapter を取得
  |
  +--> get_launcher()
  |      Launcher.from_config() で Launcher を取得
  |
  +--> collect_existing_run_ids()
  |      runs/ を再帰探索して既存 run_id を収集
  |
  +--> create_run()
  |      run_id 採番 + ディレクトリ作成
  |
  +--> adapter.render_inputs()
  |      入力ファイル生成
  |
  +--> adapter.resolve_runtime()
  |      実行ファイル解決
  |
  +--> adapter.build_program_command()
  |      実行コマンド構築
  |
  +--> launcher.build_exec_line()
  |      MPI ラッパー付き実行行生成
  |
  +--> generate_job_script()
  |      submit/job.sh 生成
  |
  +--> adapter.collect_provenance()
  |      provenance 情報収集
  |
  +--> write_manifest()
         manifest.toml 書き出し (status = "created")
```

### sweep (パラメータサーベイ展開)

```
CLI: runo runs sweep DIR
  |
  +--> load_project() + load_survey() + load_case()
  |
  +--> expand_survey(axes, linked)
  |      axes 直積 × linked zip を展開 (N 個の組合せ)
  |
  +--> N 回ループ:
         +--> merge params (base_case + sweep 差分)
         +--> generate_display_name()
         +--> _generate_run()  (create と同一ロジック)
         |      run_id 採番 + ディレクトリ作成
         |      入力生成 + job.sh 生成 + manifest 書き出し
         +--> existing_ids に追加 (重複防止)
```

### submit (job 投入)

```
CLI: runo runs submit RUN
  |
  +--> resolve_run()
  |      run_id またはパスから run ディレクトリを特定
  |
  +--> read_manifest()
  |      現在の状態が "created" であることを確認
  |
  +--> sbatch_submit()
  |      sbatch --chdir=work/ submit/job.sh
  |      job_id をパース
  |
  +--> update_manifest()
  |      job.job_id を記録
  |
  +--> update_state(SUBMITTED)
         manifest.toml と status/state.json を更新
```

### status (状態確認)

```
CLI: runo runs status RUN
  |
  +--> resolve_run() --> read_manifest()
  |      manifest.toml の run.status を表示
  |
  +--> query_job_status(job_id)  (job_id がある場合のみ best-effort)
         live Slurm state を表示するが、manifest.toml と state.json は更新しない
```

### sync (Slurm 状態同期)

```
CLI: runo runs sync RUN
  |
  +--> resolve_run() --> read_manifest()
  |      job_id を取得
  |
  +--> query_job_status(job_id)
  |      1. squeue で照会 (アクティブ job)
  |      2. 見つからなければ sacct で照会 (完了 job)
  |      3. Slurm 状態を RunState にマッピング
  |
  +--> update_state(new_state)
         manifest.toml と status/state.json を更新
```

---

## Slurm 連携

### sbatch 投入 (`slurm/submit.py`)

- `sbatch_submit(job_script, working_dir)` が `sbatch --chdir=... job.sh` を実行
- 出力の `Submitted batch job 12345` をパースして job_id を返す
- テスト用に `CommandRunner` 型を注入可能（モック対応）

### 状態照会 (`slurm/query.py`)

- `squeue_status(job_id)`: アクティブ job の状態を照会
- `sacct_status(job_id)`: 完了 job の状態と exit code を照会
- `query_job_status(job_id)`: squeue -> sacct の順で照会し、RunState にマッピング
- `map_slurm_state()`: Slurm 固有の状態文字列 (PENDING, RUNNING, COMPLETED 等) を RunState に変換

Slurm 状態のマッピング:

| Slurm 状態 | runops RunState |
|-----------|-----------------|
| PENDING | submitted |
| RUNNING, COMPLETING, CONFIGURING, SUSPENDED | running |
| COMPLETED | completed |
| FAILED, NODE_FAIL, OUT_OF_MEMORY, TIMEOUT, PREEMPTED | failed |
| CANCELLED | cancelled |

---

## job.sh 生成 (`jobgen/generator.py`)

`generate_job_script()` は以下の構造の Slurm batch script を生成します:

```bash
#!/bin/bash
#SBATCH --job-name=R20260327-0001
#SBATCH --partition=gr20001a
#SBATCH --nodes=1
#SBATCH --ntasks=32
#SBATCH --time=12:00:00
#SBATCH --output=<run_dir>/work/%j.out
#SBATCH --error=<run_dir>/work/%j.err

set -euo pipefail

# module load ... (任意)
# export ENV_VAR=value (任意)

cd <run_dir>

exec srun ./solver input/params.json
```

---

## Run 探索 (`core/discovery.py`)

`discover_runs(runs_dir)` は `runs/` ディレクトリ以下を再帰的に走査し、`manifest.toml` を持つディレクトリを run として認識します。

これにより、`runs/` 以下の任意の深さの多重ネストに対応できます:

```
runs/
  cavity/
    rectangular/
      production/
        scan_u_aspect/
          R20260327-0001/    <-- manifest.toml があれば run として認識
```

`resolve_run(identifier, runs_dir)` は:
1. 絶対パス -> そのまま使用
2. 相対パス -> cwd からの解決を試行
3. run_id 文字列 -> 全 manifest.toml を走査して検索

---

## エラーハンドリング

`core/exceptions.py` に定義されたドメイン例外の階層:

```
SimctlError (基底)
  +-- ProjectNotFoundError
  +-- ProjectConfigError
  +-- CaseNotFoundError
  +-- CaseConfigError
  +-- SurveyConfigError
  +-- ManifestNotFoundError
  +-- ManifestError
  +-- InvalidStateTransitionError
  +-- DuplicateRunIdError
  +-- RunNotFoundError
  +-- ProvenanceError
```

CLI 層で `SimctlError` をキャッチし、ユーザーフレンドリーなメッセージを表示してから `typer.Exit(code=1)` で終了します。

---

## 知識層 (Knowledge Layer)

AI エージェントがシミュレーションを自律的に実行するための知識管理アーキテクチャ。
3 つのドメインで構成される:

### シミュレータ知識

```
simulator/environment plugin ← シミュレータ開発者・環境管理者が管理
    ↓ Codex plugin install / explicit knowledge source
.runops/knowledge/enabled/imports.md ← Agent context bundle (自動生成)
    ↓ 任意: runo init --with-refs / runo update-refs
refs/{repo}/docs/          ← ローカル mirror fallback
    ↓ AI が参照
adapter.parameter_schema() ← 構造化メタデータ
adapter.validate_params()  ← 物理的バリデーション
adapter.required_outputs() ← analysis-ready に必要な成果物
```

- simulator/environment plugin: 長文の Agent context、環境スキル、解析ライブラリ利用法
- `codex_plugins()`: simulator に推奨する外部 Codex plugin の導入導線と委譲役割 (`capabilities`)
- `runo plugins`: project / simulator / site から推薦 plugin を再表示・JSON 出力し、推薦メタデータを検査する監査入口
- `runo doctor`: 推薦メタデータの error も project 健全性として検出するが、plugin の install 状態は管理しない
- `refs/`: `runo init --with-refs` または手動 clone で使う任意のローカル mirror
- `doc_repos()` / `knowledge_sources()`: 任意 mirror を使う場合の clone 先とインデックス対象
- `parameter_schema()`: 型・単位・範囲・制約・導出公式
- `validate_params()`: CFL 条件、Debye 長解像度など
- `required_outputs()`: completed run を analysis-ready とみなす前に必要な出力カテゴリ

シミュレータ固有の Agent 向け長文コンテキストは、runops adapter ではなく各
シミュレータや解析ライブラリの Codex plugin に置く。runops adapter は実行管理に
必要なテンプレート、検証、入出力検出、provenance に責務を限定する。
adapter が返す package-bundled `agent_guide()` は、plugin や明示的 knowledge source が
ない場合の runops 側 fallback に限定し、完全な simulator manual にしない。

### 実行環境知識

```
sinfo / module list        ← HPC 環境
    ↓ runo doctor
.runops/environment.toml   ← 自動検出・保存
```

### 研究意図

```
campaign.toml              ← ユーザーが記述
  [campaign] name, hypothesis
  [variables] パラメータ定義 (role, range, unit)
  [observables] 測定量
```

### 実験知見 (curated)

```
.runops/insights/*.md      ← /learn で保存
.runops/facts.toml         ← runo knowledge add-fact
runops.toml:[knowledge.sources] ← 外部 knowledge source 定義
    ↓ runo knowledge source sync
insights のインポート       ← プロジェクト横断の知識共有
```

知見の種類: `constraint` (制約), `result` (結果サマリー),
`analysis` (物理的考察), `dependency` (パラメータ依存性)

### Lab notebook (chronological)

```
notes/YYYY-MM-DD.md        ← runo notes append (append-only)
notes/history/YYYY/YYYY-MM-DD.md
                             ← 古い日次 notebook (runo notes archive)
notes/reports/<topic>.md   ← refined long-form (改稿可)
    ↓ /learn で素材として読む
.runops/insights/, facts.toml ← curated 化
```

curated knowledge と lab notebook は **二層構造**:

- 整理済の永続知見 (上書き可・名前付き) は `.runops/insights/` / `facts.toml`
- 時系列の意思決定・観察ログ (準備フェーズの意思決定・観察・仮説・TODO) は `notes/YYYY-MM-DD.md`
- `runo notes append` は今日の日次ファイルに `## HH:MM <title>` 形式で追記
- `runo notes archive` は古い日次ファイルだけを `notes/history/YYYY/` に移し、`notes list/show` は active と history を透過検索する
- 価値が出てきたら notes → reports → insights / facts.toml の順に昇格

### Research layer (decision ledger)

```
research/agenda.md          ← 現在の高レベルな研究判断 (mutable)
research/proposals/         ← 高コスト・方向転換前の任意 proposal
research/reviews/           ← agenda checkpoint の snapshot
```

`research/agenda.md` は TODO リストではなく、現在の見立て、active question、
paused/killed、次に何をなぜ行うかを残す判断の台帳。本文は日本語で書き、
コード・コマンド・ファイルパス・run_id は実際の表記のまま残す。

project 運用レイヤーの詳細は [Layer Docs](layers/README.md) を参照。

## テスタビリティ

テスト容易性を確保するための設計:

- **Slurm モック**: `CommandRunner` 型を注入することで、実際の Slurm 環境なしでテスト可能
- **ファイルシステム**: pytest の `tmp_path` fixture を使った一時ディレクトリでの統合テスト
- **CLI**: typer の `CliRunner` による CLI テスト
- **Adapter / Launcher**: 抽象基底クラスの contract test で実装の正しさを検証
