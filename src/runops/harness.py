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
| `runo new CASE --why TEXT [--set k=v]... [--scratch] [--submit]` | create one run |
| `runo new --from RUN --why TEXT [--set k=v]... [--continue]` | derive a run from another |
| `runo sweep CASE --set k=v1,v2 [--names k=n1,n2] [--apply] [--submit]` | preview / create a parameter product |
| `runo submit RUN... [--partition P]` / `runo submit --all DIR` | sbatch created runs |
| `runo sync` / `runo status RUN` / `runo log RUN [--err]` | refresh state from Slurm / show / read logs |
| `runo list [--all] [--case C] [--status S] [--json]` | recent + active runs (old, scratch, archived hidden) |
| `runo cancel RUN` / `runo retry RUN` | stop a job / reset failed or cancelled to created |
| `runo note RUN "text"` / `runo pin RUN --reason TEXT` | append an observation / protect a key run |
| `runo summarize RUN` | adapter summary into analysis/summary.json |
| `runo tidy` / `runo tidy --apply` | list / apply cleanup (expired scratch, stale failures, old runs) |
| `runo mv RUN... [--dest DIR] [--label L] --why TEXT` | rename / move runs, keeping ids and inputs |
| `runo archive RUN\\|DIR... [--superseded-by RUN\\|DIR --why T]` | move finished runs (or a series) to runs/_archive |
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

This is a runops project: simulation runs are tracked as directories under
`runs/`, each with a `manifest.toml` owned by runops. Use the `runo` CLI.

## Simulators

{sims}

## Commands

{COMMANDS}

## Rules

- The request sets what may happen: "make/create" creates runs only; "run/submit" also
  submits; "try/test" allows a short `--scratch` run and its submission, never a
  production submit. Earlier runs may fill in parameters, not add actions.
- Before `submit`, `sweep --apply --submit`, or `submit --all`, show the target runs,
  partition and resources, and get confirmation.
- Scope is this project: the runs under `runs/` here and their job ids. "all", "resubmit",
  "cancel the duplicates" mean runs of this project. Do not `cd` to other projects or use
  raw `sbatch` / `scancel` to widen it; account-wide `squeue` / `sacct` is for diagnosis,
  never a target list. If no run here matches, say so. Touch other projects' runs only when
  the user names them, and never revive runs another session cancelled to fix them.
- After a production submit is accepted, report the job ids and stop. When asked to
  watch, check once for early failure, then near the expected end; no `tail -f` loops.
- Never edit `manifest.toml` or a run's `input/` by hand. Change the case or create a
  new run with `--set` / `new --from`. To rename or move a run, use `runo mv`, not a
  re-created copy.
- When a new series replaces an old one, ask whether the old one is still needed; if not,
  `runo archive OLD_DIR --superseded-by NEW_DIR --why ...` and report what was archived.
- Express variations as runs, not cases: use `runo new CASE --set k=v`,
  `runo new --from RUN --set k=v`, or `runo sweep`. Create a new case only when the
  structure of the base input files changes.
- Always pass `--why` when creating runs. Use `--scratch` for smoke/debug runs.

## Notes

- Observations about one run: `runo note RUN "..."` (or the run's `notes.md`).
- Conclusions across runs and next decisions: append to `LOG.md` under a dated heading.
- Reusable knowledge (formulas, methods, pitfalls): `notes/<topic>.md`, one file per
  topic. Extend an existing file instead of creating a similar one.
- Do not create note files anywhere else (`research/`, `analysis/*.md`, `runs/`).

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
