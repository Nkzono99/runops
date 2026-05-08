"""Generate the src/runops structure guide using Python Diagrams."""
# ruff: noqa: E501

from __future__ import annotations

from pathlib import Path

try:
    from diagrams import Cluster, Edge
    from diagrams.generic.compute import Rack
    from diagrams.generic.storage import Storage
    from diagrams.onprem.client import User
    from diagrams.onprem.vcs import Git
    from diagrams.programming.language import Python
except ModuleNotFoundError as exc:
    raise SystemExit(
        "Python package 'diagrams' is not installed.\n"
        "Use the Docker renderer instead:\n"
        "  python scripts/render_diagrams_in_docker.py"
    ) from exc

from diagram_utils import (
    DOCS_ROOT,
    make_diagram,
    markdown_image,
    node_attrs,
    png_path,
    prepare_figure_dir,
    require_graphviz,
)

SRC_ROOT = Path(__file__).resolve().parent.parent / "src" / "runops"
DOC_PATH = DOCS_ROOT / "src-structure.md"

DIRECTORY_LABELS: dict[str, str] = {
    "cli": "Typer ベースの CLI エントリポイントと対話 UX",
    "core": "ドメインモデル、実行オーケストレーション、manifest、state、knowledge",
    "adapters": "シミュレータ固有処理と adapter registry",
    "launchers": "MPI 起動ラッパーと launcher factory",
    "jobgen": "job、launcher、site から job.sh を組み立てる層",
    "slurm": "sbatch / squeue / sacct の薄いラッパー",
    "sites": "runops init だけが読む bundled site preset",
    "templates": "project / case / survey にコピーされる静的テンプレート",
}

KEY_FILES: tuple[tuple[str, str], ...] = (
    ("src/runops/cli/main.py", "最上位のコマンド登録。"),
    ("src/runops/core/actions/", "CLI と agent が使う action facade と registry。"),
    (
        "src/runops/core/run_creation/",
        "case -> adapter -> launcher -> site -> job.sh をつなぐ実行時の中心。",
    ),
    (
        "src/runops/core/site/",
        "runtime の site 解決。site.toml、legacy launcher fallback、STANDARD_SITE を扱う。",
    ),
    (
        "src/runops/adapters/registry.py",
        "simulator adapter の registry と import-by-name 解決。",
    ),
    (
        "src/runops/launchers/base.py",
        "Launcher.from_config() による launcher factory と profile 読み込み。",
    ),
    (
        "src/runops/jobgen/generator.py",
        "site 固有の module / directive を含む最終的な Slurm job script 生成。",
    ),
    (
        "src/runops/slurm/query.py",
        "Slurm state の問い合わせと runops RunState への写像。",
    ),
    (
        "src/runops/cli/init/command.py",
        "init 時の対話 UX、project scaffold、site preset 書き出し。",
    ),
    (
        "src/runops/cli/init/bootstrap.py",
        "init 後の `.venv`、`tools/runops`、editable install bootstrap。",
    ),
    ("src/runops/cli/init/scaffold.py", "init/setup で共有する scaffold helper。"),
)


