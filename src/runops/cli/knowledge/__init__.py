"""Knowledge CLI facade."""

from __future__ import annotations

from pathlib import Path as Path

from runops.cli.knowledge.command import add_fact as add_fact
from runops.cli.knowledge.command import facts_cmd as facts_cmd
from runops.cli.knowledge.command import knowledge_app as knowledge_app
from runops.cli.knowledge.command import list_cmd as list_cmd
from runops.cli.knowledge.command import promote_fact as promote_fact
from runops.cli.knowledge.command import save as save
from runops.cli.knowledge.command import show as show
from runops.cli.knowledge.common import _find_root as _find_root
from runops.cli.knowledge.sources import attach as attach
from runops.cli.knowledge.sources import detach as detach
from runops.cli.knowledge.sources import profile_app as profile_app
from runops.cli.knowledge.sources import profile_disable as profile_disable
from runops.cli.knowledge.sources import profile_enable as profile_enable
from runops.cli.knowledge.sources import render as render
from runops.cli.knowledge.sources import source_app as source_app
from runops.cli.knowledge.sources import source_list_cmd as source_list_cmd
from runops.cli.knowledge.sources import status_cmd as status_cmd
from runops.cli.knowledge.sources import sync as sync

__all__ = [
    "Path",
    "_find_root",
    "add_fact",
    "attach",
    "detach",
    "facts_cmd",
    "knowledge_app",
    "list_cmd",
    "profile_app",
    "profile_disable",
    "profile_enable",
    "promote_fact",
    "render",
    "save",
    "show",
    "source_app",
    "source_list_cmd",
    "status_cmd",
    "sync",
]
