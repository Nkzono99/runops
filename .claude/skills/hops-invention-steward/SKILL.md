---
name: hops-invention-steward
description: Run the invention and lab-organization lane inside a HOPS daily supervisor. Use for open meta improvement scanning, evidence/routing, research-scan or feedback records, and safe harness-lab queue organization even when earlier lanes already made changes.
---
Use `uvx --from harnessops hops <command>` in target/project repos unless repo-local docs prove `hops` is available.

# Mission

Create or improve the candidate queue. This lane exists so daily automation does not stop after small maintenance or issue work.

Read `.harnessops/project.toml`. Use `hops` for state changes; do not directly reorganize `.harnessops/`, `harness-feedback/`, or `harness-lab/`.

# Work

Run `hops doctor --check-overlay --check-records` when supervisor preflight is missing, stale, or contradicted by the current worktree.

1. Run `hops-open-meta-scan` for broad, non-recording discovery unless a fatal blocker prevents repo inspection.
2. Pass the best 1-3 raw ideas to `hops-research-improvements` for evidence, anti-myopia routing, park/reject decisions, and candidate queue creation.
3. In target/meta lab repos, prefer `hops lab research-scan`, `hops lab investigate`, or `hops lab classify` before new captures. Create `hops lab capture` only for a reusable failure class, cross-project pattern, or important evaluation gap.
4. In project repos, do not create `harness-lab/`; record observations with `hops feedback add-failure`, route them, and export sanitized feedback when useful.
5. Organize existing lab queue when discovery finds stale classification, missing relation, or duplicate local-only candidates.

# Boundaries

Do not implement feature changes just because an idea looks promising. Leave implementation candidates for `hops-priority-improvement-steward`.

# Output

Return the lane result contract: `status`, `changed_files`, `records_created_or_updated`, `issues_touched`, `validation`, `recommended_next`, and `stop_reason`. Include parked/rejected ideas so the supervisor can see the search was real.
