# 拡張ガイド

このドキュメントでは、runops に新しい Simulator Adapter や Launcher Profile を追加する方法を説明します。

---

## 新しい Simulator Adapter の追加

### 概要

Simulator Adapter は、シミュレータ固有の処理を吸収するためのコンポーネントです。新しいシミュレータに対応するには、以下のステップで Adapter を実装します。

### ステップ 1: Adapter クラスの作成

`src/runops/adapters/` に新しい Python ファイルを作成します。

例: `src/runops/adapters/my_solver.py`

```python
"""Adapter for my_solver simulator."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from runops.adapters.base import SimulatorAdapter
from runops.adapters.registry import register


@register
class MySolverAdapter(SimulatorAdapter):
    """Adapter for the my_solver particle simulation code.

    Conventions:
    - Input file: input/config.toml
    - Executable: specified via simulators.toml
    - Success marker: work/COMPLETED file
    """

    adapter_name: str = "my_solver"

    @property
    def name(self) -> str:
        return self.adapter_name

    def render_inputs(
        self,
        case_data: dict[str, Any],
        run_dir: Path,
    ) -> list[str]:
        ...

    def resolve_runtime(
        self,
        simulator_config: dict[str, Any],
        resolver_mode: str,
    ) -> dict[str, Any]:
        ...

    def build_program_command(
        self,
        runtime_info: dict[str, Any],
        run_dir: Path,
    ) -> list[str]:
        ...

    def detect_outputs(self, run_dir: Path) -> dict[str, Any]:
        ...

    def detect_status(self, run_dir: Path) -> str:
        ...

    def summarize(self, run_dir: Path) -> dict[str, Any]:
        ...

    def collect_provenance(
        self,
        runtime_info: dict[str, Any],
    ) -> dict[str, Any]:
        ...
```

### ステップ 2: 7 つのメソッドの実装

#### 1. `render_inputs(case_data, run_dir) -> list[str]`

シミュレータ固有の入力ファイルを `run_dir/input/` に生成します。

**引数:**
- `case_data`: `{"case": {...}, "params": {...}}` の形式。`params` にシミュレーションパラメータが入っています。
- `run_dir`: run ディレクトリのパス

**戻り値:** 生成した入力ファイルの相対パス（run_dir 基準）のリスト

**実装例:**

```python
def render_inputs(
    self,
    case_data: dict[str, Any],
    run_dir: Path,
) -> list[str]:
    params = case_data.get("params", {})
    input_dir = run_dir / "input"
    input_dir.mkdir(parents=True, exist_ok=True)

    # シミュレータ固有の入力ファイルを生成
    config = {
        "grid": {
            "nx": params.get("nx", 256),
            "ny": params.get("ny", 256),
        },
        "physics": {
            "dt": params.get("dt", 1e-8),
            "velocity": params.get("u", 4e5),
        },
    }

    config_file = input_dir / "config.toml"
    # TOML形式で書き出す例
    import tomli_w
    with open(config_file, "wb") as f:
        tomli_w.dump(config, f)

    return [str(config_file.relative_to(run_dir))]
```

#### 2. `resolve_runtime(simulator_config, resolver_mode) -> dict`

シミュレータの実行ファイルを解決します。

**引数:**
- `simulator_config`: `simulators.toml` の当該シミュレータセクション
- `resolver_mode`: `"package"`, `"local_source"`, `"local_executable"` のいずれか

**戻り値:** 少なくとも `executable` と `resolver_mode` キーを含む辞書

**実装例:**

```python
def resolve_runtime(
    self,
    simulator_config: dict[str, Any],
    resolver_mode: str,
) -> dict[str, Any]:
    runtime: dict[str, Any] = {"resolver_mode": resolver_mode}

    if resolver_mode == "local_executable":
        executable = simulator_config.get("executable", "")
        if not executable:
            raise ValueError("'executable' is required for local_executable mode")
        runtime["executable"] = executable

    elif resolver_mode == "local_source":
        source_repo = simulator_config.get("source_repo", "")
        executable = simulator_config.get("executable", "")
        runtime["source_repo"] = source_repo
        runtime["executable"] = executable
        runtime["build_command"] = simulator_config.get("build_command", "")

    elif resolver_mode == "package":
        import shutil
        exe_name = simulator_config.get("executable", "my_solver")
        resolved = shutil.which(exe_name)
        runtime["executable"] = resolved or exe_name

    return runtime
```

