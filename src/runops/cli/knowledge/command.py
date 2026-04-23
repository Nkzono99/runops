"""CLI commands for knowledge management."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Optional

import typer

from runops.cli.knowledge.common import _find_root
from runops.cli.knowledge.sources import profile_app, source_app
from runops.core.actions import ActionStatus
from runops.core.actions import add_fact as add_fact_action
from runops.core.actions import save_insight as save_insight_action
from runops.core.knowledge import (
    FACT_TYPES,
    INSIGHT_TYPES,
    list_insights,
    promote_candidate_fact,
    query_facts,
)

knowledge_app = typer.Typer(
    name="knowledge",
    help="Manage project knowledge and external knowledge sources.",
    no_args_is_help=True,
)


@knowledge_app.command("save")
def save(
    name: Annotated[
        str,
        typer.Argument(help="Insight name (used as filename)."),
    ],
    insight_type: Annotated[
        str,
        typer.Option(
            "--type",
            "-t",
            help=("Insight type: constraint, result, analysis, or dependency."),
        ),
    ] = "result",
    simulator: Annotated[
        str,
        typer.Option(
            "--simulator",
            "-s",
            help="Simulator this insight applies to.",
        ),
    ] = "",
    tags: Annotated[
        Optional[str],
        typer.Option(
            "--tags",
            help="Comma-separated tags.",
        ),
    ] = None,
    message: Annotated[
        Optional[str],
        typer.Option(
            "--message",
            "-m",
            help="Insight content (markdown). If omitted, reads from stdin.",
        ),
    ] = None,
) -> None:
    """Save a knowledge insight to .runops/insights/.

    Examples:
      runo knowledge save emses_cfl -t constraint -s emses \\
        -m "dt > 1.5 causes instability with nx=64 grid"
      echo "Survey results..." | runo knowledge save mag_results -t result
    """
    if insight_type not in INSIGHT_TYPES:
        typer.echo(
            f"Invalid type '{insight_type}'. "
            f"Must be one of: {', '.join(sorted(INSIGHT_TYPES))}",
            err=True,
        )
        raise typer.Exit(code=1)

    root = _find_root()

    if message is None:
        typer.echo("Enter insight content (Ctrl+D to finish):")
        import sys

        message = sys.stdin.read()

    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    result = save_insight_action(
        root,
        name=name,
        content=message,
        insight_type=insight_type,
        simulator=simulator,
        tags=tag_list,
    )
    if result.status is not ActionStatus.SUCCESS:
        typer.echo(f"Error: {result.message}", err=True)
        raise typer.Exit(code=1)

    path = Path(result.data["path"])
    typer.echo(f"Saved: {path.relative_to(root)}")


@knowledge_app.command("list")
def list_cmd(
    simulator: Annotated[
        Optional[str],
        typer.Option(
            "--simulator",
            "-s",
            help="Filter by simulator.",
        ),
    ] = None,
    insight_type: Annotated[
        Optional[str],
        typer.Option("--type", "-t", help="Filter by type."),
    ] = None,
    tag: Annotated[
        Optional[str],
        typer.Option("--tag", help="Filter by tag."),
    ] = None,
) -> None:
    """List knowledge insights.

    Examples:
      runo knowledge list
      runo knowledge list -s emses -t constraint
    """
    root = _find_root()

    insights = list_insights(
        root,
        simulator=simulator or "",
        insight_type=insight_type or "",
        tag=tag or "",
    )

    if not insights:
        typer.echo("No insights found.")
        return

    for ins in insights:
        type_badge = f"[{ins.type}]"
        sim_badge = f"({ins.simulator})" if ins.simulator else ""
        tags_str = " " + ", ".join(f"#{t}" for t in ins.tags) if ins.tags else ""
        typer.echo(f"  {ins.name} {type_badge} {sim_badge}{tags_str}")


@knowledge_app.command("show")
def show(
    name: Annotated[
        str,
        typer.Argument(help="Insight name to display."),
    ],
) -> None:
    """Show a specific insight.

    Examples:
      runo knowledge show emses_cfl_limit
    """
    root = _find_root()
    insights_dir = root / ".runops" / "insights"
    path = insights_dir / f"{name}.md"

    if not path.is_file():
        typer.echo(f"Insight not found: {name}", err=True)
        raise typer.Exit(code=1)

    typer.echo(path.read_text(encoding="utf-8"))


@knowledge_app.command("add-fact")
def add_fact(
    claim: Annotated[
        str,
        typer.Argument(help="The knowledge claim (one sentence)."),
    ],
    fact_type: Annotated[
        str,
        typer.Option(
            "--type",
            "-t",
            help="Fact type: observation, constraint, dependency, policy, hypothesis.",
        ),
    ] = "observation",
    simulator: Annotated[
        str,
        typer.Option(
            "--simulator",
            "-s",
            help="Simulator this fact applies to.",
        ),
    ] = "",
    scope_case: Annotated[
        str,
        typer.Option(
            "--scope-case",
            help="Case or case pattern this fact applies to.",
        ),
    ] = "",
    scope_text: Annotated[
        str,
        typer.Option(
            "--scope-text",
            help="Free-text scope description.",
        ),
    ] = "",
    param_name: Annotated[
        str,
        typer.Option(
            "--param-name",
            help="Parameter name this fact is about.",
        ),
    ] = "",
    evidence_kind: Annotated[
        str,
        typer.Option(
            "--evidence-kind",
            help="Evidence kind, e.g. run_observation or calculation.",
        ),
    ] = "",
    evidence_ref: Annotated[
        str,
        typer.Option(
            "--evidence-ref",
            help="Reference to evidence source, e.g. run:R20260330-0001.",
        ),
    ] = "",
    confidence: Annotated[
        str,
        typer.Option(
            "--confidence",
            "-c",
            help="Confidence level: high, medium, low.",
        ),
    ] = "medium",
    source_run: Annotated[
        str,
        typer.Option("--run", help="Source run ID."),
    ] = "",
    tags: Annotated[
        Optional[str],
        typer.Option("--tags", help="Comma-separated tags."),
    ] = None,
    supersedes: Annotated[
        str,
        typer.Option(
            "--supersedes",
            help="ID of an older fact this one replaces.",
        ),
    ] = "",
) -> None:
    """Add a structured fact to .runops/facts.toml.

    Facts are machine-readable knowledge claims with provenance.
    Unlike insights (free-form markdown), facts are designed for
    programmatic use by AI agents.

    Examples:
      runo knowledge add-fact "CFL limit: dt must be < 1.0 for emses" \\
        --type constraint --simulator emses --param-name tmgrid.dt \\
        --scope-text "baseline scan" --confidence high \\
        --evidence-kind run_observation --evidence-ref run:R20260330-0001
    """
    if confidence not in ("high", "medium", "low"):
        typer.echo(
            f"Invalid confidence '{confidence}'. Must be: high, medium, low.",
            err=True,
        )
        raise typer.Exit(code=1)
    if fact_type not in FACT_TYPES:
        typer.echo(
            f"Invalid type '{fact_type}'. "
            f"Must be one of: {', '.join(sorted(FACT_TYPES))}.",
            err=True,
        )
        raise typer.Exit(code=1)

    root = _find_root()
    existing_facts = list(query_facts(root, exclude_superseded=False))
    if supersedes and all(f.id != supersedes for f in existing_facts):
        typer.echo(f"Error: superseded fact not found: {supersedes}", err=True)
        raise typer.Exit(code=1)

    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

    result = add_fact_action(
        root,
        claim=claim,
        fact_type=fact_type,
        simulator=simulator,
        scope_case=scope_case,
        scope_text=scope_text,
        param_name=param_name,
        confidence=confidence,
        source_run=source_run,
        evidence_kind=evidence_kind,
        evidence_ref=evidence_ref,
        tags=tag_list,
        supersedes=supersedes,
    )
    if result.status is not ActionStatus.SUCCESS:
        typer.echo(f"Error: {result.message}", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"Saved fact [{result.data['fact_id']}]: {claim}")


@knowledge_app.command("facts")
def facts_cmd(
    scope: Annotated[
        Optional[str],
        typer.Option("--scope", help="Filter by scope."),
    ] = None,
    tag: Annotated[
        Optional[str],
        typer.Option("--tag", help="Filter by tag."),
    ] = None,
    confidence: Annotated[
        Optional[str],
        typer.Option(
            "--confidence",
            "-c",
            help="Minimum confidence: high, medium, low.",
        ),
    ] = None,
    simulator: Annotated[
        Optional[str],
        typer.Option("--simulator", "-s", help="Filter by simulator."),
    ] = None,
    fact_type: Annotated[
        Optional[str],
        typer.Option("--type", "-t", help="Filter by fact type."),
    ] = None,
    param_name: Annotated[
        Optional[str],
        typer.Option("--param-name", help="Filter by parameter name."),
    ] = None,
    include_superseded: Annotated[
        bool,
        typer.Option(
            "--include-superseded",
            help="Include facts superseded by newer facts.",
        ),
    ] = False,
    local_only: Annotated[
        bool,
        typer.Option(
            "--local-only",
            help="Show only local curated facts and hide imported candidates.",
        ),
    ] = False,
    output_json: Annotated[
        bool,
        typer.Option("--json", help="Emit JSON for machine consumption."),
    ] = False,
) -> None:
    """List structured facts from local and transported knowledge stores.

    Examples:
      runo knowledge facts
      runo knowledge facts --scope emses --confidence high
    """
    if confidence and confidence not in ("high", "medium", "low"):
        typer.echo(
            f"Invalid confidence '{confidence}'. Must be: high, medium, low.",
            err=True,
        )
        raise typer.Exit(code=1)

    root = _find_root()
    facts = query_facts(
        root,
        scope=scope or "",
        tag=tag or "",
        min_confidence=confidence or "",
        simulator=simulator or "",
        fact_type=fact_type or "",
        param_name=param_name or "",
        exclude_superseded=not include_superseded,
        include_candidates=not local_only,
    )

    if output_json:
        if not facts:
            typer.echo("[]")
            return
        typer.echo(
            json.dumps(
                [
                    {
                        "id": f.id,
                        "claim": f.claim,
                        "fact_type": f.fact_type,
                        "simulator": f.simulator,
                        "scope_case": f.scope_case,
                        "scope_text": f.scope_text,
                        "param_name": f.param_name,
                        "confidence": f.confidence,
                        "source_run": f.source_run,
                        "source_project": f.source_project,
                        "evidence_kind": f.evidence_kind,
                        "evidence_ref": f.evidence_ref,
                        "tags": list(f.tags),
                        "supersedes": f.supersedes,
                        "storage": f.storage,
                        "transport_source": f.transport_source,
                        "transport_kind": f.transport_kind,
                        "transport_path": f.transport_path,
                        "upstream_id": f.upstream_id,
                    }
                    for f in facts
                ],
                indent=2,
                ensure_ascii=False,
            )
        )
        return

    if not facts:
        typer.echo("No facts found.")
        return

    for f in facts:
        location = f"[{f.storage}]"
        conf_badge = f"[{f.confidence}]"
        extras: list[str] = []
        if f.fact_type:
            extras.append(f.fact_type)
        if f.simulator:
            extras.append(f.simulator)
        if f.param_name:
            extras.append(f.param_name)
        label = ", ".join(part for part in extras if part)
        label_str = f" [{label}]" if label else ""
        scope_str = f" ({f.scope})" if f.scope else ""
        transport = (
            f" from {f.transport_source}"
            if f.transport_source and f.storage != "local"
            else ""
        )
        typer.echo(
            f"  {f.id} {location}{conf_badge}{label_str}{scope_str}{transport}: "
            f"{f.claim}"
        )


@knowledge_app.command("promote-fact")
def promote_fact(
    fact_id: Annotated[
        str,
        typer.Argument(help="Candidate fact ID to promote, e.g. shared:f004."),
    ],
) -> None:
    """Promote an imported candidate fact into local curated facts.toml."""
    root = _find_root()

    try:
        promoted = promote_candidate_fact(root, fact_id)
    except LookupError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from None
    except RuntimeError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from None

    typer.echo(
        f"Promoted {fact_id} -> {promoted.id}"
        f" ({promoted.fact_type}, {promoted.confidence})"
    )


knowledge_app.add_typer(source_app, name="source")
knowledge_app.add_typer(profile_app, name="profile")
