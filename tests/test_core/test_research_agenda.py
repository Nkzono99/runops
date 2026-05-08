"""Tests for research agenda summaries."""

from __future__ import annotations

from pathlib import Path

from runops.core.research import summarize_research_agenda


def test_summarize_research_agenda_reports_missing_file(tmp_path: Path) -> None:
    summary = summarize_research_agenda(tmp_path)

    assert summary == {"exists": False, "path": "research/agenda.md"}


def test_summarize_research_agenda_ignores_template_placeholders(
    tmp_path: Path,
) -> None:
    agenda = tmp_path / "research" / "agenda.md"
    agenda.parent.mkdir(parents=True)
    agenda.write_text(
        "# Research Agenda\n\n"
        "## Current Decision / 現在の判断\n\n"
        "- 判断 (Decision):\n"
        "- 理由 (Rationale):\n\n"
        "## What Would Change Our Mind / 判断が変わる条件\n\n"
        "- もし ... が観察されたら、... と判断を変える。\n\n"
        "## Next Actions / 次の行動\n\n"
        "1. 行動 (Action):\n"
        "   - Human gate: yes/no\n",
        encoding="utf-8",
    )

    summary = summarize_research_agenda(tmp_path)

    assert summary["exists"] is True
    assert summary["is_template"] is True
    assert summary["current_decision"] == ""
    assert summary["active_questions_count"] == 0
    assert summary["next_actions_count"] == 0
    assert summary["paused_killed_count"] == 0
    assert summary["has_change_conditions"] is False


def test_summarize_research_agenda_counts_filled_sections(tmp_path: Path) -> None:
    agenda = tmp_path / "research" / "agenda.md"
    agenda.parent.mkdir(parents=True)
    agenda.write_text(
        "# Research Agenda\n\n"
        "## Current Decision / 現在の判断\n\n"
        "- 判断 (Decision): "
        "v4.11 smoke の完了確認までは controlled rerun に進まない。\n"
        "- 理由 (Rationale): current evidence が v4.10 系に偏っているため。\n\n"
        "## What Would Change Our Mind / 判断が変わる条件\n\n"
        "- v4.11 smoke が完了して同じ構造なら、controlled rerun に進む。\n\n"
        "## Active Questions / 現在の問い\n\n"
        "- Q1:\n"
        "  - 問い (Question): v4.11 で vertical_hole 構造は変わるか。\n"
        "- Q2:\n"
        "  - 問い (Question):\n\n"
        "## Next Actions / 次の行動\n\n"
        "1. 行動 (Action): v4.11 smoke run を sync する。\n"
        "   - Human gate: no\n"
        "2. 行動 (Action): controlled rerun の proposal を作る。\n"
        "   - Human gate: yes\n\n"
        "## Paused / Killed / 保留・終了した方向\n\n"
        "- 話題 (Topic): boundary block mismatch 仮説\n"
        "  - 状態 (Status): paused\n",
        encoding="utf-8",
    )

    summary = summarize_research_agenda(tmp_path)

    assert summary["exists"] is True
    assert summary["is_template"] is False
    assert (
        summary["current_decision"]
        == "v4.11 smoke の完了確認までは controlled rerun に進まない。"
    )
    assert summary["active_questions_count"] == 1
    assert summary["next_actions_count"] == 2
    assert summary["paused_killed_count"] == 1
    assert summary["has_change_conditions"] is True
    assert (
        summary["read_hint"] == "Read research/agenda.md before proposing next actions."
    )
