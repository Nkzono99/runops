"""``AGENTS.md`` / ``CLAUDE.md`` generation (SPEC §10)."""

from __future__ import annotations

from pathlib import Path

from runops.project import Project

BEGIN = "<!-- runops:begin -->"
END = "<!-- runops:end -->"

COMMANDS = """\
| command | effect |
|---|---|
| `runo context --json` | where the project stands: active runs, recent runs, LOG.md tail |
| `runo case list` / `runo case new NAME --simulator SIM [--from CASE]` | list / scaffold cases |
| `runo new CASE --why TEXT [--set k=v]... [--job k=v]... [--scratch] [--submit]` | create one run |
| `runo new --from RUN --why TEXT [--set k=v]... [--job k=v]... [--continue]` | derive a run (keeps its params and [job]) |
| `runo sweep CASE --set k=v1,v2 [--names k=n1,n2] [--apply] [--submit]` | preview / create a parameter product |
| `runo submit RUN... [--partition P]` / `runo submit --all DIR` | sbatch created runs |
| `runo sync` / `runo status RUN` / `runo log RUN [--err]` | refresh state from Slurm / show / read logs |
| `runo list [--all] [--case C] [--status S] [--json]` | recent + active runs (old, scratch, archived hidden) |
| `runo cancel RUN [--why T]` / `runo retry RUN` | stop a job / reset failed or cancelled to created |
| `runo note RUN "text"` / `runo pin RUN --reason TEXT` | append an observation / protect a key run |
| `runo summarize RUN` | adapter summary into analysis/summary.json |
| `runo tidy` / `runo tidy --apply` | list / apply cleanup (expired scratch, stale failures, old runs) |
| `runo mv RUN... [--dest DIR] [--label L] --why TEXT` | rename / move runs, keeping ids and inputs |
| `runo archive RUN\\|DIR... [--superseded-by RUN\\|DIR --why T]` | move created or finished runs (or a series) to runs/_archive |
| `runo restore RUN` / `runo delete RUN` | move back / remove |
| `runo build SIM` | build a local_source simulator into .runops/build |
| `runo doctor` / `runo update` | check environment / upgrade simulator packages and skills |"""


def render_block(project: Project, skills: list[str]) -> str:
    sims = (
        "\n".join(
            f"- `{name}`: adapter `{sim.adapter}`, resolver `{sim.resolver_mode}`"
            for name, sim in project.config.simulators.items()
        )
        or "- (none configured yet; add `[simulators.<name>]` to runops.toml)"
    )
    skill_lines = "\n".join(f"- `{name}`" for name in skills) or "- (none)"
    return f"""{BEGIN}
# {project.config.name}

This is a runops project. Each run is a directory under `runs/` with a `manifest.toml`
that runops owns. The `runo` CLI creates, submits, tracks and tidies runs, and acts on
the project found from the current directory.

## Simulators

{sims}

## Commands

{COMMANDS}

## How to work here

- **Let the request set the actions.** "make/create" means creating runs; "run/submit"
  also submits; "try/test" means a short `--scratch` run that you may submit. Earlier
  runs can supply parameters, while the request decides what happens.
- **Confirm before compute is spent.** Before any submit, show the runs, partition,
  resources and core-hours, and wait for the go-ahead. Once Slurm accepts the jobs,
  report the job ids and end the turn; Slurm does the waiting. When asked to watch,
  check once early and once near the expected end.
- **Work within this project.** Requests such as "resubmit everything" mean the runs
  under `runs/` here: find them with `runo sync` and `runo list`. Account-wide `squeue`
  and `sacct` help diagnose, but other projects and unmanaged jobs belong to other
  sessions, so act on them only when the user names them. If nothing here matches, say so.
- **Change runs through `runo`.** `runo` writes each run's manifest and `input/`, so
  they stay an exact record of what ran.
  Express a change as a new run (`runo new --from RUN --set k=v`, `--job walltime=...`
  for resources, `runo sweep`) and rename or regroup with `runo mv`. Variations are
  runs; a new case is for a different structure of the base input.
- **Leave the reason behind.** Give each new run `--why`. When you cancel runs to fix or
  replace them, add `runo cancel --why`, so later sessions and `runo retry` leave them
  stopped. When a new series replaces an old one, ask whether the old one is still
  needed and archive it with `--superseded-by`.

## Notes

Notes live in three places, where `runo context` and the next session find them:
- one run: `runo note RUN "..."`;
- conclusions across runs and next decisions: `LOG.md`, appended under a dated heading;
- reusable knowledge (formulas, methods, pitfalls): `notes/<topic>.md`, extending the
  existing file for a topic.

Analysis tools the simulator package does not bring go in `.runops/analysis-env/`
(`uv venv .runops/analysis-env`), so `.venv` stays as `runo update` manages it. Run heavy
reading and plotting where the site allows compute jobs.

## Skills

{skill_lines}
{END}
"""


def write_harness(project: Project, skills: list[str]) -> list[Path]:
    written: list[Path] = []
    block = render_block(project, skills)
    agents = project.root / "AGENTS.md"
    if agents.is_file():
        text = agents.read_text(encoding="utf-8")
        if BEGIN in text and END in text:
            head, _, rest = text.partition(BEGIN)
            _, _, tail = rest.partition(END)
            text = head + block.rstrip("\n") + tail
        else:
            text = block + "\n" + text
    else:
        text = block
    agents.write_text(text, encoding="utf-8")
    written.append(agents)
    claude = project.root / "CLAUDE.md"
    if not claude.exists():
        claude.write_text("@AGENTS.md\n", encoding="utf-8")
        written.append(claude)
    return written
