---
name: runops-analyze
description: Analyze or compare run results in a runops project. Use when plotting, investigating a series or sweep, writing an analysis report, or choosing where analysis scripts and outputs belong.
---

# Analyze run results

1. Read `runo context`, identify the question and target run ids, and check existing
   analysis directories for the same topic. Use simulator skills for physical methods.
2. Choose the location by the runs the result depends on:
   - one run: `<run_dir>/analysis/` (or a topic inside it);
   - one series or sweep directory: `runs/<group>/_analysis/<topic>/`;
   - multiple groups or the whole project: `analysis/<topic>/`;
   - reusable modules and their tests: `analysis/lib/`.
   A group is just a directory of runs. Name topics for the question, without a date;
   revisit an existing topic by updating its outputs and dating the README entry.
3. Keep one investigation together:
   - `README.md`: question, target run ids and paths, method, results, limits;
   - `scripts/`: Python and sbatch scripts;
   - `out/`: JSON, CSV, plots, HTML;
   - `logs/`: analysis job stdout and stderr.
4. Use `.runops/analysis-env/` for extra analysis dependencies. Check the host and site
   rules before running; heavy reads and plotting belong on compute nodes.
   Submit from the investigation directory, creating `logs/` before sbatch opens logs:
   ```bash
   cd <investigation-directory>
   mkdir -p logs
   sbatch scripts/analyze.sbatch
   ```
   In the script use `#SBATCH -o logs/%x.%j.out` and `#SBATCH -e logs/%x.%j.err`,
   the site's resource directives, and `srun` for the payload where required.
   Keep the working directory at the investigation root so `scripts/` and `out/` resolve.
5. Update the investigation README, then append the decision and its README link to
   `LOG.md`. Put reusable formulas, methods and pitfalls in `notes/<topic>.md`.
6. `runo tidy --only analysis-logs` previews old job logs, retaining the newest pair per
   job name in each logs directory. Apply with `runo tidy --apply --only analysis-logs`.
   Archiving a whole group directory also moves its `_analysis/`; a partial archive
   leaves shared analysis with the remaining runs. `restore RUN` restores only that run.
7. For an existing project's scattered files, show source → destination paths before
   moving anything, then fix affected script paths and document links. Keep results.
