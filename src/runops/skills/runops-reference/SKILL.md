---
name: runops-reference
description: Full runops (runo) command reference, project layout and manifest fields. Use when unsure which runo command or option to use.
---

# runo command reference

| command | effect |
|---|---|
| `runo init [SIM...] [--site kudpc\|standard] [--no-install] [-y]` | create runops.toml, cases/, runs/, LOG.md, notes/, AGENTS.md, skills; install simulator packages. Site defaults to a guess from the host name; asks interactively only in a terminal without arguments |
| `runo doctor [--json]` | check config, adapters, executables, sbatch, skill freshness |
| `runo update [--skills-only] [-y]` | upgrade simulator packages and redeploy skills / AGENTS.md block |
| `runo build SIM [--force]` | build a local_source simulator into .runops/build/<sim>-<commit>-<hash> |
| `runo context [--json]` | project summary: all active runs with progress, recent runs, group analysis topics |
| `runo case new NAME [--simulator SIM] [--from CASE]` / `runo case list` | scaffold / list cases |
| `runo new CASE [--why] [--label] [--set k=v]... [--job k=v]... [--tag] [--scratch] [--dest DIR] [--submit] [--json]` | create a run; `--job` sets this run's `[job]` values |
| `runo new --from RUN [--why] [--set k=v]... [--job k=v]... [--job-from-case] [--continue] [--submit]` | derive a run with the source's params and `[job]` |
| `runo sweep CASE --set k=v1,v2... [--names k=n1,n2...] [--job k=v]... [--label L] [--dest DIR] [--why] [--apply] [--submit] [--limit N] [--json]` | product of values; `--names` gives each value a short run label |
| `runo submit RUN... [--partition P] [--qos Q] [--afterok JOBID] [-y]` | sbatch created runs |
| `runo submit --all [DIR] [-y]` | sbatch every created run under DIR |
| `runo cancel RUN... [--why TEXT] [-y]` | scancel; `--why` is noted and `retry` asks before reviving |
| `runo retry RUN [--submit] [-y]` | failed/cancelled -> created |
| `runo status [RUN...] [--brief] [--json]` | show manifest state (no Slurm call) |
| `runo sync [RUN...] [--json]` | update state from Slurm |
| `runo log RUN [--err] [-n N] [-f]` | latest job stdout/stderr |
| `runo list [PATH] [--all] [--since 30d] [--case C] [--sweep L] [--status S] [--tag T] [--scratch] [--archived] [--brief] [--json]` | runs (`--brief`: no params/why/notes) |
| `runo note RUN [TEXT] [--by WHO]` | append / show notes |
| `runo pin RUN [--off] [--reason TEXT]` | keep a run visible and safe from tidy/delete |
| `runo summarize RUN... [--force]` | analysis/summary.json from the adapter |
| `runo mv RUN... [--dest DIR] [--label L] [--why TEXT]` | rename/move created or finished runs; id, inputs, sweep and notes kept |
| `runo archive RUN\|DIR... [--superseded-by RUN\|DIR --why TEXT] [-y]` / `runo archive --older-than 90d [-y]` | move created or finished runs, or a series, to runs/_archive; record the replacement |
| `runo restore RUN` | move back |
| `runo delete RUN... [-y]` | remove created/failed/cancelled/scratch runs |
| `runo tidy [--apply] [--only KIND] [--older-than AGE] [--purge-work RUN...] [--json]` | cleanup runs, builds and `analysis-logs` (thresholds: `tidy_failed_days` / `tidy_archive_days`) |
| `runo migrate-v1 [--dry-run]` | convert a runops v1 project |

## Layout

`runops.toml` (site, simulators, launchers, defaults), `cases/<name>/case.toml` plus base
input files, `runs/<case>/<run_id>--<label>/` with `manifest.toml`, `input/`, `submit/job.sh`,
`work/` (cwd for Slurm logs), `analysis/`, optional `notes.md`. Scratch runs live in
`runs/_scratch/`, archived runs in `runs/_archive/`. `runo` acts on the project found
from the cwd; paths into another project's `runs/` are refused.
Group analysis lives in `runs/<group>/_analysis/<topic>/`; project analysis in
`analysis/<topic>/`. A whole `archive DIR` includes group analysis; `restore RUN` does not.

## Manifest

`[run]` id, label, status, why, scratch, expires_at, pinned, tags, superseded_by, `[[notes]]`;
`[origin]` case, sweep, parent_run; `[simulator]` executable and provenance;
`[job]` resources, job_id, `[[job.attempts]]` (job_id, exit_code, elapsed, cancel_reason, progress); `[params]` final values;
`[variation].changed_keys`, `job_changed_keys`. Status: created -> submitted -> running ->
completed | failed | cancelled; terminal runs can be archived.
