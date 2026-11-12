---
name: runops-maintain
description: Maintain a runops project - add or change a simulator, update runops or simulator packages, refresh skills, fix environment problems, or meet a runops v1 project. Use when the user asks to set up, upgrade, migrate, or add a simulator rather than to run simulations.
---

# Maintaining the project

Start with `runo doctor`; it shows how each adapter resolves (entry-point,
project-local, builtin), missing executables, Slurm availability, stale skills, skill
links to missing files and v1 leftovers. Fix what it reports, then run it again.

## Add a simulator

1. Add `[simulators.<name>]` to `runops.toml`: `adapter`, `resolver_mode`,
   `executable`, optional `package` (pip spec), `modules`. Several entries may share an
   adapter (e.g. a patched build). See `runops-reference` for fields.
2. Packaged simulator: `runo update -y` installs the package into `.venv`, finds its
   `runops.adapters` entry point, adds the other packages its adapter lists when missing
   (emout for emses) and deploys its skills. `runo doctor` names any that are missing.
3. Source build: `resolver_mode = "local_source"` with `source_repo`, `build_command`,
   `executable` (relative to the build dir); `runo build <name>` builds into
   `.runops/build/`. Builds compile code; on HPC login nodes follow the site's rule for
   where builds may run.
4. No package yet: put an `Adapter` class in `adapters/<adapter>.py` (contract in the
   runops `docs/adapter.md`). `generic` with `command = "..."` covers simple programs.
5. `runo case new NAME --simulator <name>`, then fill the base input and `[job]`.

## Update

- runops itself: `uv tool upgrade runops` (or reinstall the way it was installed),
  then `runo update --skills-only` to refresh skills and the AGENTS.md block.
  `runo context` warns when this project's runops skills are older than the installed runops.
- Simulator packages: `runo update -y`. Tell the user which packages changed.
- `runo update` rewrites only the `<!-- runops:begin/end -->` block of AGENTS.md and
  directories marked `.managed-by-runops`.

## A runops v1 project

A v1 project has `simulators.toml` / `site.toml`; this runops stops there and names
the way: convert it with runops 2.8, which still has `migrate-v1`
(`uvx --from runops==2.8.0 runo migrate-v1 --dry-run`, then `-y` after the user
confirms the plan), and continue with this version (`runo doctor`, `runo list --all`).

Report what changed and anything the user must do (credentials, site-specific
modules, deleting `.runops/v1-backup/` after review).