#### 3. `build_program_command(runtime_info, run_dir) -> list[str]`

MPI Launcher なしのシミュレータ実行コマンドを構築します。

**引数:**
- `runtime_info`: `resolve_runtime()` の戻り値
- `run_dir`: run ディレクトリのパス

**戻り値:** コマンドを文字列のリストで返す（Launcher がこれを MPI ラッパーで包む）

**実装例:**

```python
def build_program_command(
    self,
    runtime_info: dict[str, Any],
    run_dir: Path,
) -> list[str]:
    executable = runtime_info["executable"]
    config_file = run_dir / "input" / "config.toml"
    return [executable, str(config_file)]
```

#### 4. `detect_outputs(run_dir) -> dict`

シミュレーション出力ファイルを検出します。

**実装例:**

```python
def detect_outputs(self, run_dir: Path) -> dict[str, Any]:
    work_dir = run_dir / "work"
    outputs: dict[str, Any] = {}

    # シミュレータ固有の出力ファイルを検出
    for pattern in ["*.h5", "*.vtk", "*.dat"]:
        for path in work_dir.glob(pattern):
            outputs[path.stem] = str(path.relative_to(run_dir))

    return outputs
```

`runo runs status` / `runo context` の analysis readiness は、この戻り値と
`required_outputs()` を組み合わせて判定する。解析に必須の出力カテゴリがある
adapter は、`detect_outputs()` の top-level key に合わせて宣言する。

```python
@classmethod
def required_outputs(cls) -> dict[str, str]:
    return {"fields": "field HDF5 output files"}
```

#### 5. `detect_status(run_dir) -> str`

出力ファイルからシミュレーションの成功/失敗を判定します。

**実装例:**

```python
def detect_status(self, run_dir: Path) -> str:
    work_dir = run_dir / "work"

    # シミュレータ固有の完了マーカーを確認
    completed_marker = work_dir / "COMPLETED"
    if completed_marker.exists():
        return "completed"

    error_log = work_dir / "error.log"
    if error_log.exists() and error_log.stat().st_size > 0:
        return "failed"

    if work_dir.is_dir() and any(work_dir.iterdir()):
        return "running"

    return "unknown"
```

#### 6. `summarize(run_dir) -> dict`

出力から主要指標を抽出し、summary を生成します。

**実装例:**

```python
def summarize(self, run_dir: Path) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "status": self.detect_status(run_dir),
        "outputs": self.detect_outputs(run_dir),
    }

    # シミュレータ固有の指標を抽出
    stats_file = run_dir / "work" / "statistics.json"
    if stats_file.exists():
        import json
        stats = json.loads(stats_file.read_text())
        summary["total_steps"] = stats.get("total_steps", 0)
        summary["final_energy"] = stats.get("final_energy", 0.0)

    return summary
```

#### 7. `collect_provenance(runtime_info) -> dict`

manifest.toml の `[simulator_source]` セクションに記録する provenance 情報を収集します。

**実装例:**

```python
def collect_provenance(
    self,
    runtime_info: dict[str, Any],
) -> dict[str, Any]:
    import hashlib

    provenance: dict[str, Any] = {
        "resolver_mode": runtime_info.get("resolver_mode", ""),
        "executable": runtime_info.get("executable", ""),
        "exe_hash": "",
        "git_commit": "",
        "git_dirty": False,
        "source_repo": runtime_info.get("source_repo", ""),
        "build_command": runtime_info.get("build_command", ""),
        "package_version": "",
    }

    # 実行ファイルのハッシュを計算
    exe_path = Path(runtime_info.get("executable", ""))
    if exe_path.is_file():
        h = hashlib.sha256()
        with exe_path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        provenance["exe_hash"] = f"sha256:{h.hexdigest()}"

    # local_source の場合は git 情報を収集
    if runtime_info.get("resolver_mode") == "local_source":
        import subprocess
        repo = runtime_info.get("source_repo", "")
        if repo:
            try:
                result = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    capture_output=True, text=True,
                    cwd=repo, check=True,
                )
                provenance["git_commit"] = result.stdout.strip()
            except (subprocess.CalledProcessError, FileNotFoundError):
                pass

    return provenance
```

