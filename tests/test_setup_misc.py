"""init presets, doctor, log, generic templates, case listing."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from runops.ops.setup import init_project
from runops.project import Project
from runops.util import load_toml


def test_init_camphor_preset(tmp_path: Path) -> None:
    root = tmp_path / "p"
    init_project(root, ["emses", "mysim=mysim-pkg"], site="camphor", install=False)
    config = load_toml(root / "runops.toml")
    assert config["site"]["resource_style"] == "rsc"
    assert config["simulators"]["emses"]["package"].startswith("MPIEMSES3D")
    assert config["simulators"]["emses"]["modules"][0].startswith("hdf5/")
    assert config["simulators"]["mysim"]["package"] == "mysim-pkg"
    for name in ("LOG.md", "notes/README.md", ".gitignore", "AGENTS.md", "CLAUDE.md"):
        assert (root / name).is_file()
    # no package provides the emses adapter yet -> the bundled port is placed
    assert (root / "adapters/emses.py").is_file()
    assert not (root / "adapters/mysim.py").exists()


def test_init_refuses_existing(project_dir: Path, cli) -> None:  # type: ignore[no-untyped-def]
    res = cli("init", "generic", "--no-install")
    assert res.code == 2 and "already exists" in res.err


def test_doctor_reports_missing_adapter(project_dir: Path, cli) -> None:  # type: ignore[no-untyped-def]
    cfg = project_dir / "runops.toml"
    cfg.write_text(cfg.read_text() + '\n[simulators.ghost]\nadapter = "nosuch"\n')
    res = cli("doctor", "--json")
    assert res.code == 2
    checks = json.loads(res.out)
    assert any(c["level"] == "error" and "nosuch" in c["message"] for c in checks)


def test_log(project_dir: Path, cli, fake_slurm) -> None:  # type: ignore[no-untyped-def]
    (run_id,) = cli("new", "demo", "--submit").run_ids()
    assert cli("log", run_id).code == 2
    m = Project.open(project_dir).resolve_run(run_id)
    (m.run_dir / f"work/{fake_slurm.last_job}.out").write_text(
        "\n".join(f"line{i}" for i in range(100))
    )
    (m.run_dir / f"work/{fake_slurm.last_job}.err").write_text("boom\n")
    res = cli("log", run_id, "-n", "3")
    assert res.out.split() == ["line97", "line98", "line99"]
    assert "boom" in cli("log", run_id, "--err").out


def test_generic_template_error(project_dir: Path, cli) -> None:  # type: ignore[no-untyped-def]
    (project_dir / "cases/demo/input.txt").write_text("{{ missing_value }}\n")
    res = cli("new", "demo")
    assert res.code == 1 and "missing_value" in res.err
    assert not list((project_dir / "runs").rglob("manifest.toml"))
    assert not [p for p in (project_dir / "runs").rglob("*") if p.name.endswith(".staging")]


def test_case_list_and_copy(project_dir: Path, cli) -> None:  # type: ignore[no-untyped-def]
    assert cli("case", "new", "demo2", "--from", "demo").code == 0
    assert load_toml(project_dir / "cases/demo2/case.toml")["case"]["name"] == "demo2"
    rows = json.loads(cli("case", "list", "--json").out)
    assert [r["name"] for r in rows] == ["demo", "demo2"]
    assert cli("case", "new", "bad name", "-s", "generic").code == 2


def test_dest_must_stay_in_runs(project_dir: Path, cli) -> None:  # type: ignore[no-untyped-def]
    assert cli("new", "demo", "--dest", "/tmp").code == 2
    res = cli("new", "demo", "--dest", "topic/a", "--label", "x")
    assert res.code == 0
    (run_id,) = res.run_ids()
    assert (
        Project.open(project_dir).resolve_run(run_id).run_dir.parent == project_dir / "runs/topic/a"
    )


def test_version(cli) -> None:  # type: ignore[no-untyped-def]
    res = cli("--version")
    assert res.code == 0 and res.out.strip().startswith("2.")


def test_detect_site() -> None:
    from runops.ops.setup import detect_site

    for host in ("camphor31", "laurel32", "cinnamon1", "gardenia13", "Laurel5.kudpc.kyoto-u.ac.jp"):
        assert detect_site(host) == "kudpc", host
    for host in ("xb0092", "mylaptop", "login1"):
        assert detect_site(host) == "standard", host


def test_init_guesses_site_from_hostname(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cli
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr("runops.ops.setup.hostname", lambda: "laurel32")
    monkeypatch.chdir(tmp_path)
    res = cli("init", "--no-install")
    assert res.code == 0, res.err
    assert "site: kudpc (guessed from host laurel32" in res.out
    config = load_toml(tmp_path / "runops.toml")
    assert config["site"]["resource_style"] == "rsc"
    assert config["site"]["name"] == "kudpc"


def test_init_explicit_site_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cli) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr("runops.ops.setup.hostname", lambda: "laurel32")
    monkeypatch.chdir(tmp_path)
    res = cli("init", "--site", "standard", "--no-install")
    assert "guessed" not in res.out
    assert load_toml(tmp_path / "runops.toml")["site"]["resource_style"] == "standard"
    assert cli("init", "--site", "nowhere", "--no-install").code == 2


class _Tty(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_init_interactive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cli) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr("runops.ops.setup.hostname", lambda: "camphor31")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.stdin", _Tty("\nemses, generic\n"))  # Enter keeps the guess
    res = cli("init", "--no-install")
    assert res.code == 0, res.err
    assert "guessed from host camphor31" in res.out
    config = load_toml(tmp_path / "runops.toml")
    assert config["site"]["resource_style"] == "rsc"
    assert sorted(config["simulators"]) == ["emses", "generic"]
    assert config["simulators"]["emses"]["modules"][0].startswith("hdf5/")


def test_init_not_interactive_with_yes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cli
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.stdin", _Tty(""))
    res = cli("init", "-y", "--no-install")
    assert res.code == 0, res.err
    assert load_toml(tmp_path / "runops.toml")["simulators"] == {}


def test_init_interactive_reasks_unknown_site(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cli
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.stdin", _Tty("nowhere\ncamphor\n\n"))
    res = cli("init", "--no-install")
    assert res.code == 0, res.err
    assert "unknown site preset 'nowhere'" in res.err
    assert load_toml(tmp_path / "runops.toml")["site"]["name"] == "kudpc"


def test_usage_error_exit_code(cli) -> None:  # type: ignore[no-untyped-def]
    res = cli("list", "--no-such-option")
    assert res.code == 2
    assert "no-such-option" in res.err


def test_cli_does_not_import_click_directly() -> None:
    source = (Path(__file__).parents[1] / "src/runops/cli.py").read_text()
    assert "import click" not in source  # newer typer vendors click


def test_init_install_prompt_defaults_to_yes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cli
) -> None:  # type: ignore[no-untyped-def]
    calls: list[bool] = []

    def fake_install(project, *, upgrade):  # type: ignore[no-untyped-def]
        calls.append(upgrade)
        return ["MPIEMSES3D"], []

    monkeypatch.setattr("runops.ops.setup.install_packages", fake_install)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sys.stdin", _Tty("\nemses\n\n")
    )  # site: Enter, sims: emses, install: Enter
    res = cli("init")
    assert res.code == 0, res.err
    assert "may build simulator binaries" in res.out
    assert "[Y/n]" in res.out
    assert calls == [False]
    assert "installed MPIEMSES3D" in res.out


def test_init_install_declined_keeps_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cli
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "runops.ops.setup.install_packages",
        lambda project, *, upgrade: (_ for _ in ()).throw(AssertionError("must not install")),
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.stdin", _Tty("\nemses\nn\n"))
    res = cli("init")
    assert res.code == 0, res.err
    assert "runo update" in res.out
    assert "emses" in load_toml(tmp_path / "runops.toml")["simulators"]


def test_init_install_needs_yes_off_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cli
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    res = cli("init", "emses")
    assert res.code == 2 and "--yes" in res.err
    assert not (tmp_path / "runops.toml").exists()
