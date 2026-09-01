"""CLI command for creating new case templates."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Optional

import typer

from runops.adapters.base import SimulatorAdapter
from runops.core.exceptions import ProjectConfigError, ProjectNotFoundError
from runops.core.project import find_project_root, load_project

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


def _detect_simulator(cwd: Path) -> str | None:
    """Detect simulator name from cwd path.

    If cwd is under cases/<simulator>/, return the simulator name.
    """
    parts = cwd.parts
    for i, part in enumerate(parts):
        if part == "cases" and i + 1 < len(parts):
            return parts[i + 1]
    return None


def _warn_fallback(message: str) -> None:
    """Emit a warning when falling back to safe defaults."""
    typer.echo(f"  Warning: {message}", err=True)


def _try_find_project_root(start: Path) -> Path | None:
    """Return the project root when inside a project, else ``None``."""
    try:
        return find_project_root(start)
    except ProjectNotFoundError:
        return None


def _load_case_defaults(project_root: Path) -> tuple[str, str]:
    """Load launcher and site defaults, warning when config is invalid."""
    default_launcher = "srun"
    site_resource_style = "standard"

    from runops.core.site import load_site_profile

    try:
        project = load_project(project_root)
    except ProjectConfigError as exc:
        _warn_fallback(
            "failed to read project config "
            f"({exc}); using launcher '{default_launcher}'"
        )
    else:
        launcher_names = list(project.launchers.keys())
        if launcher_names:
            default_launcher = launcher_names[0]

    try:
        site = load_site_profile(project_root)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        _warn_fallback(
            f"failed to read site profile ({exc}); using '{site_resource_style}' "
            "resource style"
        )
    else:
        site_resource_style = site.resource_style

    return default_launcher, site_resource_style


def _discover_ref_templates(
    project_root: Path,
    adapter_cls: type[SimulatorAdapter],
) -> dict[str, str]:
    """Load rich ref templates when available."""
    refs_dir = project_root / "refs"
    templates: dict[str, str] = {}

    for _url, repo_name in adapter_cls.doc_repos():
        repo_dir = refs_dir / repo_name
        if not repo_dir.is_dir():
            continue
        for candidate_name in ("plasma.toml", "beach.toml"):
            candidate = repo_dir / candidate_name
            if not candidate.is_file():
                continue
            try:
                templates[candidate_name] = candidate.read_text(encoding="utf-8")
            except OSError as exc:
                _warn_fallback(
                    f"failed to read ref template {candidate}: {exc}; "
                    "using bundled template"
                )
    return templates


def new(
    case_name: Annotated[
        str,
        typer.Argument(help="Name of the new case to create."),
    ],
    simulator: Annotated[
        Optional[str],
        typer.Option(
            "--simulator",
            "-s",
            help="Simulator name (auto-detected from cwd if under cases/<sim>/).",
        ),
    ] = None,
    dest: Annotated[
        Optional[Path],
        typer.Option(
            "--dest",
            "-d",
            help="Destination directory (defaults to cases/<simulator>/).",
        ),
    ] = None,
    survey: Annotated[
        bool,
        typer.Option(
            "--survey",
            help="Also generate a survey.toml stub in runs/<case_name>/.",
        ),
    ] = False,
    minimal: Annotated[
        bool,
        typer.Option(
            "--minimal",
            "-m",
            help=(
                "Use the small bundled adapter template instead of the rich "
                "reference template from refs/.  The result is shorter and "
                "easier to edit but contains fewer worked examples."
            ),
        ),
    ] = False,
) -> None:
    """Create a new case template with simulator-specific boilerplate.

    When --dest is omitted, the case is created under cases/<simulator>/
    (resolved from the project root).  If the simulator cannot be determined,
    an explicit --simulator/-s is required.

    With ``--minimal`` the case starts from the bundled adapter template
    only — the rich reference template that runops normally pulls from
    ``refs/<simulator>/`` is skipped.  Use this when you want a small,
    easy-to-edit starting point.

    For EMSES cases, ``runo case new`` also tries to populate
    ``[meta.physical]`` in the generated ``plasma.toml`` by running
    ``emu generate -u`` (best-effort: silently skipped if the ``emu``
    CLI is not on PATH).

    Examples:
      runo case new flat_surface -s emses
      runo case new flat_surface -s emses --minimal
      runo case new periodic -s beach --survey
      cd cases/emses && runo case new flat_surface
      runo case new mycase -d /path/to/dest -s emses
    """
    # Detect simulator early: from --simulator, or from dest/cwd path
    cwd = Path.cwd().resolve()
    sim_name = simulator or _detect_simulator((dest or cwd).resolve())

    # Resolve target_dir: use dest if given, otherwise cases/<sim>/ from project root
    if dest is not None:
        target_dir = dest.resolve()
    elif sim_name is not None:
        project_root_candidate = _try_find_project_root(cwd)
        if project_root_candidate is not None:
            target_dir = (project_root_candidate / "cases" / sim_name).resolve()
        else:
            target_dir = cwd
    else:
        target_dir = cwd

    # Final simulator detection from resolved target_dir
    if sim_name is None:
        sim_name = _detect_simulator(target_dir)
    if sim_name is None:
        typer.echo(
            "Cannot detect simulator.\n"
            "Use --simulator/-s or run from inside cases/<simulator>/."
        )
        raise typer.Exit(code=1)

    # Load adapter
    try:
        import runops.adapters  # noqa: F401
        from runops.adapters.registry import get_global_registry

        registry = get_global_registry()
        available = registry.list_adapters()

        if sim_name not in available:
            typer.echo(
                f"Unknown simulator: '{sim_name}'. Available: {', '.join(available)}"
            )
            raise typer.Exit(code=1)

        adapter_cls = registry.get(sim_name)
    except KeyError as e:
        typer.echo(f"Error: {e}")
        raise typer.Exit(code=1) from None

    # Create case directory
    case_dir = target_dir / case_name
    if case_dir.exists():
        typer.echo(f"Error: {case_dir} already exists.")
        raise typer.Exit(code=1)

    case_dir.mkdir(parents=True)

    # Resolve project root (used for launcher, site profile, and ref templates)
    default_launcher = "srun"
    site_resource_style = "standard"
    project_root = _try_find_project_root(target_dir)
    if project_root is not None:
        default_launcher, site_resource_style = _load_case_defaults(project_root)

    # Look for rich template files in refs/<repo>/.  Skipped under
    # ``--minimal`` so the user always gets the small bundled adapter
    # template, even if a refs/ override exists.
    ref_templates: dict[str, str] = {}
    if not minimal and project_root is not None:
        ref_templates = _discover_ref_templates(project_root, adapter_cls)

    # Write template files
    templates = adapter_cls.case_template()
    created: list[str] = []

    for filename, content in templates.items():
        filepath = case_dir / filename
        # Fill in case name and launcher in case.toml
        if filename == "case.toml":
            content = content.replace('name = ""', f'name = "{case_name}"', 1)
            content = content.replace(
                'launcher = "default"', f'launcher = "{default_launcher}"', 1
            )
            # Replace job fields based on site resource style
            if site_resource_style == "rsc":
                content = content.replace(
                    'partition = ""\nnodes = 1\nntasks = 1\nwalltime = "01:00:00"\n',
                    'partition = ""\nprocesses = 1\nthreads = 1\n'
                    'cores = 1\nwalltime = "01:00:00"\n',
                )
        # Override with rich template from refs/ if available
        if filename in ref_templates:
            content = ref_templates[filename]
        filepath.write_text(content, encoding="utf-8")
        created.append(filename)

    typer.echo(f"Created case '{case_name}' for simulator '{sim_name}':")
    typer.echo(f"  Path: {case_dir}")
    for f in created:
        typer.echo(f"    {f}")
    typer.echo(
        f"\nEdit {case_dir / 'case.toml'} to configure parameters and job settings."
    )

    # For EMSES cases, populate [meta.physical] in plasma.toml via emu.
    # Best-effort: silently skip if emu is not on PATH.
    if sim_name == "emses":
        plasma_toml = case_dir / "plasma.toml"
        if plasma_toml.exists():
            _try_emu_generate(plasma_toml)

    # Optionally generate survey.toml stub
    if survey:
        _generate_survey_stub(
            case_name,
            sim_name,
            default_launcher,
            project_root=project_root,
            resource_style=site_resource_style,
        )


def _try_emu_generate(plasma_toml: Path) -> None:
    """Run ``emu generate -u`` on a freshly-created plasma.toml.

    Best-effort: prints a notice on success and silently skips when the
    ``emu`` CLI is not installed (e.g. when EMSES has not been pip-installed
    into the project venv yet).  Any other failure is reported as a
    warning so the user can re-run manually.
    """
    import shutil
    import subprocess

    if shutil.which("emu") is None:
        return

    try:
        result = subprocess.run(
            ["emu", "generate", "-u", str(plasma_toml)],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        typer.echo(
            f"  Warning: failed to auto-run `emu generate -u`: {exc}",
            err=True,
        )
        return

    if result.returncode == 0:
        typer.echo(
            f"  Populated [meta.physical] in {plasma_toml.name} via `emu generate -u`."
        )
    else:
        # Don't fail the case creation — the file is still usable, just
        # without [meta.physical] info.  Surface the error so the user
        # knows to re-run manually.
        typer.echo(
            "  Warning: `emu generate -u` exited with "
            f"code {result.returncode}: {(result.stderr or '').strip()}",
            err=True,
        )


def _generate_survey_stub(
    case_name: str,
    simulator: str,
    launcher: str,
    *,
    project_root: Path | None = None,
    resource_style: str = "standard",
) -> None:
    """Generate a provisional survey stub under .runops/work/surveys/.

    Args:
        case_name: Name of the base case.
        simulator: Simulator name.
        launcher: Launcher profile name.
        project_root: Project root directory (if already resolved).
        resource_style: Site resource style ("standard" or "rsc").
    """
    if project_root is None:
        typer.echo("  Warning: Could not find project root; skipping survey.toml.")
        return

    survey_dir = project_root / ".runops" / "work" / "surveys" / case_name
    survey_dir.mkdir(parents=True, exist_ok=True)

    # Build the case reference path: <sim>/<case_name> for multi-sim layout
    base_case_ref = f"{simulator}/{case_name}"

    if resource_style == "rsc":
        job_comment = (
            '# partition = ""\n'
            "# processes = 1\n"
            "# threads = 1\n"
            "# cores = 1\n"
            '# walltime = "01:00:00"'
        )
    else:
        job_comment = (
            '# partition = ""\n# nodes = 1\n# ntasks = 1\n# walltime = "01:00:00"'
        )

    from runops.templates import render

    content = render(
        "survey.toml.j2",
        case_name=case_name,
        base_case_ref=base_case_ref,
        simulator=simulator,
        launcher=launcher,
        job_comment=job_comment,
    )
    survey_file = survey_dir / "survey.toml"
    if survey_file.exists():
        typer.echo(f"\n  survey.toml already exists at {survey_dir}, skipping.")
        return

    survey_file.write_text(content, encoding="utf-8")
    typer.echo("\nCreated survey stub:")
    typer.echo(f"  Path: {survey_dir / 'survey.toml'}")
    typer.echo(
        "  This is provisional and ignored by formal Run discovery. "
        "After assigning an Experiment and finite budget, move it under runs/ "
        "and preview with `runo runs sweep`."
    )
