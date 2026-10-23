# adapter ガイド

simulator package の作者向けに、runops v2 の adapter と skill の同梱方法を説明します。

## 最小の adapter

adapter は `name` 属性と 3 つの method を持つ class です。runops を import する必要は
ありません。

```python
from pathlib import Path


class Adapter:
    name = "mysim"

    def render_inputs(self, params: dict, run_dir: Path) -> list[str]:
        """run_dir/input/ にコピー済みの base file に params を適用する。"""
        from runops.adapters import toml_override   # base が TOML なら使える

        toml_override(run_dir / "input" / "mysim.toml", params)
        return ["input/mysim.toml"]

    def build_command(self, runtime, run_dir: Path) -> list[str]:
        """launcher の後ろに置く argv。job の cwd は run_dir。"""
        return [str(runtime.executable), "input/mysim.toml"]

    def detect_status(self, run_dir: Path) -> str:
        """job 終了後に呼ばれる。"completed" | "failed" | "unknown"。"""
        return "completed" if (run_dir / "work" / "DONE").exists() else "failed"
```

`render_inputs` は dotted key（`a.b`、`a.0.b`、`a[0].b`）を入力の階層に写してください。
`toml_override` はこれを実装済みです。`detect_status` が `unknown` を返すと Slurm の
状態で決まります。

## 任意の hook

| method | 用途 |
|---|---|
| `configure(sim_config)` | `runops.toml` の `[simulators.X]` を受け取る |
| `case_template() -> dict[str, str]` | `runo case new` が置く base file |
| `pip_packages() -> list[str]` | `runo init` / `runo update` が `.venv` に入れる package |
| `resolve_runtime(sim_config, venv) -> RuntimeInfo` | executable 解決を自前で行う場合 |
| `collect_provenance(runtime) -> dict` | manifest の `[simulator]` に足す値 |
| `validate_params(params) -> list[str]` | warning 文字列 |
| `job_prelude(run_dir) -> list[str]` | job.sh で実行直前に置く shell 行 |
| `summarize(run_dir) -> dict` | `runo summarize` の内容 |
| `keep_patterns() -> list[str]` | `tidy --purge-work` で残す glob |
| `extend_inputs(src_run, run_dir, params) -> list[str]` | `runo new --from RUN --continue` の restart 設定 |
| `agent_context_dir() -> Path | None` | 同梱 skill と reference の場所 |

`runtime` は `executable`、`package_version`、`exe_hash`、`git_commit`、`git_dirty`、
`env`、`resolver_mode`、`build_dir` を持ちます。

## 公開方法

package の `pyproject.toml` に entry point を書きます。entry point 名が
`[simulators.X].adapter` の値です。

```toml
[project.entry-points."runops.adapters"]
mysim = "mysim_tools.runops_adapter:Adapter"
```

runops は自身の環境と project の `.venv` の両方から entry point を探します。
editable install（`pip install -e`）でも動きます。package が無い間は、同じ class を
project の `adapters/mysim.py` に `Adapter` という名前で置けば使えます。entry point が
あればそちらが優先されます。`runo doctor` がどちらで解決したかを表示します。

## skill と reference の同梱

`agent_context_dir()` が返す directory を次の形にします。

```text
<dir>/
  skills/<skill-name>/SKILL.md
  references/*.md
```

`runo init` と `runo update` は `skills/*` を project の `.agents/skills/` と
`.claude/skills/` に同名でコピーし、`references/` を `<adapter>-references` として置きます。
skill 名は package 側で名前空間を付けてください（例: `mysim-input-review`）。
`runops-` で始まる名前は予約されています。skill から reference へは
`../<adapter>-references/X.md` と書いてください。package 内の配置どおりの
`../../references/X.md` は展開時にこの形へ書き換えます。`runo doctor` は展開済み skill の
相対リンク切れを報告します。展開した directory には
`.managed-by-runops` が置かれ、更新時に上書きされます。利用者が作った同名 directory は
上書きしません。

wheel に含めるには、その directory を package data に入れます。source checkout だけで
使う場合は、repository 内の path を返しても構いません。

## 既存の EMSES / BEACH adapter

v1 から移植した adapter は `src/runops/legacy_adapters/` にあります。`runo migrate-v1` と、
entry point が見つからないときの `runo init emses` / `runo init beach` が、project の
`adapters/` にコピーします。MPIEMSES3D と BEACH の package が entry point を
公開したら、legacy 版は削除できます。
