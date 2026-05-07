"""Import external insights and facts from configured knowledge sources."""

from __future__ import annotations

import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

try:
    import tomli_w
except ImportError:
    tomli_w = None  # type: ignore[assignment]

from runops.core.models.knowledge_source import KnowledgeSource

from .paths import (
    fact_source_file,
    insight_source_dir,
    namespaced_insight_filename,
    safe_namespace,
    source_root,
)


def import_external_insights(
    project_root: Path,
    sources: list[KnowledgeSource],
    *,
    simulator: str = "",
) -> tuple[int, int]:
    """Import insights from configured external sources."""
    from runops.core.knowledge import get_insights_dir, parse_insight

    our_insights_dir = get_insights_dir(project_root)
    imported = 0
    skipped = 0

    for source in sources:
        source_dir = insight_source_dir(project_root, source)
        if source_dir is None or not source_dir.is_dir():
            continue

        for md_file in sorted(source_dir.glob("*.md")):
            insight = parse_insight(md_file)
            if insight is None:
                continue
            if simulator and insight.simulator != simulator:
                continue

            dest = our_insights_dir / namespaced_insight_filename(source, md_file.stem)
            if dest.exists():
                skipped += 1
                continue

            shutil.copy2(md_file, dest)
            imported += 1

    return imported, skipped


def import_external_facts(
    project_root: Path,
    sources: list[KnowledgeSource],
    *,
    simulator: str = "",
) -> tuple[int, int]:
    """Sync structured facts from external sources into candidate transport."""
    from runops.core.knowledge import get_candidate_facts_dir

    if tomli_w is None:
        msg = "tomli_w is required to write candidate fact transport"
        raise RuntimeError(msg)

    candidate_dir = get_candidate_facts_dir(project_root)
    synced_sources = 0
    total_facts = 0

    for source in sources:
        facts_file = fact_source_file(project_root, source)
        dest = candidate_dir / f"{safe_namespace(source.name)}.toml"
        if facts_file is None:
            if dest.exists():
                dest.unlink()
            continue

        with open(facts_file, "rb") as f:
            raw = tomllib.load(f)

        selected: list[dict[str, Any]] = []
        for item in raw.get("facts", []):
            if not isinstance(item, dict):
                continue
            item_simulator = str(item.get("simulator", "")).strip()
            if simulator and item_simulator not in {"", simulator}:
                continue
            selected.append(dict(item))

        if not selected:
            if dest.exists():
                dest.unlink()
            synced_sources += 1
            continue

        payload = {
            "transport": {
                "source": source.name,
                "kind": source.kind,
                "source_path": str(source_root(project_root, source)),
                "imported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            },
            "facts": selected,
        }
        with open(dest, "wb") as f:
            tomli_w.dump(payload, f)

        synced_sources += 1
        total_facts += len(selected)

    return synced_sources, total_facts