### ステップ 3: Registry への登録

上の例では `@register` デコレータを使って自動登録しています。これにより、モジュールが import された時点でグローバル Registry に登録されます。

デコレータを使わない場合は、明示的に登録することもできます:

```python
from runops.adapters.registry import register

register(MySolverAdapter, name="my_solver")
```

自動 import の仕組み: `simulators.toml` で `adapter = "my_solver"` と指定すると、`AdapterRegistry.load_from_config()` が `runops.adapters.my_solver` モジュールを自動的に import します。このため、モジュールファイル名が adapter 名と一致している必要があります。

### ステップ 4: simulators.toml への追加

```toml
[simulators.my_solver]
adapter = "my_solver"
resolver_mode = "local_executable"
executable = "/path/to/my_solver"
# その他シミュレータ固有の設定
source_repo = "/path/to/source"
build_command = "cmake --build build"
```

### ステップ 5: テストの作成

`tests/test_adapters/test_my_solver.py` にテストを作成します:

```python
"""Tests for my_solver adapter."""

from pathlib import Path
from typing import Any

import pytest

from runops.adapters.my_solver import MySolverAdapter


@pytest.fixture
def adapter() -> MySolverAdapter:
    return MySolverAdapter()


@pytest.fixture
def sample_case_data() -> dict[str, Any]:
    return {
        "case": {"name": "test_case", "simulator": "my_solver"},
        "params": {"nx": 128, "ny": 128, "dt": 1e-8, "u": 4e5},
    }


class TestRenderInputs:
    def test_creates_config_file(
        self, adapter: MySolverAdapter, sample_case_data: dict[str, Any], tmp_path: Path
    ) -> None:
        run_dir = tmp_path / "R20260327-0001"
        run_dir.mkdir()
        (run_dir / "input").mkdir()

        files = adapter.render_inputs(sample_case_data, run_dir)

        assert len(files) > 0
        assert (run_dir / files[0]).exists()


class TestResolveRuntime:
    def test_local_executable(self, adapter: MySolverAdapter, tmp_path: Path) -> None:
        exe = tmp_path / "solver"
        exe.write_text("#!/bin/bash\necho hello")
        exe.chmod(0o755)

        config = {"executable": str(exe), "resolver_mode": "local_executable"}
        runtime = adapter.resolve_runtime(config, "local_executable")

        assert runtime["executable"] == str(exe)
        assert runtime["resolver_mode"] == "local_executable"


class TestDetectStatus:
    def test_completed(self, adapter: MySolverAdapter, tmp_path: Path) -> None:
        run_dir = tmp_path / "R20260327-0001"
        work_dir = run_dir / "work"
        work_dir.mkdir(parents=True)
        (work_dir / "COMPLETED").touch()

        assert adapter.detect_status(run_dir) == "completed"

    def test_unknown_when_empty(self, adapter: MySolverAdapter, tmp_path: Path) -> None:
        run_dir = tmp_path / "R20260327-0001"
        (run_dir / "work").mkdir(parents=True)

        assert adapter.detect_status(run_dir) == "unknown"
```

### GenericAdapter の継承

多くの場合、ゼロから実装するよりも `GenericAdapter` を継承して必要な部分だけオーバーライドする方が効率的です:

```python
from runops.adapters.generic import GenericAdapter
from runops.adapters.registry import register


@register
class MyExtendedAdapter(GenericAdapter):
    """Extended adapter that customizes input rendering and status detection."""

    adapter_name: str = "my_extended"

    def render_inputs(self, case_data, run_dir):
        # カスタムの入力生成ロジック
        ...

    def detect_status(self, run_dir):
        # カスタムの状態検出ロジック
        ...

    # 他のメソッドは GenericAdapter のデフォルト実装を継承
```

