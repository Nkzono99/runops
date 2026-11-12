---
name: runops-create-run
description: Create simulation runs with runops (runo new / new --from / sweep). Use when the user wants to run a simulation, try a parameter, scan values, or rerun a variant.
---

# Creating runs

1. `runo context --json` and `runo case list` to see what exists.
2. Pick the case. Express the variation with `--set` (TOML literals: `3`, `1.5e-6`, `true`,
   `"text"`, `[1, 2]`; bare words are strings), not with a new case:
   - one run: `runo new CASE --why "..." --set section.key=value`
   - from an existing run: `runo new --from RUN --why "..." --set key=value`
     (keeps the source's params and `[job]`, and sits beside it; the output lists what differs)
   - continue from a finished run (if the adapter supports it): `runo new --from RUN --continue --why "..."`
   - a product of values: `runo sweep CASE --set a=1,2 --set b=x,y --why "..."`
     shows the points and core-hours without creating anything; add `--apply` to create.
3. Always write `--why`: the question this run answers, in one sentence.
4. Smoke and debug runs use `--scratch` (see Start-up checks). `runo list` shows them
   while queued or running, and `runo tidy` deletes them after they expire.
5. Create a new case (`runo case new NAME --from CASE`) only when the structure of the
   base input changes, not for a different value. Runs copy the case's top-level files and
   `input/`, so a structure spread over several files (a layout and its tables) is its own case.
6. Resources belong to the run: `--job walltime=72:00:00 --job processes=256` on `new` or
   `sweep`. Change the case's `[job]` only for future runs, after confirmation.
7. After the confirmation AGENTS.md asks for, `runo submit RUN...` or create with
   `--submit`. If only some are accepted, resubmit just the runs the summary lists as
   still created (`runo submit <id...>`); accepted runs are no longer created and are refused.
8. When new runs replace an old series (a bug or wrong input in it), ask whether the old
   one is still needed; deriving with `--from` alone does not make the source obsolete.
   If not (finished runs or created drafts): `runo archive OLD_DIR --superseded-by NEW_DIR
   --why "..."`, then report the current series, the archive path and the count.

## Start-up checks

A short `--scratch` run shows that the program starts and the physical setup holds; judge
steadiness, statistical error and convergence separately, on longer runs. The project's check
script (runops records runs, it does not judge them) stops on abnormal exit, NaN, missing
output, a ledger mismatch or a broken physical condition, and warns on a few outliers, cache
misses or a speed extrapolated from a short sample. Give each threshold its basis and
denominator (share of N items, the window); per item, write pass/warn/fail, value, unit,
threshold and script version to JSON. Check each layout briefly: one stands for no other.

## Naming

Names identify a series and its key settings; the manifest and input hold the rest.
- Shared settings of a series go in the parent directory (`sweep --label`, `--dest`),
  e.g. `d5m_T10eV_v400kms_pe`; the run label shows only what differs per point.
- When a swept value is long (a whole array), name each value with
  `--names KEY=wh0,wh1,...` rather than adding a parameter just for the name.
- Use units (`T10eV`, `v400kms`), skip defaults, and keep labels to what differs from
  the parent. Check the preview against existing series before `--apply`.
- To rename or regroup existing runs, `runo mv RUN... --dest DIR [--label L] --why ...`.
  It keeps ids and inputs, so the history stays attached.

## Walltime

Before setting `[job].walltime`, find a comparable finished run (same case, resources and step
count; `runo list --case C --all --json` shows `elapsed`, `walltime`, `walltime_used`). Suggest
about 1.3-1.5x its elapsed, rounded up, naming that run; a `TIMEOUT` run's elapsed is only a lower
bound, and with no comparable run the estimate is unknown. Set it with `--job walltime=...`.
