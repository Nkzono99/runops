"""Acceptance 7: entry-point adapter with agent context -> skills, lock, update."""

from __future__ import annotations

import shutil
import subprocess
import sys
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
        "runops-analyze",
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
    assert "Work within this project" in agents
    assert "act on them only when the user names them" in agents
    assert "runo cancel --why" in agents
    assert "--superseded-by" in agents
    # runo owns managed runs; jobs outside runs are project scripts, linked by --dependency.
    assert "Create, submit, cancel and retry the runs under `runs/`" in agents
    assert "Run work outside runs as project scripts" in agents
    assert "runo submit RUN --dependency afterok:JOBID" in agents
    skills = project_dir / ".agents/skills"
    status = (skills / "runops-check-status/SKILL.md").read_text()
    assert "`runo list --status failed --status cancelled`. These runs are the candidates" in status
    assert "stopped on purpose" in status
    assert "--superseded-by" in (skills / "runops-create-run/SKILL.md").read_text()
    assert "--superseded-by" in (skills / "runops-tidy/SKILL.md").read_text()
    analyze = (skills / "runops-analyze/SKILL.md").read_text()
    assert "work outside runs: record and link them as AGENTS.md describes" in analyze
    assert (
        "another project's `runs/` are refused"
        in (skills / "runops-reference/SKILL.md").read_text()
    )


def test_package_reference_links_point_at_deployed_references(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cli
) -> None:  # type: ignore[no-untyped-def]
    root = tmp_path / "proj"
    site = root / ".venv/lib/python3.99/site-packages"
    # A module name no other test imports, so its agent context is this project's.
    write_dist(site, "refsim", DUMMY.replace('name = "dummy"', 'name = "refsim"'), "1.0")
    ctx = site / "dummy_context"
    (ctx / "skills/refsim-guide").mkdir(parents=True)
    (ctx / "skills/refsim-guide/SKILL.md").write_text(
        "---\nname: refsim-guide\ndescription: d\n---\n"
        "See [params](../../references/Parameters.md) and `../../docs/missing.md`.\n"
    )
    (ctx / "references").mkdir()
    (ctx / "references/Parameters.md").write_text("# params\n")
    (ctx / "docs").mkdir()
    (ctx / "docs/usage.md").write_text("# usage\n")
    (ctx / "skills/refsim-guide/SKILL.md").write_text(
        (ctx / "skills/refsim-guide/SKILL.md").read_text() + "Also [usage](../../docs/usage.md).\n"
    )
    init_project(root, ["refsim=refsim-pkg"], install=False)
    monkeypatch.chdir(root)
    for base in (".agents/skills", ".claude/skills"):
        guide = root / base / "refsim-guide"
        assert "](../refsim-references/Parameters.md)" in (guide / "SKILL.md").read_text()
        assert (guide / "../refsim-references/Parameters.md").is_file()
        assert "](../refsim-docs/usage.md)" in (guide / "SKILL.md").read_text()
        assert (guide / "../refsim-docs/usage.md").is_file()
        assert "docs documents" in (root / base / "refsim-docs/SKILL.md").read_text().lower()
    res = cli("doctor")
    assert "refsim-guide: links to missing files: ../refsim-docs/missing.md" in res.out
    assert "Parameters.md" not in res.out
    # Bundled reference documents may link into their repository; only SKILL.md counts.
    refs = root / ".agents/skills/refsim-references/Parameters.md"
    refs.write_text("see [src](../src/main.F90)\n")
    assert "main.F90" not in cli("doctor").out


def test_analyze_report_guide_and_example_are_deployed(project_dir: Path, cli) -> None:  # type: ignore[no-untyped-def]
    for base in (".agents/skills", ".claude/skills"):
        skill = project_dir / base / "runops-analyze"
        text = (skill / "SKILL.md").read_text()
        assert "](report-guide.md)" in text and "](example-report/README.md)" in text
        guide = (skill / "report-guide.md").read_text()
        assert "](example-report/README.md)" in guide
        example = skill / "example-report"
        for name in (
            "README.md",
            "report.html",
            "out/fig1_maps.png",
            "out/fig2_dependence.png",
            "out/values.csv",
            "scripts/make_figures.py",
            "scripts/build_html.py",
        ):
            assert (example / name).is_file(), name
    assert "runops-analyze" not in cli("doctor").out  # no broken links reported


def test_example_report_html_is_built_from_its_readme(tmp_path: Path) -> None:
    source = Path(__file__).parents[1] / "src/runops/skills/runops-analyze/example-report"
    topic = tmp_path / "topic"
    shutil.copytree(source, topic)
    build = [sys.executable, str(topic / "scripts/build_html.py")]
    check = subprocess.run([*build, "--check"], capture_output=True, text=True)
    assert check.returncode == 0, check.stdout + check.stderr
    assert "2 image(s) embedded" in check.stdout
    html = (topic / "report.html").read_text(encoding="utf-8")
    readme = (topic / "README.md").read_text(encoding="utf-8")
    assert html.count('src="data:image/png;base64,') == readme.count("](out/fig") == 2
    assert 'src="out/' not in html

    (topic / "README.md").write_text(readme + "\nAn added sentence.\n", encoding="utf-8")
    assert subprocess.run([*build, "--check"], capture_output=True).returncode == 1
    assert subprocess.run(build, capture_output=True).returncode == 0
    assert subprocess.run([*build, "--check"], capture_output=True).returncode == 0
