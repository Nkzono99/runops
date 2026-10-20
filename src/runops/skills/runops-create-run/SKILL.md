---
name: runops-create-run
description: Create simulation runs with runops (runo new / new --from / sweep). Use when the user wants to run a simulation, try a parameter, scan values, or rerun a variant.
---

# Creating runs

1. `runo context --json` and `runo case list` to see what exists.
2. Pick the case. Express the variation with `--set`, not with a new case:
   - one run: `runo new CASE --why "..." --set section.key=value`
   - from an existing run: `runo new --from RUN --why "..." --set key=value`
   - continue from a finished run (if the adapter supports it): `runo new --from RUN --continue --why "..."`
   - a product of values: `runo sweep CASE --set a=1,2 --set b=x,y --why "..."`
     shows the points and core-hours without creating anything; add `--apply` to create.
3. Always write `--why`: the question this run answers, in one sentence.
4. Smoke and debug runs use `--scratch`. They are hidden from `runo list` and
   `runo tidy` deletes them after they expire.
5. Create a new case (`runo case new NAME --from CASE`) only when the structure of the
   base input file changes, not for a different value.
6. Before submitting, show the run ids, partition, resources and core-hours and get
   confirmation. Then `runo submit RUN...` or create with `--submit`.
7. When the new runs replace an old series (a bug or wrong input in the old one), ask
   whether the old series is still needed. Deriving with `--from` alone does not make
   the source obsolete. If it is not needed and its runs are finished:
   `runo archive OLD_DIR --superseded-by NEW_DIR --why "..."`. Report the current
   series, the archive path and the count.

## Naming

Names identify a series and its key settings; the manifest and input hold the rest.
- Shared settings of a series go in the parent directory (`sweep --label`, `--dest`),
  e.g. `d5m_T10eV_v400kms_pe`; the run label shows only what differs per point.
- When a swept value is long (a whole array), name each value:
  `--names KEY=wh0,wh1,...`. Do not add dummy parameters for naming.
- Use units (`T10eV`, `v400kms`), skip defaults, do not repeat parent info in labels.
  Check the preview against existing series before `--apply`.
- To rename or regroup existing runs, `runo mv RUN... --dest DIR [--label L] --why ...`.
  It keeps ids and inputs; never re-create a run just to change its name.

## Walltime

Before setting `[job].walltime`, look for a comparable finished run (same case,
resources and step count): `runo list --case C --all --json` shows `elapsed`,
`walltime` and `walltime_used`. Suggest about 1.3-1.5x its elapsed, rounded up, and
name the run it came from. A `TIMEOUT` run's elapsed is only a lower bound. With no
comparable run, say the estimate is unknown. Change the case only after confirmation.

Values in `--set` are TOML literals: `3`, `1.5e-6`, `true`, `"text"`, `[1, 2]`.
Unquoted words become strings.

Never edit `manifest.toml` or `input/` of a created run. Create a new run instead.
