"""The development harness stays consistent: one source per skill, valid references."""

from __future__ import annotations

import re
from pathlib import Path

from runops.util import tomllib

ROOT = Path(__file__).parents[1]
CANONICAL = ROOT / ".agents" / "skills"
FRONT_RE = re.compile(r"^---\n(.*?)\n---\n", re.S)
PATH_RE = re.compile(r"`((?:src/runops|tests|docs|\.agents/skills|\.claude/rules)/[\w./-]+)`")


def _front(path: Path) -> str:
    match = FRONT_RE.match(path.read_text(encoding="utf-8"))
    assert match, f"{path} has no frontmatter"
    return match.group(1)


def _skills() -> list[str]:
    return sorted(p.name for p in CANONICAL.iterdir() if (p / "SKILL.md").is_file())


def test_canonical_skills_have_matching_names() -> None:
    for name in _skills():
        front = _front(CANONICAL / name / "SKILL.md")
        assert f"name: {name}" in front
        assert "description:" in front


def test_claude_skills_are_entry_points() -> None:
    claude = ROOT / ".claude" / "skills"
    for path in claude.glob("*/SKILL.md"):  # entry points must have a source
        if ".agents/skills/" in path.read_text(encoding="utf-8"):
            assert (CANONICAL / path.parent.name / "SKILL.md").is_file(), path
    for name in _skills():
        entry = claude / name / "SKILL.md"
        assert _front(entry) == _front(CANONICAL / name / "SKILL.md")
        assert f".agents/skills/{name}/SKILL.md" in entry.read_text(encoding="utf-8")
        assert [p.name for p in (claude / name).iterdir()] == ["SKILL.md"]


def test_agents_point_to_canonical_skills() -> None:
    for path in (ROOT / ".claude" / "agents").glob("*.md"):
        assert (CANONICAL / path.stem / "SKILL.md").is_file()
        assert f".agents/skills/{path.stem}/SKILL.md" in path.read_text(encoding="utf-8")
    for path in (ROOT / ".codex" / "agents").glob("*.toml"):
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        assert data["name"] == path.stem
        assert f".agents/skills/{path.stem}/SKILL.md" in data["developer_instructions"]


def test_project_docs() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert len(agents.splitlines()) <= 100
    for name in _skills():
        assert f"`{name}`" in agents, name
    for link in re.findall(r"\]\(([^)#]+)\)", agents):
        assert (ROOT / link).exists(), link
    assert (ROOT / "CLAUDE.md").read_text(encoding="utf-8") == "@AGENTS.md\n"
    assert sorted(p.name for p in (ROOT / ".codex" / "rules").iterdir()) == ["runops.rules"]


def test_referenced_paths_exist() -> None:
    files = [
        *CANONICAL.glob("*/SKILL.md"),
        *(ROOT / ".claude" / "rules").glob("*.md"),
        ROOT / "AGENTS.md",
    ]
    for path in files:
        for ref in PATH_RE.findall(path.read_text(encoding="utf-8")):
            if any(ch in ref for ch in "*<"):
                continue
            assert (ROOT / ref.rstrip("/.")).exists(), f"{path.relative_to(ROOT)}: {ref}"