---

## 新しい Launcher Profile の追加

### 概要

新しい MPI 起動方式に対応するには、`Launcher` 基底クラスを継承した新しい Launcher を実装します。

### ステップ 1: Launcher クラスの作成

`src/runops/launchers/` に新しい Python ファイルを作成します。

例: `src/runops/launchers/custom_mpi.py`

```python
"""Custom MPI launcher profile."""

from __future__ import annotations

import shlex
from typing import Any

from runops.launchers.base import Launcher, LauncherConfigError


class CustomMpiLauncher(Launcher):
    """Launcher for a custom MPI implementation.

    Attributes:
        np_flag: Flag for specifying the number of processes.
        hostfile_flag: Flag for specifying the hostfile.
    """

    def __init__(
        self,
        name: str,
        command: str,
        *,
        use_slurm_ntasks: bool = False,
        extra_options: list[str] | None = None,
        np_flag: str = "--np",
        hostfile_flag: str = "--hostfile",
    ) -> None:
        super().__init__(
            name=name,
            command=command,
            use_slurm_ntasks=use_slurm_ntasks,
            extra_options=extra_options,
        )
        self._np_flag = np_flag
        self._hostfile_flag = hostfile_flag

    @property
    def kind(self) -> str:
        return "custom_mpi"

    def build_launch_command(
        self,
        program_command: list[str],
        ntasks: int,
        extra_options: dict[str, Any] | None = None,
    ) -> list[str]:
        if not program_command:
            raise LauncherConfigError("program_command must not be empty.")

        parts: list[str] = [self.command]

        if not self.use_slurm_ntasks:
            parts.extend([self._np_flag, str(ntasks)])

        parts.extend(self._extra_options)

        if extra_options:
            for key, value in extra_options.items():
                if value is True:
                    parts.append(f"--{key}")
                elif value is not False and value is not None:
                    parts.append(f"--{key}={value}")

        parts.extend(program_command)
        return parts

    def build_exec_line(
        self,
        program_command: list[str],
        ntasks: int,
        extra_options: dict[str, Any] | None = None,
    ) -> str:
        if not program_command:
            raise LauncherConfigError("program_command must not be empty.")

        parts: list[str] = [self.command]

        if self.use_slurm_ntasks:
            parts.extend([self._np_flag, "${SLURM_NTASKS}"])
        else:
            parts.extend([self._np_flag, str(ntasks)])

        parts.extend(self._extra_options)

        if extra_options:
            for key, value in extra_options.items():
                if value is True:
                    parts.append(f"--{key}")
                elif value is not False and value is not None:
                    parts.append(f"--{key}={value}")

        prog_str = " ".join(shlex.quote(p) for p in program_command)
        option_str = " ".join(shlex.quote(p) for p in parts)
        return f"{option_str} {prog_str}"
```

### ステップ 2: ファクトリメソッドへの登録

`src/runops/launchers/base.py` の `Launcher.from_config()` メソッドに新しい kind を追加します:

```python
@classmethod
def from_config(cls, name: str, config: dict[str, Any]) -> Launcher:
    # ... 既存のコード ...

    if kind == "srun":
        return SrunLauncher(...)
    elif kind == "mpirun":
        return MpirunLauncher(...)
    elif kind == "mpiexec":
        return MpiexecLauncher(...)
    elif kind == "custom_mpi":                          # 追加
        from runops.launchers.custom_mpi import CustomMpiLauncher
        np_flag = str(config.get("np_flag", "--np"))
        return CustomMpiLauncher(
            name=name,
            command=str(command),
            use_slurm_ntasks=use_slurm,
            extra_options=extra_opts,
            np_flag=np_flag,
        )
    else:
        raise LauncherConfigError(...)
```

### ステップ 3: launchers.toml への追加

```toml
[launchers.my_custom_mpi]
kind = "custom_mpi"
command = "/opt/custom-mpi/bin/mpirun"
np_flag = "--np"
use_slurm_ntasks = true
extra_options = ["--bind-to", "core"]
```

### ステップ 4: テストの作成

