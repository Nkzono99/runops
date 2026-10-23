"""Agent context deployment into ``.agents/skills`` and ``.claude/skills`` (SPEC §8.2, §8.3)."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

from runops import __version__
from runops.adapters.registry import optional
from runops.errors import RunopsError
from runops.ops.common import sim_context
from runops.project import Project
from runops.util import dump_toml, hash_tree, load_toml, tomllib

MARKER = ".managed-by-runops"
SKILL_ROOTS = (".agents/skills", ".claude/skills")
LOCK_FILE = "skills.lock"


@dataclass
class SkillSource:
    source: str  # "runops" or adapter name
    version: str
    skills: dict[str, Path]  # target dir name -> source dir


@dataclass
class DeployReport:
    deployed: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def runops_source() -> SkillSource:
    root = Path(str(resources.files("runops") / "skills"))
    skills = {p.name: p for p in sorted(root.iterdir()) if (p / "SKILL.md").is_file()}
    return SkillSource("runops", __version__, skills)


def adapter_sources(project: Project, warnings: list[str]) -> list[SkillSource]:
    sources: list[SkillSource] = []
    seen: set[str] = set()
    for sim in project.config.simulators.values():
        if sim.adapter in seen:
            continue
        seen.add(sim.adapter)
        try:
            ctx = sim_context(project, sim.name)
        except RunopsError as exc:
            warnings.append(f"skills for {sim.adapter!r} skipped: {exc}")
            continue
        directory = optional(ctx.adapter, "agent_context_dir", None)
        if not directory:
            continue
        directory = Path(directory)
        skills: dict[str, Path] = {}
        if (directory / "skills").is_dir():
            for path in sorted((directory / "skills").iterdir()):
                if not (path / "SKILL.md").is_file():
                    continue
                if path.name.startswith("runops-"):
                    warnings.append(
                        f"{sim.adapter}: skill {path.name!r} uses the reserved "
                        "runops- prefix; skipped"
                    )
                    continue
                skills[path.name] = path  # the package owns its skill namespace
        if (directory / "references").is_dir():
            skills[f"{sim.adapter}-references"] = directory / "references"
        version = ctx.resolved.version or "local"
        sources.append(SkillSource(sim.adapter, version, skills))
    return sources


def deploy(project: Project, sources: list[SkillSource]) -> DeployReport:
    report = DeployReport()
    lock_entries: list[dict[str, Any]] = []
    for source in sources:
        names = set(source.skills)
        for root_rel in SKILL_ROOTS:
            root = project.root / root_rel
            root.mkdir(parents=True, exist_ok=True)
            for existing in sorted(root.iterdir()):
                marker = existing / MARKER
                if existing.name in names or not marker.is_file():
                    continue
                if _marker_source(marker) == source.source:
                    shutil.rmtree(existing)
                    report.removed.append(f"{root_rel}/{existing.name}")
        for name, src in source.skills.items():
            for root_rel in SKILL_ROOTS:
                target = project.root / root_rel / name
                if target.exists() and not (target / MARKER).is_file():
                    report.warnings.append(
                        f"{root_rel}/{name} exists and is not managed by runops; left untouched"
                    )
                    continue
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(src, target)
                if not (target / "SKILL.md").is_file():
                    _write_reference_index(target, source.source)
                elif f"{source.source}-references" in source.skills:
                    _point_at_deployed_references(target, source.source)
                (target / MARKER).write_text(
                    f'source = "{source.source}"\nversion = "{source.version}"\n',
                    encoding="utf-8",
                )
                report.deployed.append(f"{root_rel}/{name}")
            lock_entries.append(
                {
                    "source": source.source,
                    "version": source.version,
                    "name": name,
                    "hash": hash_tree(src),
                }
            )
    dump_toml(project.state_dir / LOCK_FILE, {"skills": lock_entries})
    return report


def read_lock(project: Project) -> list[dict[str, Any]]:
    try:
        data = load_toml(project.state_dir / LOCK_FILE)
    except (FileNotFoundError, tomllib.TOMLDecodeError):
        return []
    skills = data.get("skills", [])
    return list(skills) if isinstance(skills, list) else []


def stale_runops_skills(project: Project) -> str:
    """Warning when the deployed runops skills predate the installed runops; else ``""``.

    Cheap (reads ``skills.lock`` only), so ``runo context`` can call it on every start.
    """
    deployed = {str(e.get("version")) for e in read_lock(project) if e.get("source") == "runops"}
    if not deployed or deployed == {__version__}:
        return ""
    return (
        f"runops skills are from {', '.join(sorted(deployed))}, installed is {__version__}; "
        "run `runo update --skills-only`"
    )


def deployed_skill_names(project: Project) -> list[str]:
    root = project.root / SKILL_ROOTS[0]
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if (p / "SKILL.md").is_file())


def _marker_source(marker: Path) -> str:
    try:
        return str(load_toml(marker).get("source", ""))
    except (OSError, tomllib.TOMLDecodeError):
        return ""


# A package skill sits in <agent_context>/skills/<name>/ and often reaches its documents as
# ../../references/; once deployed, the documents live in the sibling <adapter>-references/.
_PACKAGE_REFERENCES = "../../references/"


def _point_at_deployed_references(target: Path, source: str) -> None:
    for md in target.rglob("*.md"):
        text = md.read_text(encoding="utf-8")
        if _PACKAGE_REFERENCES in text:
            md.write_text(
                text.replace(_PACKAGE_REFERENCES, f"../{source}-references/"), encoding="utf-8"
            )


_LINK = re.compile(r"\]\(([^)\s]+)\)|`(\.\.?/[^`\s]+)`")


def broken_skill_links(project: Project) -> dict[str, list[str]]:
    """Relative links in deployed SKILL.md files that point at nothing: {skill: [link, ...]}.

    Only SKILL.md is checked: bundled reference documents are copies of repository docs
    whose links into the repository are expected to be absent.
    """
    root = project.root / SKILL_ROOTS[0]
    broken: dict[str, list[str]] = {}
    if not root.is_dir():
        return broken
    for skill in sorted(root.iterdir()):
        md = skill / "SKILL.md"
        if md.is_file():
            for match in _LINK.finditer(md.read_text(encoding="utf-8")):
                link = (match.group(1) or match.group(2)).split("#", 1)[0]
                if not link or "://" in link or link.startswith(("mailto:", "/")):
                    continue
                if not (md.parent / link).exists():
                    broken.setdefault(skill.name, []).append(link)
    return broken


def _write_reference_index(target: Path, source: str) -> None:
    files = sorted(p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file())
    lines = [
        "---",
        f"name: {target.name}",
        f"description: Reference documents for the {source} simulator. "
        "Read the file that matches the question.",
        "---",
        "",
        f"# {source} references",
        "",
        *[f"- [{name}]({name})" for name in files],
        "",
    ]
    (target / "SKILL.md").write_text("\n".join(lines), encoding="utf-8")
