---
name: hops-finalize-steward
description: Run the finalization lane inside a HOPS daily supervisor. Use after other lanes to validate accumulated changes, publish an automation branch, create or update a PR, wait for required checks, merge, perform authorized issue actions, and release only when explicit criteria are met.
---
Use `uvx --from harnessops hops <command>` in target/project repos unless repo-local docs prove `hops` is available.

# Mission

Finalize accumulated lane work. Do not invent new work in this lane.

Read `.harnessops/project.toml`. Use `hops` for state changes; do not directly reorganize `.harnessops/`, `harness-feedback/`, or `harness-lab/`.

# Validation Gate

If there are changes, run discoverable repo-native tests/lint/build/domain checks plus:

- `hops doctor --check-overlay --check-records`
- `hops migrate --check`

If validation fails, leave the patch local, report `failed-validation`, and do not push.

# Publish And Merge

1. Fetch/prune and confirm the merge target is not behind or diverged.
2. In target/meta repos with GitHub Flow enabled, use:
   - `hops github-flow publish --branch "codex/steward/<YYYYMMDD>-daily" --message "Daily steward automation" --validation-passed`
   - `hops github-flow pr --base <merge-target-branch> --title "Daily steward automation" --body "<summary>"`
   - `hops github-flow merge --require-checks`
3. In repos without GitHub Flow, use the repo-native finalize path documented by that repo; never direct-push a protected base branch.
4. Perform issue close/comment/label actions only when the automation prompt authorizes them and the selected work provides validation evidence.

# Release

Release only when all are true: PR was merged, a repo-local release skill or documented command exists, version/changelog/tag criteria are explicit, required checks passed, the tag does not exist, and release notes are sanitized.

Before release, compare the previous release tag to the release ref. If deleted `harness-lab/records/` or `harness-lab/improvements/` source files exist, run `hops lab archive pack --since-ref <previous-tag> --to-ref <release-ref>` and `hops lab archive verify <zip>`, then attach the zip to the release asset set. Do not archive generated views.

# Output

Return the lane result contract: `status`, `changed_files`, `records_created_or_updated`, `issues_touched`, `validation`, `recommended_next`, and `stop_reason`, plus branch, commit, PR, merge, and release details.
