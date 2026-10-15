---
name: runops-reference
description: Full runops (runo) command reference, project layout and manifest fields. Use when unsure which runo command or option to use.
---

# runo command reference

| command | effect |
|---|---|
| `runo init [SIM...] [--site NAME] [-y]` | create runops.toml, cases/, runs/, LOG.md, notes/, AGENTS.md, skills; install simulator packages |
| `runo doctor [--json]` | check config, adapters, executables, sbatch, skill freshness |
| `runo update [--skills-only] [-y]` | upgrade simulator packages and redeploy skills / AGENTS.md block |
| `runo build SIM [--force]` | build a local_source simulator into .runops/build/<sim>-<commit> |
| `runo context [--json]` | project summary for agents |
| `runo case new NAME [--simulator SIM] [--from CASE]` / `runo case list` | scaffold / list cases |
| `runo new CASE [--why] [--label] [--set k=v]... [--tag] [--scratch] [--dest DIR] [--submit] [--json]` | create a run |
| `runo new --from RUN [--why] [--set k=v]... [--continue] [--submit]` | derive a run |
| `runo sweep CASE --set k=v1,v2... [--label L] [--why] [--apply] [--submit] [--limit N] [--json]` | product of values |
| `runo submit RUN... [--partition P] [--qos Q] [--afterok JOBID] [-y]` | sbatch created runs |
| `runo submit --all [DIR] [-y]` | sbatch every created run under DIR |
| `runo cancel RUN... [-y]` | scancel |
| `runo retry RUN [--submit]` | failed/cancelled -> created |
| `runo status [RUN...] [--json]` | show manifest state (no Slurm call) |
| `runo sync [RUN...] [--json]` | update state from Slurm |
| `runo log RUN [--err] [-n N] [-f]` | latest job stdout/stderr |
| `runo list [PATH] [--all] [--since 30d] [--case C] [--sweep L] [--status S] [--tag T] [--scratch] [--archived] [--json]` | runs |
| `runo note RUN [TEXT] [--by WHO]` | append / show notes |
| `runo pin RUN [--off] [--reason TEXT]` | keep a run visible and safe from tidy/delete |
| `runo summarize RUN... [--force]` | analysis/summary.json from the adapter |
| `runo archive RUN... [-y]` / `runo archive --older-than 90d [-y]` | move to runs/_archive |
| `runo restore RUN` | move back |
| `runo delete RUN... [-y]` | remove created/failed/cancelled/scratch runs |
| `runo tidy [--apply] [--only KIND] [--older-than AGE] [--purge-work RUN...] [--json]` | cleanup (thresholds: `[defaults].tidy_failed_days` / `tidy_archive_days`) |
| `runo migrate-v1 [--dry-run]` | convert a runops v1 project |

## Layout

`runops.toml` (site, simulators, launchers, defaults), `cases/<name>/case.toml` plus base
input files, `runs/<case>/<run_id>--<label>/` with `manifest.toml`, `input/`, `submit/job.sh`,
`work/` (cwd for Slurm logs), `analysis/`, optional `notes.md`. Scratch runs live in
`runs/_scratch/`, archived runs in `runs/_archive/`.

## Manifest

`[run]` id, label, status, why, scratch, expires_at, pinned, tags, `[[notes]]`;
`[origin]` case, sweep, parent_run; `[simulator]` executable and provenance;
`[job]` resources, job_id, `[[job.attempts]]`; `[params]` final values;
`[variation].changed_keys`. Status: created -> submitted -> running ->
completed | failed | cancelled; terminal runs can be archived.
