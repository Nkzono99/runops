---
name: hops-priority-improvement-steward
description: Run the priority improvement lane inside a HOPS daily supervisor. Use for selecting and advancing important recorded HOPS improvements, eval cases, hypotheses, decisions, guards, docs, tests, or repo-native implementation after maintenance, issue, open meta scan, and invention lanes.
---
Use `uvx --from harnessops hops <command>` in target/project repos unless repo-local docs prove `hops` is available.

# Mission

Advance the most important recorded improvement work. Prefer meaningful T2/T3 packets over tiny metadata cleanup when validation is available.

Read `.harnessops/project.toml`. Use `hops` for state changes; do not directly reorganize `.harnessops/`, `harness-feedback/`, or `harness-lab/`.

# Selection

Start with `hops lab review queue --json` in target/meta lab repos. Then inspect recent lane results, including any structured `artifacts.meta_scan` handoff from the open-meta and invention lanes, and the highest-ranked recorded `IMP`, `RS`, `FB`, `E`, `H`, and `D` items. Rank by:

- user-blocking or automation-blocking impact
- cross-project applicability
- clear mechanism and validation path
- ability to add or preserve a guard
- age or repeated recurrence

Do not pick a trivial cleanup merely because it is easiest unless all higher-value candidates are blocked.

# Work

1. For target/meta lab repos, use `hops-run-lab` to create or advance eval cases, hypotheses, manual evals, decisions, and classifications.
2. Before implementation, run `hops lab review context --capability <capability> --json` or another narrow context query to retrieve prior decisions, counterexamples, and guards.
3. Implement selected docs, tests, skill, workflow, CLI, or bridge changes when the implementation gate is met.
4. For project repos, record and export upstream feedback rather than creating adoption decisions.
5. If no implementation is safe, advance the record state: investigation, classification, eval design, park/reject, or explicit blocker.

# Validation

Run focused checks for implementation changes plus `hops doctor --check-overlay --check-records` and `hops migrate --check`.

# Output

Return the lane result contract: `status`, `changed_files`, `records_created_or_updated`, `issues_touched`, `validation`, `recommended_next`, and `stop_reason`.
