"""CLI commands for knowledge management."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Optional

import typer

from runops.core.actions import ActionStatus
from runops.core.actions import add_fact as add_fact_action
from runops.core.actions import save_insight as save_insight_action
from runops.core.exceptions import KnowledgeSourceError, SimctlError
from runops.core.knowledge import (
    FACT_TYPES,
    INSIGHT_TYPES,
    list_insights,
    promote_candidate_fact,
    query_facts,
)
from runops.core.knowledge_source import (
    ExternalKnowledgeMount,
    KnowledgeSource,
    collect_external_knowledge,
    import_external_facts,
    import_external_insights,
    load_knowledge_config,
    remove_knowledge_source,
    render_imports,
    save_knowledge_source,
    set_knowledge_source_profiles,
    sync_all_sources,
    sync_source,
    validate_source_structure,
)
from runops.core.project import find_project_root

knowledge_app = typer.Typer(
    name="knowledge",
    help="Manage project knowledge and external knowledge sources.",
    no_args_is_help=True,
)

source_app = typer.Typer(
    name="source",
    help="Manage configured external knowledge sources.",
    no_args_is_help=True,
)

profile_app = typer.Typer(
    name="profile",
    help="Enable or disable profiles on configured knowledge sources.",
    no_args_is_help=True,
)


def _find_root() -> Path:
    """Find project root or exit."""
    try:
        return find_project_root(Path.cwd().resolve())
    except SimctlError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from None


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


def _list_sources(root: Path) -> None:
    """Display external knowledge sources."""
    entries = collect_external_knowledge(root)
    if not entries:
        typer.echo("No knowledge sources configured.")
        return

    _print_external_status(entries, detailed=False)


def _print_external_status(
    entries: list[ExternalKnowledgeMount],
    *,
    detailed: bool,
) -> None:
    """Render configured sources from a shared view."""
    typer.echo("Configured knowledge sources:")
    for entry in entries:
        status = "OK" if entry.exists else "NOT READY"
        location_label = "mount" if entry.kind == "profiles" else "location"
        if detailed:
            long_status = "ready" if entry.exists else "not ready"
            typer.echo(
                f"\n  [{entry.kind}/{entry.source_type}] {entry.name} ({long_status})"
            )
            typer.echo(f"    {location_label}: {entry.display_path}")
            if entry.kind == "profiles":
                enabled = (
                    ", ".join(entry.profiles_enabled)
                    if entry.profiles_enabled
                    else "(none)"
                )
                available = (
                    ", ".join(entry.profiles_available)
                    if entry.profiles_available
                    else "(none)"
                )
                typer.echo(f"    available profiles: {available}")
                typer.echo(f"    enabled profiles: {enabled}")
            continue

        typer.echo(f"  {entry.name} [{entry.kind}/{entry.source_type}] ({status})")
        typer.echo(f"    {location_label}: {entry.display_path}")
        if entry.kind == "profiles":
            enabled = (
                ", ".join(entry.profiles_enabled)
                if entry.profiles_enabled
                else "(none)"
            )
            available = (
                ", ".join(entry.profiles_available)
                if entry.profiles_available
                else "(none)"
            )
            typer.echo(f"    available profiles: {available}")
            typer.echo(f"    enabled profiles:   {enabled}")


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


def sync(
    source_name: Annotated[
        Optional[str],
        typer.Argument(help="Sync only this knowledge source (optional)."),
    ] = None,
    simulator: Annotated[
        Optional[str],
        typer.Option(
            "--simulator",
            "-s",
            help="Sync only insights for this simulator.",
        ),
    ] = None,
) -> None:
    """Sync knowledge sources and import insights from external sources.

    When a source name is given, only that source is synced.
    Otherwise, all knowledge sources are synced, then insights are
    imported from sources with ``kind = "project"`` or ``"insights"``.

    Examples:
      runo knowledge source sync
      runo knowledge source sync shared-lab-knowledge
      runo knowledge source sync -s emses
    """
    root = _find_root()
    config = load_knowledge_config(root)
    if config is None or not config.sources:
        typer.echo("No knowledge sources configured.")
        return

    selected_sources = (
        [source for source in config.sources if source.name == source_name]
        if source_name
        else list(config.sources)
    )
    if source_name and not selected_sources:
        typer.echo(f"Knowledge source not found: {source_name}", err=True)
        raise typer.Exit(code=1)

    typer.echo("Syncing knowledge sources...")
    if source_name:
        for src in selected_sources:
            try:
                status = sync_source(root, src)
                typer.echo(f"  [{src.kind}/{src.source_type}] {src.name}: {status}")
            except KnowledgeSourceError as e:
                typer.echo(f"  [{src.kind}/{src.source_type}] {src.name}: error - {e}")
    else:
        for name, status in sync_all_sources(root, config):
            typer.echo(f"  {name}: {status}")

    if any(source.kind == "profiles" for source in config.sources):
        for source in selected_sources:
            if source.kind != "profiles" or not source.mount:
                continue
            source_dir = root / source.mount
            if not source_dir.is_dir():
                continue
            issues = validate_source_structure(source_dir)
            if issues:
                typer.echo(f"Validation warnings for {source.name}:")
                for issue in issues:
                    typer.echo(f"  - {issue}")
        try:
            render_imports(root, config)
            typer.echo("Rendered imports.md")
        except Exception as e:
            typer.echo(f"Warning: failed to render imports: {e}", err=True)

    importable_sources = [
        source for source in selected_sources if source.kind in {"project", "insights"}
    ]
    if importable_sources:
        typer.echo("Importing transported knowledge from external sources...")
        for source in importable_sources:
            typer.echo(f"  [{source.kind}/{source.source_type}] {source.name}")
        imported, skipped = import_external_insights(
            root,
            importable_sources,
            simulator=simulator or "",
        )
        synced_sources, imported_facts = import_external_facts(
            root,
            importable_sources,
            simulator=simulator or "",
        )
        typer.echo(f"  Insights imported: {imported}, skipped: {skipped}")
        typer.echo(
            f"  Candidate facts synced: {imported_facts} "
            f"across {synced_sources} source(s)"
        )


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


# ---------- Knowledge source commands ----------


def attach(
    source_type: Annotated[
        str,
        typer.Argument(help="Source type: git or path."),
    ],
    name: Annotated[
        str,
        typer.Argument(help="Source name (identifier)."),
    ],
    url_or_path: Annotated[
        str,
        typer.Argument(help="Git URL or filesystem path."),
    ],
    ref: Annotated[
        str,
        typer.Option("--ref", help="Git ref to checkout (git sources only)."),
    ] = "main",
    kind: Annotated[
        str,
        typer.Option(
            "--kind",
            help="Source kind: profiles, project, or insights.",
        ),
    ] = "profiles",
    mount: Annotated[
        Optional[str],
        typer.Option("--mount", help="Override mount path."),
    ] = None,
    profiles: Annotated[
        Optional[str],
        typer.Option("--profiles", help="Comma-separated profile names to enable."),
    ] = None,
    no_sync: Annotated[
        bool,
        typer.Option("--no-sync", help="Skip initial sync."),
    ] = False,
) -> None:
    """Attach an external knowledge source to this project.

    Examples:
      runo knowledge source attach git shared-kb git@github.com:lab/kb.git
      runo knowledge source attach path old-project ../old-project --kind project
      runo knowledge source attach git lab-kb \\
        https://github.com/lab/kb.git --profiles common,emses
    """
    if source_type not in ("git", "path"):
        msg = f"Invalid source type: {source_type}. Must be 'git' or 'path'."
        typer.echo(msg, err=True)
        raise typer.Exit(code=1)
    if kind not in ("profiles", "project", "insights"):
        msg = (
            f"Invalid source kind: {kind}. "
            "Must be 'profiles', 'project', or 'insights'."
        )
        typer.echo(msg, err=True)
        raise typer.Exit(code=1)
    if kind != "profiles" and profiles:
        typer.echo(
            "Error: --profiles is only valid for sources with --kind profiles.",
            err=True,
        )
        raise typer.Exit(code=1)
    if source_type == "path" and kind != "profiles" and mount:
        typer.echo(
            "Error: --mount is not used for path sources with --kind project|insights.",
            err=True,
        )
        raise typer.Exit(code=1)

    root = _find_root()
    mount_path = mount or (
        f"refs/knowledge/{name}" if source_type == "git" or kind == "profiles" else ""
    )
    profile_list = (
        [p.strip() for p in profiles.split(",") if p.strip()] if profiles else []
    )

    source = KnowledgeSource(
        name=name,
        source_type=source_type,
        kind=kind,
        url=url_or_path,
        ref=ref if source_type == "git" else "main",
        mount=mount_path,
        profiles=profile_list,
    )

    try:
        save_knowledge_source(root, source)
    except KnowledgeSourceError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from None

    typer.echo(f"Attached [{kind}/{source_type}] {name}: {url_or_path}")
    if mount_path:
        typer.echo(f"  mount: {mount_path}")
    if kind == "profiles" and profile_list:
        typer.echo(f"  profiles: {', '.join(profile_list)}")

    if not no_sync:
        typer.echo("Syncing...")
        try:
            status = sync_source(root, source)
            typer.echo(f"  {name}: {status}")
        except KnowledgeSourceError as e:
            typer.echo(f"  Sync failed: {e}", err=True)

        # Validate profile sources after they are synced locally.
        source_dir = root / mount_path if mount_path else None
        if kind == "profiles" and source_dir and source_dir.is_dir():
            issues = validate_source_structure(source_dir)
            if issues:
                typer.echo("Validation warnings:")
                for issue in issues:
                    typer.echo(f"  - {issue}")


def detach(
    name: Annotated[
        str,
        typer.Argument(help="Source name to remove."),
    ],
    keep_files: Annotated[
        bool,
        typer.Option("--keep-files", help="Keep mounted files."),
    ] = False,
) -> None:
    """Detach a knowledge source from this project.

    Examples:
      runo knowledge source detach shared-kb
      runo knowledge source detach shared-kb --keep-files
    """
    root = _find_root()

    # Find mount path before removing
    config = load_knowledge_config(root)
    mount_path: Path | None = None
    if config:
        for src in config.sources:
            if src.name == name:
                mount_path = root / src.mount
                break

    try:
        removed = remove_knowledge_source(root, name)
    except KnowledgeSourceError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from None

    if not removed:
        typer.echo(f"Source not found: {name}", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"Detached: {name}")

    if not keep_files and mount_path and mount_path.exists():
        import shutil

        if mount_path.is_symlink():
            mount_path.unlink()
        else:
            shutil.rmtree(mount_path)
        typer.echo(f"  Removed: {mount_path.relative_to(root)}")


def render() -> None:
    """Render imports.md from enabled knowledge profiles.

    Generates .runops/knowledge/enabled/imports.md containing
    @import directives for each enabled profile.

    Examples:
      runo knowledge source render
    """
    root = _find_root()
    config = load_knowledge_config(root)

    if config is None:
        typer.echo("No [knowledge] section in runops.toml.")
        raise typer.Exit(code=1)

    imports_path = render_imports(root, config)
    rel = imports_path.relative_to(root)
    typer.echo(f"Rendered: {rel}")

    content = imports_path.read_text(encoding="utf-8").strip()
    if content:
        for line in content.split("\n"):
            if line.startswith("@"):
                typer.echo(f"  {line}")


def status_cmd() -> None:
    """Show knowledge integration status.

    Examples:
      runo knowledge source status
    """
    root = _find_root()
    config = load_knowledge_config(root)
    external_entries = collect_external_knowledge(root)

    if config is None:
        typer.echo("Knowledge integration: not configured")
        typer.echo(
            "  Add [knowledge] section to runops.toml"
            " or use 'runo knowledge source attach'."
        )
    else:
        status = "enabled" if config.enabled else "disabled"
        typer.echo(f"Knowledge integration: {status}")
        typer.echo(f"  mount_dir: {config.mount_dir}")
        typer.echo(f"  derived_dir: {config.derived_dir}")
        typer.echo(f"  sources: {len(config.sources)}")

    if external_entries:
        _print_external_status(external_entries, detailed=True)

    if config is None:
        return

    if not any(source.kind == "profiles" for source in config.sources):
        return

    # Check imports.md status
    imports_path = root / config.derived_dir / "enabled" / "imports.md"
    if imports_path.is_file():
        typer.echo(f"\n  imports.md: {imports_path.relative_to(root)} (exists)")
    else:
        typer.echo("\n  imports.md: not generated (run 'runo knowledge source render')")


def _validate_requested_profiles(
    root: Path,
    source_name: str,
    requested_profiles: list[str],
) -> None:
    config = load_knowledge_config(root)
    if config is None:
        return

    source = next((src for src in config.sources if src.name == source_name), None)
    if source is None or source.kind != "profiles":
        return

    mount_path = root / source.mount if source.mount else None
    if mount_path is None or not mount_path.is_dir():
        return

    available: set[str] = set()
    for entry in collect_external_knowledge(root):
        if entry.name == source_name:
            available = set(entry.profiles_available)
            break

    missing = [profile for profile in requested_profiles if profile not in available]
    if missing:
        typer.echo(
            f"Error: unknown profiles for {source_name}: {', '.join(missing)}",
            err=True,
        )
        raise typer.Exit(code=1)


@profile_app.command("enable")
def profile_enable(
    source_name: Annotated[
        str,
        typer.Argument(help="Knowledge source name."),
    ],
    profile_names: Annotated[
        list[str],
        typer.Argument(help="One or more profile names to enable."),
    ],
) -> None:
    """Enable one or more profiles for a configured source."""
    root = _find_root()
    _validate_requested_profiles(root, source_name, profile_names)

    try:
        updated = set_knowledge_source_profiles(root, source_name, enable=profile_names)
    except KnowledgeSourceError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from None

    typer.echo(
        f"Enabled profiles for {source_name}: "
        f"{', '.join(updated.profiles) if updated.profiles else '(none)'}"
    )

    config = load_knowledge_config(root)
    if config is not None:
        imports_path = render_imports(root, config)
        typer.echo(f"Rendered: {imports_path.relative_to(root)}")


@profile_app.command("disable")
def profile_disable(
    source_name: Annotated[
        str,
        typer.Argument(help="Knowledge source name."),
    ],
    profile_names: Annotated[
        list[str],
        typer.Argument(help="One or more profile names to disable."),
    ],
) -> None:
    """Disable one or more profiles for a configured source."""
    root = _find_root()

    try:
        updated = set_knowledge_source_profiles(
            root,
            source_name,
            disable=profile_names,
        )
    except KnowledgeSourceError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from None

    typer.echo(
        f"Enabled profiles for {source_name}: "
        f"{', '.join(updated.profiles) if updated.profiles else '(none)'}"
    )

    config = load_knowledge_config(root)
    if config is not None:
        imports_path = render_imports(root, config)
        typer.echo(f"Rendered: {imports_path.relative_to(root)}")


@source_app.command("list")
def source_list_cmd() -> None:
    """Show configured external knowledge sources."""
    root = _find_root()
    _list_sources(root)


source_app.command("attach")(attach)
source_app.command("detach")(detach)
source_app.command("sync")(sync)
source_app.command("render")(render)
source_app.command("status")(status_cmd)

knowledge_app.add_typer(source_app, name="source")
knowledge_app.add_typer(profile_app, name="profile")
