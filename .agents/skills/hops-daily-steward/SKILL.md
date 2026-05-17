---
name: hops-daily-steward
description: Run one unattended HarnessOps daily automation as a thin supervisor. Use when Codex should pull/preflight a clean repo, then sequentially delegate maintenance, issue execution, open meta scan, invention/lab organization, priority improvement execution, and PR/merge finalization to lane-specific HOPS skills without doing lane work directly.
---
Use `uvx --from harnessops hops <command>` in target/project repos unless repo-local docs prove `hops` is available.

# Mission

Supervise one daily run. Keep this skill small: the supervisor owns order, gates, delegation, and final synthesis. It must not perform maintenance, issue work, open meta scanning, invention, implementation, lab evaluation, PR creation, merge, or release directly.

Read `.harnessops/project.toml` before delegation. State changes must go through `hops`; do not directly reorganize `.harnessops/`, `harness-feedback/`, or `harness-lab/`.

# Start Gate

1. Ensure the worktree is clean and switch to the configured base branch if needed.
2. Run `hops steward run start --pull --json`, adding `--update-policy apply` when runtime policy requests automatic HarnessOps updates.
3. Stop before HOPS state changes when the returned preflight has `can_continue=false`, the repo role is unknown, privacy risk is present, or the automation prompt does not authorize the needed remote action.

If preflight output is unavailable, run `hops doctor --check-overlay --check-records` and `hops migrate --check` before delegation.

Never stash, reset, rebase, force-push, force-pull, or direct-push a protected base branch unless explicitly authorized.

# Supervisor Contract

Use `supervisor_plan` and `run_id` from `hops steward run start` as the source of truth for lane order, lane handoff text, update policy, and the lane result contract.

For each `supervisor_plan.lanes[]` item, spawn one subagent when subagents are available and authorized. Wait for its final report before starting the next lane. If subagents are unavailable, use an inline fallback and run the lane skill one at a time; report `inline_fallback=true`.

After each lane, validate and persist its result with `hops steward run record-lane-result --run-id <run_id> --lane <lane>`. End the ledger with `hops steward run end --run-id <run_id> --status <status>`.

The supervisor should pass only:

- runtime authority and branch policy from the automation prompt
- `.harnessops/project.toml` role summary
- preflight JSON or prior lane result summaries
- current dirty/branch state when relevant

Do not read each lane skill body up front. The lane agent reads its own skill.

If a lane reports `blocked`, decide whether the blocker is fatal. Nonfatal blockers should be recorded in the final report and later lanes should continue.

# Output

Report mode, repo role, branch/sync result, lane results, validation, commits/PRs/merges/issue actions/release actions, blockers, remaining queue, and human decisions.
