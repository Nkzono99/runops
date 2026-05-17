---
name: hops-maintenance-steward
description: Run the maintenance lane inside a HOPS daily supervisor. Use for applying HarnessOps/update-harness changes, doctor/migrate repair, managed artifact drift, generated view refresh, and lab memory maintenance before issue or invention work.
---
Use `uvx --from harnessops hops <command>` in target/project repos unless repo-local docs prove `hops` is available.

# Mission

Handle lifecycle and low-risk maintenance only. Do not triage GitHub issues, invent new improvements, or implement product features.

Read `.harnessops/project.toml`. Use `hops` for state changes; do not directly reorganize `.harnessops/`, `harness-feedback/`, or `harness-lab/`.

# Inputs

Expect the supervisor to provide preflight JSON and runtime policy. Default daily policy is `update-policy: apply`, meaning target/project repos should apply a newer published HarnessOps runtime when update notice, lock drift, managed-file drift, or explicit runtime policy indicates it.

# Work

1. Recheck `hops doctor --check-overlay --check-records` and `hops migrate --check` if the preflight summary is missing or stale.
2. Apply `hops-update-harness` when stale HarnessOps state or `update-policy: apply` is present.
   - In target/project repos, prefer `uvx --refresh-package harnessops --from harnessops hops update-harness --agent-bridge` so `[agents]` selects the repo-local bridge hosts.
   - In HarnessOps core, do not PyPI self-update; treat lifecycle drift as repo-local implementation work for a later lane.
3. For target/meta lab repos, handle safe lab maintenance:
   - run `hops lab memory lint --warn-only` when lab health is missing or stale
   - run `hops lab review lint --warn-only` when queue health or guard completeness is unknown
   - use `hops-compact-lab-memory` only when lint reports `needs-abstraction`
   - refresh generated lab views with HOPS commands when doctor reports managed view warnings
4. Rerun doctor/migrate and any cheap repo-native validation made relevant by the changes.

# Boundaries

Project repos must not create `harness-lab/`. Maintenance may leave nonfatal implementation ideas for `hops-priority-improvement-steward`.

# Output

Return the lane result contract: `status`, `changed_files`, `records_created_or_updated`, `issues_touched`, `validation`, `recommended_next`, and `stop_reason`.
