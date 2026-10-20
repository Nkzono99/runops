"""Acceptance 7: entry-point adapter with agent context -> skills, lock, update."""

from __future__ import annotations

from pathlib import Path

import pytest

from runops.ops.setup import init_project
from runops.util import load_toml

from .test_adapters import write_dist

DUMMY = """
from pathlib import Path

HERE = Path(__file__).parent / "dummy_context"


class Adapter:
    name = "dummy"

    def render_inputs(self, params, run_dir):
        return []

    def build_command(self, runtime, run_dir):
        return ["dummy-exe"]

    def detect_status(self, run_dir):
        return "unknown"

    def agent_context_dir(self):
        return HERE
"""


def _install_dummy(root: Path, version: str, skill_text: str) -> Path:
    site = root / ".venv/lib/python3.99/site-packages"
    for old in site.glob("dummy_runops-*.dist-info"):
        for f in old.iterdir():
            f.unlink()
        old.rmdir()
    write_dist(site, "dummy", DUMMY, version)
    ctx = site / "dummy_context"
    (ctx / "skills/dummy-input-review").mkdir(parents=True, exist_ok=True)
    (ctx / "skills/dummy-input-review/SKILL.md").write_text(skill_text)
    (ctx / "skills/runops-evil").mkdir(exist_ok=True)
    (ctx / "skills/runops-evil/SKILL.md").write_text("x")
    (ctx / "references").mkdir(exist_ok=True)
    (ctx / "references/Parameters.md").write_text("# params\n")
    return site


def test_init_deploys_adapter_skills_and_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cli
) -> None:  # type: ignore[no-untyped-def]
    root = tmp_path / "proj"
    root.mkdir()
    _install_dummy(root, "1.0", "---\nname: input-review\ndescription: v1\n---\nv1\n")
    init_project(root, ["dummy=dummy-pkg"], install=False)
    monkeypatch.chdir(root)

    for base in (".agents/skills", ".claude/skills"):
        skill = root / base / "dummy-input-review"
        assert (skill / "SKILL.md").read_text().endswith("v1\n")
        assert (skill / ".managed-by-runops").is_file()
        refs = root / base / "dummy-references"
        assert (refs / "Parameters.md").is_file()
        assert "Parameters.md" in (refs / "SKILL.md").read_text()
        assert (root / base / "runops-create-run/SKILL.md").is_file()
        assert not (root / base / "runops-evil").exists()

    lock = load_toml(root / ".runops/skills.lock")["skills"]
    dummy = [e for e in lock if e["source"] == "dummy"]
    assert {e["name"] for e in dummy} == {"dummy-input-review", "dummy-references"}
    assert {e["version"] for e in dummy} == {"1.0"}
    agents = (root / "AGENTS.md").read_text()
    assert "`dummy-input-review`" in agents and "<!-- runops:begin -->" in agents

    # user-owned skill dir with a clashing name stays untouched; user text outside block kept
    (root / ".claude/skills/dummy-references/.managed-by-runops").unlink()
    (root / "AGENTS.md").write_text(agents + "\n## My notes\nkeep me\n")

    _install_dummy(root, "1.1", "---\nname: input-review\ndescription: v2\n---\nv2\n")
    res = cli("doctor")
    assert "run `runo update --skills-only`" in res.out
    assert "resolved via entry-point" in res.out

    res = cli("update", "--skills-only")
    assert res.code == 0, res.err
    assert "not managed by runops" in res.err
    assert (root / ".agents/skills/dummy-input-review/SKILL.md").read_text().endswith("v2\n")
    assert (root / ".claude/skills/dummy-input-review/SKILL.md").read_text().endswith("v2\n")
    assert not (root / ".claude/skills/dummy-references/.managed-by-runops").exists()
    lock = load_toml(root / ".runops/skills.lock")["skills"]
    assert {e["version"] for e in lock if e["source"] == "dummy"} == {"1.1"}
    assert "keep me" in (root / "AGENTS.md").read_text()
    assert "run `runo update --skills-only`" not in cli("doctor").out


def test_runops_skills_are_short() -> None:
    root = Path(__file__).parents[1] / "src/runops/skills"
    names = sorted(p.name for p in root.iterdir() if p.is_dir())
    assert names == [
        "runops-check-status",
        "runops-create-run",
        "runops-maintain",
        "runops-reference",
        "runops-tidy",
    ]
    for name in names:
        text = (root / name / "SKILL.md").read_text()
        assert text.startswith("---\nname: " + name)
        assert len(text.splitlines()) <= 60


def test_agents_md_short(project_dir: Path) -> None:
    assert len((project_dir / "AGENTS.md").read_text().splitlines()) <= 120
    assert (project_dir / "CLAUDE.md").read_text() == "@AGENTS.md\n"


def test_harness_and_skills_scope_actions_to_this_project(project_dir: Path) -> None:
    agents = (project_dir / "AGENTS.md").read_text()
    assert "Scope is this project" in agents
    assert "never a target list" in agents
    assert "--superseded-by" in agents
    skills = project_dir / ".agents/skills"
    status = (skills / "runops-check-status/SKILL.md").read_text()
    assert "starts from this project's runs" in status
    assert "account-wide `squeue` / `sacct` are not" in status
    assert "--superseded-by" in (skills / "runops-create-run/SKILL.md").read_text()
    assert "--superseded-by" in (skills / "runops-tidy/SKILL.md").read_text()
    assert (
        "another project's `runs/` are refused"
        in (skills / "runops-reference/SKILL.md").read_text()
    )
