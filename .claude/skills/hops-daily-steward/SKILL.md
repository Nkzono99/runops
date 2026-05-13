---
name: hops-daily-steward
description: Run the unattended HarnessOps daily improvement loop for HarnessOps core, target repositories, or project repositories. Sync a clean repo, inspect issue/feedback/lab/doctor state, delegate to existing HOPS skills, and autonomously advance role-appropriate local improvements through evidence/test/guard gates. Use for daily steward, scheduled HarnessOps maintenance, automatic improvement loop, or daily issue + feedback/lab advancement. Remote actions follow explicit automation prompt authorization.
---
Use `uvx --from harnessops hops <command>` for CLI invocations in target/project repos; do not rely on `hops` being on PATH.

# Intent

Run one bounded HarnessOps improvement cycle.

This skill is a compact steward / conductor, not a new workflow engine:

- sync the repo safely
- detect repo role from `.harnessops/project.toml`
- read current HOPS state
- route work to existing skills
- select at most one systemic candidate
- advance local work when automated gates pass
- report actions, blockers, and human decisions

Default automation mode is `advance-local`.

Human review is not required for local advance, but automated gates are mandatory.

Use `hops` for HarnessOps state changes. Do not directly reorganize `.harnessops/`, `harness-feedback/`, or `harness-lab/`.

# Repo Role Routing

Read `.harnessops/project.toml` before choosing write paths.

| Repo role | Allowed HOPS direction |
|---|---|
| HarnessOps core / target / meta lab repo | Use `harness-lab/` via `hops feedback import`, `hops lab ...`, `hops propose`, `hops eval`, and `hops decide`. |
| project repo | Use `harness-feedback/` via `hops add-failure`, `hops route`, `hops add-feedback`, and `hops feedback export --sanitize`. Do not create `harness-lab/`. |
| unknown repo role | Stop and report the missing role context. |

Do not assume this is the HarnessOps implementation repository. Use repo-native validation, branch, release, and issue conventions from the target/project repo. The HarnessOps repo-local `release` skill is only available when that repo provides it.

# Non-Negotiable Gates

Stop before HOPS state change, implementation, or `hops update-harness` when any condition is true:

- worktree is dirty before sync
- branch is diverged, untracked, or `git pull --ff-only` fails
- repo role cannot be determined from `.harnessops/project.toml`
- `hops doctor --check-overlay --check-records` fails
- project repository would require `harness-lab/`
- target/meta lab repository would require project-local `harness-feedback/`
- candidate lacks evidence refs
- candidate lacks validation command or guard plan
- privacy or project-specific contamination is possible
- requested remote action is not authorized by the automation prompt or direct human instruction

Do not run stash, reset, rebase, force pull, push, PR creation, issue comment/close/create, or release without explicit automation prompt authorization or direct human confirmation.

# Sync Gate

For scheduled automation, delegate routine intake to CLI:

```bash
hops steward preflight --pull --json
```

If `can_continue` is false, stop and report. This command performs pull-first safety, doctor/check-records, migrate check, overlay counts, lane trigger scaffold, subagent plan scaffold, and run ledger creation.

Manual fallback only when the CLI is unavailable:

1. Read `.harnessops/project.toml`.
2. Run `git status --short --branch`.
3. If clean and tracking remote exists, run `git fetch --prune` then `git pull --ff-only`.
4. If dirty, diverged, conflicted, or pull fails, stop.
5. Run `hops doctor --check-overlay --check-records` and `hops migrate --check`.

# Delegation

Use subagents when the automation prompt explicitly allows them. Otherwise run the same lanes sequentially with isolated sections. Pass minimal context.

| Need | Delegate |
|---|---|
| issue / feedback triage | `hops-issue-triage`, `hops-import-feedback`, `hops-route-feedback` |
| open divergent invention lane | `hops-open-meta-scan` |
| evidence, routing, park/reject, selection | `hops-research-improvements` |
| eval case, hypothesis, manual eval, decision, guard | `hops-run-lab` |
| managed file drift / bridge / update | `hops-update-harness` |
| lab memory pressure | `hops-compact-lab-memory` |

Do not let the open invention lane read existing lab memory unless it is explicitly acting as librarian.

# Triggers

Always:

- intake from `hops steward preflight --pull --json`
- issue / feedback triage when inputs exist
- doctor / update state check
- critic before any write or decision

Conditional:

- `hops-open-meta-scan`: explicit request, weekly run, repo-native release prep, repeated friction, issue cluster, or loop stagnation
- `hops-research-improvements`: raw ideas, open issues, or feedback require routing
- `hops-run-lab`: candidate is ready for E/H/D or guard work
- `hops-update-harness`: doctor/update/bridge signals exist

Weekly:

- loop-auditor for steward self-improvement
- do not change the steward daily unless a strong failure signal exists

# Selection Rules

- New systemic candidate: max 1 per run.
- Existing dossier notes: max 1-3 per run.
- Raw Ideas are ephemeral; do not capture them directly.
- Prefer existing issue / dossier / record over new records.
- `park`, `reject`, `local-only`, and no-op are valid outcomes.
- Do not advance project-specific private context into target/core lab.
- In project repos, convert observations to sanitized feedback/export candidates rather than lab decisions.

# Advance-Local

When gates pass, local advance may perform role-appropriate actions.

Project repositories may perform:

- `hops add-failure`
- `hops route`
- `hops add-feedback`
- `hops feedback export --sanitize`
- project-local code / docs / skill edits for the selected candidate

HarnessOps core, target, and meta lab repositories may perform:

- `hops feedback import`
- `hops lab investigate`
- `hops lab classify`
- `hops lab research-scan`
- `hops lab capture`
- `hops lab new-eval-case`
- `hops propose`
- `hops eval --manual`
- `hops decide`
- `hops-update-harness` skill or `uvx --refresh-package harnessops --from harnessops hops update-harness`
- code / docs / skill edits for the selected candidate
- validation commands, including tests and doctor checks

Adopted decisions must include evidence, regression risk, guard path or guard plan, validation result, and kill criteria when applicable.

# End-Of-Run Policy

If local changes were made, run validation and then choose one policy from the automation prompt:

- `patch-only`: leave the patch in the worktree and report that the next scheduled run will stop until reviewed.
- `commit-local`: after validation passes, create a local automation branch or commit on the authorized branch.

Use CLI for the mechanical ending:

```bash
hops steward finalize --policy patch-only --json
hops steward finalize --policy commit-local --validation-passed --json
```

If the automation prompt does not specify a policy, default to `patch-only`.

Push, PR, issue, and release actions are outside `hops steward finalize`; run them only when the automation prompt explicitly authorizes them and after validation plus a final remote divergence check.

# Decision Card

Each lane returns a compact card:

```yaml
lane:
action: advance | investigate | classify | capture | update-harness | park | reject | no-op | human-review
target:
evidence:
risk:
command:
stop_reason:
```

# Report

Return a concise daily report:

- mode and repo role
- sync / doctor result
- intake summary
- selected candidate or no-op rationale
- actions performed
- validation result
- local changes / local commit state
- remote actions performed or skipped by policy
- blocked or parked items
- remote actions requiring confirmation
- run ledger: branch, start_sha, head_sha, pull_status, issue_snapshot
