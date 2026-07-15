"""Research workspace command-group composition."""

from __future__ import annotations

import typer

from runops.cli.research import (
    append,
    archive,
    check,
    migrate_legacy,
    new_result,
    restore,
    rotate,
    status,
)

research_app = typer.Typer(
    name="research",
    help="Quantity-bounded research journal and result workspace.",
)
research_app.command("status")(status)
research_app.command("check")(check)
research_app.command("append")(append)
research_app.command("rotate")(rotate)
research_app.command("new-result")(new_result)
research_app.command("archive")(archive)
research_app.command("restore")(restore)
research_app.command("migrate-legacy")(migrate_legacy)

__all__ = ["research_app"]
