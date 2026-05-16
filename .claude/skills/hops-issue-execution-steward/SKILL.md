---
name: hops-issue-execution-steward
description: Run the issue lane inside a HOPS daily supervisor. Use for open GitHub issue triage, importing or recording issue context, executing safe issue packets, and preparing authorized issue close/comment/label actions.
---
Use `uvx --from harnessops hops <command>` in target/project repos unless repo-local docs prove `hops` is available.

# Mission

Handle issue intake and execution after maintenance. Do not run broad invention or choose unrelated recorded improvements.

Read `.harnessops/project.toml`. Use `hops` for state changes; do not directly reorganize `.harnessops/`, `harness-feedback/`, or `harness-lab/`.

# Work

1. Use `hops-issue-triage` with no issue argument to discover open issues. Include priority, evidence, missing information, recommended HOPS action, and `remote_action_allowed`.
2. If an issue is actionable:
   - target/meta lab repo: import or capture durable issue context into `harness-lab/`, then create eval/proposal records only when evidence supports it
   - project repo: record observed failure through `harness-feedback/`, route it, and run `hops feedback export --sanitize` when useful
3. Execute one or more safe issue packets when the mechanism and validation path are clear.
4. If no issue is actionable, report `no-op` with triage evidence. Do not replace issue work with maintenance or invention.
5. Close/comment/label issues only when the automation prompt authorizes remote issue actions and validation supports the action.

# Validation

Run focused repo-native checks for executed changes plus `hops doctor --check-overlay --check-records` and `hops migrate --check`.

# Output

Return the lane result contract: `status`, `changed_files`, `records_created_or_updated`, `issues_touched`, `validation`, `recommended_next`, and `stop_reason`.
