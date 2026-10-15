"""Acceptance 10 plus config / manifest validation."""

from __future__ import annotations

from pathlib import Path

import pytest
import tomli_w

from runops import util
from runops.config import load_config
from runops.errors import UsageError
from runops.manifest import Manifest, RunState
from runops.project import Project


def test_manifest_write_is_atomic(project_dir: Path, cli, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    (run_id,) = cli("new", "demo").run_ids()
    m = Project.open(project_dir).resolve_run(run_id)
    before = m.path.read_bytes()

    class Boom(Exception):
        pass

    real_fdopen = util.os.fdopen

    def exploding_fdopen(fd, *args, **kwargs):  # type: ignore[no-untyped-def]
        handle = real_fdopen(fd, *args, **kwargs)
        original_write = handle.write

        def write(text: str) -> int:
            original_write(text[: len(text) // 2])
            raise Boom()

        handle.write = write
        return handle

    monkeypatch.setattr(util.os, "fdopen", exploding_fdopen)
    m.run["why"] = "changed"
    with pytest.raises(Boom):
        m.save()
    monkeypatch.undo()
    assert m.path.read_bytes() == before
    assert not [p for p in m.path.parent.iterdir() if p.name.startswith(".manifest")]


def test_state_transitions(tmp_path: Path) -> None:
    m = Manifest(
        tmp_path / "manifest.toml",
        {"schema": 2, "run": {"id": "R1", "status": "created"}},
    )
    with pytest.raises(UsageError):
        m.set_status(RunState.COMPLETED)
    m.set_status(RunState.SUBMITTED)
    m.set_status(RunState.FAILED)
    m.set_status(RunState.CREATED)


def test_v1_manifest_rejected(tmp_path: Path) -> None:
    path = tmp_path / "manifest.toml"
    path.write_text(tomli_w.dumps({"run": {"id": "R1", "status": "completed"}}))
    with pytest.raises(UsageError, match="migrate-v1"):
        Manifest.load(path)


def test_config_unknown_keys_warn(project_dir: Path) -> None:
    cfg = project_dir / "runops.toml"
    cfg.write_text(cfg.read_text() + "\n[extra]\nfoo = 1\n")
    config = load_config(project_dir)
    assert any("unknown key 'extra'" in w for w in config.warnings)


def test_config_errors(project_dir: Path, cli) -> None:  # type: ignore[no-untyped-def]
    cfg = project_dir / "runops.toml"
    text = cfg.read_text()
    cfg.write_text(text.replace("schema = 2", "schema = 1"))
    res = cli("list")
    assert res.code == 2 and "migrate-v1" in res.err
    cfg.write_text(text.replace('resource_style = "standard"', 'resource_style = "weird"'))
    assert cli("list").code == 2


def test_no_project(tmp_path: Path, cli, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    res = cli("list")
    assert res.code == 2 and "runo init" in res.err
    (tmp_path / "simulators.toml").write_text("")
    res = cli("list")
    assert res.code == 2 and "v1" in res.err


def test_parse_value() -> None:
    assert util.parse_value("3") == 3
    assert util.parse_value("1.5e-6") == 1.5e-6
    assert util.parse_value("true") is True
    assert util.parse_value("[1, 2]") == [1, 2]
    assert util.parse_value("abc") == "abc"
    assert util.parse_value('"3"') == "3"


@pytest.mark.parametrize("supported", [True, False])
def test_move_noreplace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, supported: bool) -> None:
    if not supported:  # Lustre-like filesystem: renameat2 returns EINVAL
        monkeypatch.setattr(util, "_renameat2_noreplace", lambda src, dst: False)
    src = tmp_path / "a"
    src.mkdir()
    (src / "f").write_text("x")
    occupied = tmp_path / "b"
    occupied.mkdir()  # an empty dir would be silently replaced by plain rename(2)
    with pytest.raises(UsageError, match="already exists"):
        util.move_noreplace(src, occupied)
    util.move_noreplace(src, tmp_path / "deep" / "c")
    assert (tmp_path / "deep/c/f").read_text() == "x"
    assert not src.exists()