`tests/test_launchers/test_custom_mpi.py`:

```python
"""Tests for custom MPI launcher."""

from __future__ import annotations

import pytest

from runops.launchers.custom_mpi import CustomMpiLauncher
from runops.launchers.base import LauncherConfigError


@pytest.fixture
def launcher() -> CustomMpiLauncher:
    return CustomMpiLauncher(
        name="test_custom",
        command="custom_mpirun",
        use_slurm_ntasks=False,
        np_flag="--np",
    )


@pytest.fixture
def slurm_launcher() -> CustomMpiLauncher:
    return CustomMpiLauncher(
        name="test_custom_slurm",
        command="custom_mpirun",
        use_slurm_ntasks=True,
        np_flag="--np",
    )


class TestBuildLaunchCommand:
    def test_basic(self, launcher: CustomMpiLauncher) -> None:
        cmd = launcher.build_launch_command(["./solver", "input.toml"], ntasks=4)
        assert cmd == ["custom_mpirun", "--np", "4", "./solver", "input.toml"]

    def test_empty_program_raises(self, launcher: CustomMpiLauncher) -> None:
        with pytest.raises(LauncherConfigError):
            launcher.build_launch_command([], ntasks=4)


class TestBuildExecLine:
    def test_slurm_ntasks(self, slurm_launcher: CustomMpiLauncher) -> None:
        line = slurm_launcher.build_exec_line(["./solver"], ntasks=4)
        assert "${SLURM_NTASKS}" in line

    def test_explicit_ntasks(self, launcher: CustomMpiLauncher) -> None:
        line = launcher.build_exec_line(["./solver"], ntasks=8)
        assert "--np" in line
        assert "8" in line
```

---

## 設定ファイルリファレンス

### runops.toml

プロジェクトの基本設定。

```toml
[project]
name = "my-simulation-project"   # 必須: プロジェクト名
description = "説明文"            # 任意: プロジェクトの説明
```

### simulators.toml

シミュレータの定義。`[simulators]` テーブルの下に各シミュレータを定義します。

```toml
[simulators.solver_a]
adapter = "generic"              # 必須: 使用する Adapter 名
resolver_mode = "local_executable"  # 必須: 解決モード
executable = "/path/to/solver"   # 必須: 実行ファイルパス

[simulators.solver_b]
adapter = "my_solver"            # カスタム Adapter
resolver_mode = "local_source"
source_repo = "/path/to/source"
executable = "/path/to/source/build/solver"
build_command = "make -j"
```

**resolver_mode の種類:**

| モード | 説明 | 必須フィールド |
|-------|------|--------------|
| `package` | PATH 上のインストール済みコマンド | `executable` (コマンド名) |
| `local_source` | ローカルソースからビルド | `source_repo`, `executable` |
| `local_executable` | ビルド済み実行ファイルを直接指定 | `executable` (フルパス) |

### launchers.toml

Launcher Profile の定義。`[launchers]` テーブルの下に各プロファイルを定義します。

```toml
[launchers.slurm_srun]
kind = "srun"                    # 必須: Launcher の種類
command = "srun"                 # 必須: 実行コマンド
use_slurm_ntasks = true          # 任意: SLURM_NTASKS を使うか (default: false)
extra_options = []               # 任意: 追加オプション

[launchers.openmpi]
kind = "mpirun"
command = "mpirun"
np_flag = "-np"                  # mpirun 固有: プロセス数フラグ
use_slurm_ntasks = true

[launchers.mpiexec]
kind = "mpiexec"
command = "mpiexec"
n_flag = "-n"                    # mpiexec 固有: プロセス数フラグ
use_slurm_ntasks = true
```

**kind の種類:**

| kind | クラス | 生成される実行行の例 |
|------|--------|-------------------|
| `srun` | `SrunLauncher` | `srun ./solver input.toml` |
| `mpirun` | `MpirunLauncher` | `mpirun -np ${SLURM_NTASKS} ./solver input.toml` |
| `mpiexec` | `MpiexecLauncher` | `mpiexec -n ${SLURM_NTASKS} ./solver input.toml` |

### case.toml

Case (run の雛形) の定義。

