---
name: runops-check-status
description: Check the progress or result of runops runs (sync, list, log, retry). Use when the user asks how jobs are doing, whether runs finished, or why a run failed.
---

# Checking runs

1. `runo sync` refreshes every submitted/running run from squeue/sacct.
2. `runo list` shows active and recent runs. `--all`, `--case C`, `--status failed`
   and `--json` narrow or widen the view. Scratch and archived runs are hidden unless
   `--scratch` / `--archived` is given.
3. `runo status RUN` shows one run; `runo log RUN` and `runo log RUN --err` show the
   tail of the latest job's stdout / stderr (`-n 200` for more, `-f` to follow).
4. For a failed run, read the stderr log and the adapter summary
   (`runo summarize RUN`). Record the cause with `runo note RUN "..."`.
   `failed (TIMEOUT)` means the walltime ran out: compare `elapsed` with `walltime`
   and raise the case walltime for the next run.
5. To rerun the same inputs: `runo retry RUN` then `runo submit RUN` after confirming.
   To change inputs, create a new run with `runo new --from RUN --set ...`.
6. Recovery ("jobs vanished, resubmit them"): `runo sync`, then
   `runo list --status failed --status cancelled`. These runs are the candidates.
   A run cancelled with a reason (a `cancelled: ...` note) was stopped on purpose,
   usually to be replaced; list it separately and let the user decide.
   `runo retry` shows that reason and asks before reviving it.
7. If a run's `work/` is large and the run is done, `runo tidy --purge-work RUN`
   removes outputs except the adapter's keep patterns.

## Observing long jobs

- When watching: one early `runo sync` + `runo log RUN --err` catches startup
  failures; the next check is near the expected end (walltime, progress in the log).
  With unknown timing start at ~1 min and lengthen to 2 and 5 min, doing other
  requested work in between. Spaced checks keep the session responsive.
- A job leaving the queue is confirmed by `runo sync` (exit record written by job.sh,
  then the adapter verdict) and the outputs.
- At the user's deadline, report the last state and leave cancel or resubmit to them.
- `runo sync` queries Slurm once for all runs, so it is the cheap way to refresh.

Summarize conclusions that span several runs in `LOG.md` under a dated heading.
