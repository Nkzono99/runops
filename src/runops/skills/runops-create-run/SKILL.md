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

Values in `--set` are TOML literals: `3`, `1.5e-6`, `true`, `"text"`, `[1, 2]`.
Unquoted words become strings.

Never edit `manifest.toml` or `input/` of a created run. Create a new run instead.
