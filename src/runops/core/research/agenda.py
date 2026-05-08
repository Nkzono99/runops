"""Summaries for the project research agenda."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

AGENDA_RELATIVE_PATH = Path("research") / "agenda.md"
READ_HINT = "Read research/agenda.md before proposing next actions."
FULLWIDTH_COLON = chr(0xFF1A)


def summarize_research_agenda(project_root: Path) -> dict[str, Any]:
    """Summarize the project-level research agenda for agent context.

    Args:
        project_root: Project root directory.

    Returns:
        JSON-serializable summary of ``research/agenda.md``.
    """
    agenda_path = project_root / AGENDA_RELATIVE_PATH
    result: dict[str, Any] = {
        "exists": agenda_path.is_file(),
        "path": AGENDA_RELATIVE_PATH.as_posix(),
    }
    if not agenda_path.is_file():
        return result

    text = agenda_path.read_text(encoding="utf-8")
    sections = _split_h2_sections(text)
    current_decision_lines = _find_section(
        sections,
        "current decision",
        "現在の判断",
    )
    active_questions_lines = _find_section(
        sections,
        "active questions",
        "現在の問い",
    )
    next_actions_lines = _find_section(sections, "next actions", "次の行動")
    paused_lines = _find_section(
        sections,
        "paused",
        "killed",
        "保留",
        "終了",
    )
    change_conditions_lines = _find_section(
        sections,
        "what would change",
        "判断が変わる条件",
    )

    current_decision = _extract_labeled_value(
        current_decision_lines,
        ("decision", "判断"),
    ) or _first_meaningful_value(current_decision_lines)

    result.update(
        {
            "is_template": not _has_meaningful_content(_all_section_lines(sections)),
            "current_decision": current_decision,
            "active_questions_count": _count_items(active_questions_lines),
            "next_actions_count": _count_items(next_actions_lines),
            "paused_killed_count": _count_items(paused_lines),
            "has_change_conditions": _has_meaningful_content(change_conditions_lines),
            "read_hint": READ_HINT,
        }
    )
    return result


def _split_h2_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current_heading = ""
    in_comment = False

    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("<!--"):
            in_comment = "-->" not in stripped
            continue
        if in_comment:
            if "-->" in stripped:
                in_comment = False
            continue
        if stripped.startswith("## "):
            current_heading = _normalize_heading(stripped.removeprefix("## "))
            sections.setdefault(current_heading, [])
            continue
        if current_heading:
            sections[current_heading].append(raw_line)

    return sections


def _normalize_heading(heading: str) -> str:
    return re.sub(r"\s+", " ", heading.strip().casefold())


def _find_section(
    sections: dict[str, list[str]],
    *tokens: str,
) -> list[str]:
    normalized_tokens = tuple(token.casefold() for token in tokens)
    for heading, lines in sections.items():
        if all(token in heading for token in normalized_tokens[:2]):
            return lines
        if any(token in heading for token in normalized_tokens):
            return lines
    return []


def _all_section_lines(sections: dict[str, list[str]]) -> list[str]:
    lines: list[str] = []
    for section_lines in sections.values():
        lines.extend(section_lines)
    return lines


def _count_items(lines: list[str]) -> int:
    groups = _top_level_item_groups(lines)
    if not groups:
        return 1 if _has_meaningful_content(lines) else 0
    return sum(1 for group in groups if _has_meaningful_content(group))


def _top_level_item_groups(lines: list[str]) -> list[list[str]]:
    groups: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        is_top_level_item = indent == 0 and (
            stripped.startswith("- ") or re.match(r"^\d+\.\s+", stripped) is not None
        )
        if is_top_level_item:
            if current:
                groups.append(current)
            current = [line]
        elif current:
            current.append(line)
    if current:
        groups.append(current)
    return groups


def _extract_labeled_value(lines: list[str], labels: tuple[str, ...]) -> str:
    normalized_labels = tuple(label.casefold() for label in labels)
    for line in lines:
        item = _strip_list_marker(line)
        split_item = _split_field(item)
        if split_item is None:
            continue
        label, value = split_item
        if any(token in label.casefold() for token in normalized_labels):
            cleaned = _clean_value(value)
            if cleaned:
                return cleaned
    return ""


def _first_meaningful_value(lines: list[str]) -> str:
    for line in lines:
        value = _meaningful_value(line)
        if value:
            return value
    return ""


def _has_meaningful_content(lines: list[str]) -> bool:
    return any(_meaningful_value(line) for line in lines)


def _meaningful_value(line: str) -> str:
    item = _strip_list_marker(line)
    if not item:
        return ""
    if item.startswith("#"):
        return ""
    if "..." in item:
        return ""
    if re.fullmatch(rf"[A-Z]\d+[:{FULLWIDTH_COLON}]?", item):
        return ""

    split_item = _split_field(item)
    if split_item is not None:
        _label, value = split_item
        return _clean_value(value)

    return _clean_value(item)


def _strip_list_marker(line: str) -> str:
    stripped = line.strip()
    if stripped.startswith("- "):
        return stripped[2:].strip()
    numbered = re.match(r"^\d+\.\s+(.*)$", stripped)
    if numbered is not None:
        return numbered.group(1).strip()
    return stripped


def _split_field(item: str) -> tuple[str, str] | None:
    colon_positions = [
        index for index in (item.find(":"), item.find(FULLWIDTH_COLON)) if index >= 0
    ]
    if not colon_positions:
        return None
    index = min(colon_positions)
    return item[:index].strip(), item[index + 1 :].strip()


def _clean_value(value: str) -> str:
    cleaned = value.strip().strip("*").strip()
    if cleaned.casefold() in {"", "todo", "tbd", "n/a", "none", "yes/no", "未定"}:
        return ""
    return cleaned