def _count_directory_entries(path: Path) -> str:
    if path.name == "sites":
        toml_count = len(list(path.glob("*.toml")))
        md_count = len(list(path.glob("*.md")))
        return f"{toml_count} 個の preset TOML、{md_count} 個の companion doc"

    if path.name == "templates":
        file_count = len(
            [p for p in path.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
        )
        return f"{file_count} 個の template asset"

    file_count = len([p for p in path.rglob("*.py") if "__pycache__" not in p.parts])
    return f"{file_count} 個の Python module"


def _build_directory_table() -> str:
    header = [
        "| Directory | 役割 | 現在の規模 |",
        "|---|---|---|",
    ]
    rows: list[str] = []
    for name in (
        "cli",
        "core",
        "adapters",
        "launchers",
        "jobgen",
        "slurm",
        "sites",
        "templates",
    ):
        path = SRC_ROOT / name
        rows.append(
            f"| `{name}/` | {DIRECTORY_LABELS[name]} | {_count_directory_entries(path)} |"
        )
    return "\n".join(header + rows)


def _build_overview(figure_dir: str) -> str:
    base = prepare_figure_dir(figure_dir) / "overview"
    with make_diagram(
        name="src/runops の全体構造",
        filename=base,
        direction="LR",
        graph_attr={"nodesep": "0.8", "ranksep": "1.0"},
    ):
        project_files = Storage(
            "project files\nrunops / simulators \n / launchers / site / \n case / survey",
            **node_attrs("artifact"),
        )

        with Cluster("src/runops"):
            cli = User(
                "cli/\nTyper command \nと command grouping", **node_attrs("human")
            )
            core = Python(
                "core/\nProject / Case / Survey / Run /\nActions / State / Knowledge",
                **node_attrs("agent"),
            )
            adapters = Rack(
                "adapters/\nSimulator adapter と registry",
                **node_attrs("runtime"),
            )
            launchers = Rack(
                "launchers/\nsrun / mpirun / mpiexec factory",
                **node_attrs("runtime"),
            )
            site_core = Rack(
                "core/site/\nruntime site abstraction", **node_attrs("config")
            )
            jobgen = Rack("jobgen/\nsubmit/job.sh 生成", **node_attrs("artifact"))
            slurm = Rack(
                "slurm/\nsbatch / squeue / sacct wrapper", **node_attrs("artifact")
            )
            templates = Storage(
                "templates/\ncase / survey / \n scaffold / agent asset",
                **node_attrs("config"),
            )
            bundled_sites = Git(
                "sites/\ninit 専用 bundled site preset",
                **node_attrs("config"),
            )

        project_files >> Edge(label="Project/Case/Survey data に変換") >> core
        cli >> Edge(label="多くの command はここへ委譲") >> core
        cli >> Edge(label="config/new/update-refs は registry を使う") >> adapters
        cli >> Edge(label="init/new が scaffold をコピー") >> templates
        cli >> Edge(label="init が preset TOML/MD を読む") >> bundled_sites
        core >> Edge(label="simulator 依存を解決") >> adapters
        core >> Edge(label="MPI 起動方式を解決") >> launchers
        core >> Edge(label="runtime site profile を解決") >> site_core
        core >> Edge(label="job.sh を組み立てる") >> jobgen
        core >> Edge(label="submit と sync") >> slurm
        adapters >> Edge(label="template と guide") >> templates
        site_core >> Edge(label="module/env/sbatch option") >> jobgen
        slurm >> Edge(label="Slurm state を RunState へ戻す") >> core

    return markdown_image(DOC_PATH, png_path(base), "src/runops の全体構造")


def _build_run_creation(figure_dir: str) -> str:
    base = prepare_figure_dir(figure_dir) / "run-creation-resolution"
    with make_diagram(
        name="runs create / sweep の依存解決",
        filename=base,
        direction="LR",
        graph_attr={"nodesep": "0.8", "ranksep": "1.0", "splines": "spline"},
    ):
        create_cli = User(
            "runs create / sweep\ncli/create.py",
            **node_attrs("human"),
        )
        actions = Python(
            "actions.py\ncreate_run / create_survey",
            **node_attrs("agent"),
        )
        with Cluster("入力"):
            project = Storage(
                "project config\nrunops / simulators /\nlaunchers",
                **node_attrs("config"),
            )
            case = Storage(
                "case / survey\ncase.toml / survey.toml",
                **node_attrs("config"),
            )

        with Cluster("解決"):
            adapter_lookup = Rack(
                "adapter 解決\nsimulator -> adapter 名",
                **node_attrs("runtime"),
            )
            adapter_import = Rack(
                "adapter registry\ncontrib.<name> / <name>",
                **node_attrs("runtime"),
            )
            adapter = Rack(
                "adapter instance\ninputs / command /\nprovenance",
                **node_attrs("runtime"),
            )
            launcher = Rack(
                "launcher 解決\nlaunchers.toml + type",
                **node_attrs("runtime"),
            )
            site = Rack(
                "site 解決\nsite.toml -> legacy ->\nSTANDARD_SITE",
                **node_attrs("config"),
            )

        jobgen = Rack("jobgen\njob.sh 生成", **node_attrs("artifact"))
        run_artifact = Rack(
            "run dir\ninput/ submit/job.sh\nmanifest.toml",
            **node_attrs("artifact"),
        )

        create_cli >> actions
        actions >> project
        actions >> case
        project >> adapter_lookup
        case >> adapter_lookup
        adapter_lookup >> adapter_import >> adapter
        project >> launcher
        case >> launcher
        project >> site
        adapter >> jobgen
        launcher >> jobgen
        site >> jobgen
        jobgen >> run_artifact
        adapter >> run_artifact
        case >> run_artifact

    return markdown_image(DOC_PATH, png_path(base), "runs create と sweep の依存解決")


def _build_site_resolution(figure_dir: str) -> str:
    base = prepare_figure_dir(figure_dir) / "site-resolution"
    with make_diagram(
        name="site の init 時 preset と runtime 解決",
        filename=base,
        direction="LR",
        graph_attr={"nodesep": "0.85", "ranksep": "1.0", "splines": "spline"},
    ):
        bundled = Git(
            "bundled preset\nsrc/runops/sites/*.toml\n+ *.md",
            **node_attrs("config"),
        )
        init_cli = User("runops init\ncli/init/", **node_attrs("human"))
        project_site = Storage(
            "project site.toml\nruntime source of truth",
            **node_attrs("config"),
        )
        project_launchers = Storage(
            "launchers.toml\nlegacy default",
            **node_attrs("config"),
        )
        case_new = User(
            "runops case new\nresource_style を参照",
            **node_attrs("human"),
        )
        runtime = Python("core/site/\nload_site_profile()", **node_attrs("agent"))
        standard = Rack("STANDARD_SITE", **node_attrs("artifact"))
        jobgen = Rack("jobgen\ngenerate_job_script()", **node_attrs("artifact"))
        job_sh = Rack(
            "submit/job.sh\nmodule / env / #SBATCH",
            **node_attrs("artifact"),
        )

        bundled >> init_cli
        init_cli >> project_site
        init_cli >> project_launchers
        project_site >> runtime
        project_launchers >> runtime
        standard >> runtime
        project_site >> case_new
        runtime >> jobgen >> job_sh

    return markdown_image(
        DOC_PATH, png_path(base), "site の init 時 preset と runtime 解決"
    )


def _build_document() -> str:
    figure_dir = "src-structure"
    overview = _build_overview(figure_dir)
    run_creation = _build_run_creation(figure_dir)
    site_resolution = _build_site_resolution(figure_dir)
    key_files_lines = [f"- `{path}`: {description}" for path, description in KEY_FILES]

    lines = [
        "# src/runops 構成ガイド",
        "",
        "> このファイルは `python scripts/generate_architecture_diagrams.py` で生成しています。",
        "> 標準の再生成手順は `python scripts/render_diagrams_in_docker.py` です。",
        "",
        "runops の `src/` は、まず次の 3 つを分けて考えると読みやすくなります。",
        "",
        "- `cli/` は人間や agent が直接叩く Typer ベースの入り口です。",
        "- `core/` は domain model だけでなく、project 設定から adapter / launcher / site / Slurm をつなぐ orchestration module も持っています。",
        "- `adapters/`、`launchers/`、`core/site/` はそれぞれ別の可変軸です。",
        "  simulator 固有差分、MPI 起動方式、cluster/site 固有差分を分離しています。",
        "",
        "いまの実装で特に混乱しやすいのは `site` まわりです。",
        "",
        "- `src/runops/sites/` は project の runtime site 設定そのものではありません。",
        "- ここは `runops init` が一度だけ読む bundled preset 集です。",
        "- 実行時に使われる site の本体は project root の `site.toml` で、解決ロジックは `src/runops/core/site/` にあります。",
        "",
        "## top-level directory 一覧",
        "",
        _build_directory_table(),
        "",
        "## 全体構造",
        "",
        overview,
        "",
        "## runs create / sweep の依存解決",
        "",
        run_creation,
        "",
        "## site の init 時 preset と runtime 解決",
        "",
        site_resolution,
        "",
        "## adapter / launcher 解決の要点",
        "",
        'たとえば `case.toml` に `simulator = "emses"`、`launcher = "camphor"` と書かれているとき、',
        "実行時の解決は次の順で進みます。",
        "",
        "- `core/run_creation/` が project、case、必要なら survey override を読みます。",
        "- simulator entry は `project.simulators` から引かれます。",
        "- `load_adapter_for_simulator()` がその entry から adapter 名を取り出します。",
        "- `AdapterRegistry.load_from_config()` は `runops.adapters.contrib.<adapter>` を先に、次に `runops.adapters.<adapter>` を import しようとします。",
        "- import に成功すると registry から adapter class を取り出し、instance 化します。",
        "- launcher 側はより単純で、`load_launchers()` が `launchers.toml` をたどり、`Launcher.from_config()` が `type` / `kind` に応じて `SrunLauncher`、`MpirunLauncher`、`MpiexecLauncher` を選びます。",
        "- `core/site.load_site_profile()` は launcher と独立に site を解決し、最後に `jobgen.generate_job_script()` が launcher 出力と site 固有の module、environment variable、stdout/stderr format、追加 `#SBATCH` directive を合成します。",
        "",
        "つまり責務分担は次のように切られています。",
        "",
        "- Adapter は `何を実行するか` と `入出力がどう見えるか` を決めます。",
        "- Launcher は `その program command を MPI でどう包むか` を決めます。",
        "- Site は `その cluster が job script に何を要求するか` を決めます。",
        "",
        "## 次に読むと理解しやすい file",
        "",
        *key_files_lines,
        "",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    require_graphviz()
    DOC_PATH.write_text(_build_document(), encoding="utf-8")
    print(f"Wrote {DOC_PATH.relative_to(DOCS_ROOT.parent)}")


if __name__ == "__main__":
    main()
