---
name: runops-tidy
description: Keep a runops project small (tidy, archive, pin, delete). Use when the run list feels cluttered, disk usage grows, or before starting a new batch of runs.
---

# Tidying

1. `runo tidy` lists candidates without changing anything:
   - `expired-scratch`: scratch runs past their expiry -> delete
   - `stale-failed`: failed/cancelled runs older than `tidy_failed_days` (default 30) with no
     `why` and no notes -> delete
   - `old-completed`: completed runs older than `tidy_archive_days` (default 90) -> archive
   - `orphan-job`: submitted/running runs that Slurm no longer knows -> sync
   - `unused-build`: build caches no active run uses -> delete
2. Show the list to the user. Apply with `runo tidy --apply`, or one kind with
   `runo tidy --apply --only old-completed`.
3. Runs that matter (baselines, figures in a paper) should be pinned so `list` always
   shows them and tidy/delete never touch them:
   `runo pin RUN --reason "baseline for fig. 3"` (`--off` to unpin).
4. `runo archive RUN` moves a finished run to `runs/_archive/` (same relative path);
   `runo restore RUN` brings it back. Archived runs stay findable by id.
   A directory archives a series: it lists the runs first and skips created/submitted/
   running and pinned ones. For a replaced series add
   `--superseded-by NEW_DIR --why "..."`; each old run records its replacement
   (the new run derived from it, else the whole new series) in `superseded_by`.
5. `runo delete RUN` removes created/failed/cancelled or scratch runs only.
6. Run `runo tidy` when starting a new line of work, so the list stays readable.
7. The day counts live in `[defaults]` of `runops.toml`. When the user wants a different
   policy for the project, change them there; `--older-than 14d` overrides both for one run.