```toml
[case]
name = "cavity_base"             # 必須: Case 名
simulator = "my_solver"          # 必須: シミュレータ名 (simulators.toml のキー)
launcher = "slurm_srun"          # 必須: Launcher 名 (launchers.toml のキー)
description = "説明文"            # 任意

[classification]                  # 任意: 分類メタデータ
model = "cavity"
submodel = "rectangular"
tags = ["baseline"]

[job]                             # Slurm ジョブ設定
partition = "compute"             # 必須: パーティション名
nodes = 1                        # 任意: ノード数 (default: 1)
ntasks = 32                      # 任意: タスク数 (default: 1)
walltime = "12:00:00"            # 任意: 制限時間 (default: "01:00:00")

[params]                          # シミュレーション固有パラメータ
nx = 256                         # Adapter が解釈する任意のキー・値
ny = 256
dt = 1.0e-8
```

### survey.toml

パラメータサーベイの定義。

```toml
[survey]
id = "S20260327-scan"            # 必須: Survey ID
name = "parameter scan"          # 任意: 表示名
base_case = "cavity_base"        # 必須: 基底 Case 名
simulator = "my_solver"          # 必須: シミュレータ名
launcher = "slurm_srun"          # 必須: Launcher 名

[classification]                  # 任意: survey レベルの分類
model = "cavity"
submodel = "rectangular"
tags = ["scan"]

[axes]                            # 必須: パラメータ軸 (直積が展開される)
nx = [128, 256, 512]
dt = [1.0e-8, 1.0e-9]

[naming]                          # 任意: display_name テンプレート
display_name = "nx{nx}_dt{dt}"   # {key} がパラメータ値で置換される

[job]                             # 任意: survey レベルの job 設定
partition = "compute"            # 指定しなければ base_case の設定を継承
nodes = 1
ntasks = 32
walltime = "12:00:00"
```

### manifest.toml

run の正本情報。runops が自動生成・更新します。手動編集は通常不要です。

全セクションのリファレンスは [SPEC.md](../SPEC.md) のセクション 12 を参照してください。

---

## AI エージェント対応メソッド

Adapter に以下のオプションメソッドを実装すると、AI エージェントの精度が向上します。

### parameter_schema()

パラメータの機械可読メタデータを返す:

```python
@classmethod
def parameter_schema(cls) -> dict[str, dict[str, Any]]:
    return {
        "sim.dt": {
            "type": "float",
            "unit": "s",
            "description": "Time step",
            "range": [0.0, None],
            "constraints": ["cfl_condition"],
            "derived_from": "Must satisfy dt < dx / c",
            "interdependencies": ["grid.dx"],
        },
    }
```

### validate_params()

run 生成前に物理的整合性をチェックする:

```python
def validate_params(
    self, case_data: dict[str, Any]
) -> list[ValidationIssue]:
    issues = []
    config = self._resolve_config(case_data)
    dt = config.get("sim", {}).get("dt", 0)
    if dt > 1.0:
        issues.append(ValidationIssue(
            severity="error",
            message="dt too large",
            parameter="sim.dt",
            constraint_name="cfl_condition",
        ))
    return issues
```

### knowledge_sources()

`refs/` 内でインデックス対象とするファイルパターンを返す:

```python
@classmethod
def knowledge_sources(cls) -> dict[str, list[str]]:
    return {
        "MySimulator": [
            "README.md",
            "docs/**/*.md",
            "schemas/*.json",
            "cookbook/COOKBOOK.md",
            "cookbook/index.toml",
            "cookbook/**/*.toml",
            "cookbook/**/*.md",
        ],
    }
```

simulator repo 側で `cookbook/` を提供する場合は、
少なくとも `COOKBOOK.md`、`index.toml`、各 entry の `meta.toml` を
この glob に含めることを推奨する。
cookbook の規約は `docs/simulator-kb-spec.md` を参照。

### campaign.toml との連携

`campaign.toml` の `[variables]` セクションと `parameter_schema()` を組み合わせることで、AI エージェントはパラメータの妥当性を自動検証し、survey.toml を自動生成できます。
