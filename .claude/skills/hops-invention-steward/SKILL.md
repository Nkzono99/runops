---
name: hops-invention-steward
description: Run the invention and lab-organization lane inside a HOPS daily supervisor after the open-meta-scan lane. Use for reviewing raw ideas, evidence/routing, research-scan or feedback records, and safe harness-lab queue organization even when earlier lanes already made changes.
---
Use `uvx --from harnessops hops <command>` in target/project repos unless repo-local docs prove `hops` is available.

# Mission

Create or improve the candidate queue. This lane exists so daily automation does not stop after small maintenance or issue work.

Read `.harnessops/project.toml`. Use `hops` for state changes; do not directly reorganize `.harnessops/`, `harness-feedback/`, or `harness-lab/`.

# Work

Run `hops doctor --check-overlay --check-records` when supervisor preflight is missing, stale, or contradicted by the current worktree.

1. Start from the previous `open-meta-scan` lane result when present. Prefer `artifacts.meta_scan.raw_ideas`, `artifacts.meta_scan.counterframes`, and `artifacts.meta_scan.routing_hints`; fall back to the lane summary text only when structured artifacts are absent. Choose the best 1-3 ideas for downstream handling.
2. If no prior open-meta-scan result exists because the supervisor plan predates the lane or the lane was blocked, run a short fallback `hops-open-meta-scan` unless a fatal blocker prevents repo inspection.
3. Pass selected raw ideas to `hops-research-improvements` for evidence, anti-myopia routing, park/reject decisions, and candidate queue creation.
4. In target/meta lab repos, prefer `hops lab research-scan`, `hops lab investigate`, or `hops lab classify` before new captures. Create `hops lab capture` only for a reusable failure class, cross-project pattern, or important evaluation gap.
5. Apply a consolidation-first pass before creating new records: prefer extending an existing dossier, adding investigation/classification, parking or rejecting duplicates, or routing to a named existing `FB`/`IMP`/`RS`. Create a new record only when those options would lose important evidence or cross-project reuse.
6. Record selected candidates or research scans so `hops-priority-improvement-steward` can see them through `hops lab review queue --json` and the prior lane summary.
7. In project repos, do not create `harness-lab/`; record observations with `hops feedback add-failure`, route them, and export sanitized feedback when useful.
8. Organize existing lab queue when discovery finds stale classification, missing relation, or duplicate local-only candidates.

# Boundaries

Do not implement feature changes just because an idea looks promising. Leave implementation candidates for `hops-priority-improvement-steward`.

# Output

Return the lane result contract: `status`, `changed_files`, `records_created_or_updated`, `issues_touched`, `validation`, `recommended_next`, and `stop_reason`. Include raw ideas reviewed, selected candidates, and parked/rejected ideas so the supervisor can see the search was real and `hops-priority-improvement-steward` has a clear handoff.
