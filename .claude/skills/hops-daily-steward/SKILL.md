---
name: hops-daily-steward
description: Run the unattended HarnessOps improvement loop. Preflight a clean repo, discover or select work, delegate to HOPS skills, advance role-appropriate changes, and use the automation prompt's remote authority for PR/merge/issue/release actions. Remote actions follow explicit automation prompt authorization.
---
Use `uvx --from harnessops hops <command>` in target/project repos unless repo-local docs prove `hops` is available.

# Mission

Run one bounded improvement cycle as a steward / conductor.

The steward must not stop at status reporting when the repo is clean and automation authority is available. If no reactive work exists, run proactive discovery and build or advance a candidate queue.

Use `hops` for HarnessOps state changes. Do not directly reorganize `.harnessops/`, `harness-feedback/`, or `harness-lab/`.

# Global Gates

Stop before any write when:

- worktree is dirty at start
- branch is diverged or pull/preflight fails
- repo role cannot be read from `.harnessops/project.toml`
- `hops doctor --check-overlay --check-records` has a fatal failure
- privacy or project-specific contamination is possible
- requested remote action is not authorized by the automation prompt or direct human instruction

Do not stash, reset, rebase, force-push, force-pull, or direct-push a protected base branch unless explicitly authorized.

# Role Routing

Read `.harnessops/project.toml` before choosing write paths.

- HarnessOps core / target / meta lab repo: use `harness-lab/` through `hops lab ...`, `hops propose`, `hops eval`, and `hops decide`.
- Project repo: use `harness-feedback/` through `hops add-failure`, `hops route`, `hops add-feedback`, and `hops feedback export --sanitize`.
- Project repos must not create `harness-lab/`.
- Unknown repo role: stop and report the missing role context.

# Gate Levels

Record gate:

- for research-scan, investigate, classify, feedback, and issue draft work
- requires a concrete observation, evidence ref, or explicit hypothesis
- does not require full validation or a guard yet

Implementation gate:

- for code, docs, skill, workflow, bridge, or managed-artifact edits
- requires a validation command or validation gap statement
- requires a guard plan when behavior changes

Merge gate:

- for PR merge, issue close, and release
- requires validation passed, no conflict, and repo policy / required checks satisfied

# Lane Order

1. Preflight: run `hops steward preflight --pull --json`.
2. Intake: read issues, feedback, lab health, doctor/update signals, and existing queue state.
3. Reactive work: handle issue/feedback/doctor/update/lab-health signals first.
4. Queue work: if a candidate queue exists, select work packets within the risk budget.
5. Proactive discovery: if no reactive work exists or the queue is thin, run `hops-open-meta-scan`.
6. Selection: use `hops-research-improvements` for evidence, routing, park/reject, queueing, and ranked candidates.
7. Execution: use `hops-run-lab`, `hops-update-harness`, `hops-compact-lab-memory`, or repo-native edits for selected work packets.
8. Validation: run repo-native tests/checks plus `hops doctor --check-overlay --check-records` and `hops migrate --check`.
9. Finalize: commit, PR, merge, issue, and release only as authorized by the automation prompt.

# Update Lane

Do not start every daily run by updating HarnessOps to the latest release. Treat updates as signal-driven work:

- Target/project repos: run `hops-update-harness` or `uvx --refresh-package harnessops --from harnessops hops update-harness` only when preflight, doctor, update notice, lock drift, managed-file drift, or explicit runtime policy shows stale HarnessOps state.
- HarnessOps core repo: treat this as repo-local implementation/release work, not PyPI self-update.
- After update-harness work, rerun doctor, migrate check, and relevant repo-native validation before merge.

# Work Budgets

Use runtime config if provided. Otherwise:

- discovery cards: 8
- recordable candidates: 5
- low-risk work packets: 5
- medium-risk work packets: 3
- high-risk work packets: 1

Risk tiers:

- T0: read-only routing / park / reject
- T1: lab/feedback metadata, research-scan, investigate, classify
- T2: docs, tests, skill wording, diagnostics
- T3: CLI behavior, workflow, update-harness, lab lifecycle
- T4: evaluator changes, guard weakening, release policy, protected-branch policy

T4 requires separate treatment or explicit high-risk authorization. Candidate count is not the primary limit; risk tier and work-packet budget are.

# No-Idle Policy

If global gates pass, do not end with status-only no-op until at least one of these has been attempted:

- process reactive issue/feedback/update/lab-health work
- advance an existing queued candidate
- run `hops-open-meta-scan` and create discovery cards
- promote selected cards to research-scan / feedback / issue / work packet
- perform safe metadata, guard, docs, tests, skill, or diagnostic cleanup

No-op is valid only with a concrete blocker, failed validation, exhausted budget, or explicit discovery failure.

# Delegation

Use subagents when available and authorized:

- issue triage: `hops-issue-triage`
- invention: `hops-open-meta-scan`
- evidence/routing: `hops-research-improvements`
- eval/decision/guard: `hops-run-lab`
- update/bridge: `hops-update-harness`
- memory: `hops-compact-lab-memory`

Pass minimal context. Do not let invention read lab memory unless acting as librarian.

# Output

Report:

- mode, role, branch, sync result
- work generated
- work advanced
- validation result
- commits / PRs / merges / issue actions / release actions
- parked / rejected / blocked items
- remaining queue
- human decisions, if any
