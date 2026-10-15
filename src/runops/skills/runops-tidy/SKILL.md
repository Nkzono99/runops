---
name: runops-tidy
description: Keep a runops project small (tidy, archive, pin, delete). Use when the run list feels cluttered, disk usage grows, or before starting a new batch of runs.
---

# Tidying

1. `runo tidy` lists candidates without changing anything:
   - `expired-scratch`: scratch runs past their expiry -> delete
   - `stale-failed`: failed/cancelled runs older than 30 days with no `why` and no notes -> delete
   - `old-completed`: completed runs older than 90 days -> archive
   - `orphan-job`: submitted/running runs that Slurm no longer knows -> sync
   - `unused-build`: build caches no active run uses -> delete
2. Show the list to the user. Apply with `runo tidy --apply`, or one kind with
   `runo tidy --apply --only old-completed`.
3. Runs that matter (baselines, figures in a paper) should be pinned so `list` always
   shows them and tidy/delete never touch them:
   `runo pin RUN --reason "baseline for fig. 3"` (`--off` to unpin).
4. `runo archive RUN` moves a finished run to `runs/_archive/` (same relative path);
   `runo restore RUN` brings it back. Archived runs stay findable by id.
5. `runo delete RUN` removes created/failed/cancelled or scratch runs only.
6. Run `runo tidy` when starting a new line of work, so the list stays readable.
