---
name: runops-analyze
description: Analyze or compare run results in a runops project. Use when plotting, investigating a series or sweep, writing an analysis or comparison report for a reader, or choosing where analysis scripts and outputs belong.
---

# Analyze run results

1. Read `runo context` and identify the question and target run ids. Open relevant
   notes under `notes/` and check their definitions and scope against the current runs.
   Look for an existing investigation on the topic. Use simulator skills for physical methods.
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
   rules before running; heavy reads and plotting belong on compute nodes. Analysis jobs
   are work outside runs: record and link them as AGENTS.md describes.
   Submit from the investigation directory, creating `logs/` before sbatch opens logs:
   ```bash
   cd <investigation-directory>
   mkdir -p logs
   sbatch scripts/analyze.sbatch
   ```
   In the script use `#SBATCH -o logs/%x.%j.out` and `#SBATCH -e logs/%x.%j.err`,
   the site's resource directives, and `srun` for the payload where required.
   Keep the working directory at the investigation root so `scripts/` and `out/` resolve.
5. When the result is a report someone will read (a comparison of runs, a dependence,
   "what changed and why"), write it by [report-guide.md](report-guide.md): question and
   answer first, original fields side by side on one scale, each figure explained
   before and after, provenance and checks at the end, as `README.md` plus a
   self-contained `report.html`. [example-report/](example-report/README.md) shows it.
6. Update the investigation README, then append the decision and its README link to
   `LOG.md`. If another investigation could reuse a definition, method or finding,
   update the matching `notes/<topic>.md`. State when it applies (e.g. the denominator
   and time window of a fraction). Link the supporting README and the data behind a
   numerical claim, using paths relative to the note. Include the relevant run ids.
   Plain Markdown works. For machine-readable provenance, a topic note can start with
   OKF frontmatter: a `type` such as `Metric` and a `sources` list of `resource` paths or URLs.
7. `runo tidy --only analysis-logs` previews old job logs, retaining the newest pair per
   job name in each logs directory. Apply with `runo tidy --apply --only analysis-logs`.
   Archiving a whole group directory also moves its `_analysis/`; a partial archive
   leaves shared analysis with the remaining runs. `restore RUN` restores only that run.
8. For an existing project's scattered files, show source → destination paths before
   moving anything, then fix affected script paths and document links. Keep results.
