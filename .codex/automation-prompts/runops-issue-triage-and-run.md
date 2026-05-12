# runops issue triage automation

This is the canonical handoff prompt for the local Codex Automation
`runops-issue-triage-and-run`. The Automation registration should stay short
and point here so workflow changes can be reviewed in Git.

## Goal

Keep `Nkzono99/runops` issues triaged and close small, actionable loops end to
end: pull, triage, implement, verify, commit, and push. Prefer doing useful
maintenance over writing a long report, but do not hide blockers.

## Required Context

- Use `$triage`.
- Use `$harnessops-bridge` and `$hops-update-harness` when touching or
  validating HarnessOps-managed files.
- Treat `AGENTS.md`, `SPEC.md`, `.codex/README.md`, and `.agents/skills/triage/SKILL.md`
  as policy.
- Read automation memory first:
  `$CODEX_HOME/automations/runops-issue-triage-and-run/memory.md`.
  If `$CODEX_HOME` is unset, use `%USERPROFILE%\.codex`.
- Before returning, append a concise memory entry with the current run time,
  what was triaged, what was changed, what was pushed, and any blocker.

## Startup

1. Inspect `git status --short --branch`.
2. Do not overwrite or stage unrelated user changes. If unrelated changes are
   present, keep them out of commits and mention them in the final summary.
3. Run `git pull --ff-only --autostash`.
4. Confirm GitHub access with `gh auth status`.
5. List open issues:
   `gh issue list --repo Nkzono99/runops --state open --limit 30 --json number,title,labels,updatedAt,createdAt,author,url,body`.

## HarnessOps Update

The latest `$triage` workflow can import durable improvement candidates into
HarnessOps. Each automation run should also pull the repository forward to the
current HarnessOps scaffold before issue work starts.

1. Resolve the HarnessOps command:
   use `hops` when it is on `PATH`; otherwise use
   `uv run --with-editable . hops`.
2. Run:
   `<hops> doctor --check-overlay --check-records`
   and `<hops> migrate --check`.
3. Run:
   `<hops> update-harness --agent-bridge --codex`.
4. If HarnessOps creates managed-file updates or `.new` files, inspect them.
   Commit safe, direct scaffold updates after validation. Do not use `--force`
   or hand-edit `.harnessops/`, `harness-feedback/`, or `harness-lab/records/`
   unless a human explicitly asks for that.
5. If both `hops` and the `uv run --with-editable . hops` fallback fail,
   continue GitHub issue triage and report `hops unavailable`.
6. For valid recurring harness or workflow improvement issues, use
   `hops feedback import --issue <NUMBER> --repo Nkzono99/runops` when possible.

## Triage Policy

For each open issue, evaluate validity, reproducibility, impact, difficulty,
duplicates, and whether the request is already implemented.

- Close only obvious spam, malicious, abusive, or unrelated issues without
  user confirmation, and always leave a clear close comment.
- Do not close legitimate issues just because they are vague. Comment or report
  what information is missing.
- Prefer fixing small, well-scoped issues in the same run.
- Defer large architecture changes, ambiguous product decisions, risky data
  migrations, and HPC-resource-affecting behavior unless the issue is already
  very specific and low-risk.

## Implementation Policy

When an issue is small and actionable:

1. Inspect the relevant code and tests before editing.
2. Make the smallest coherent change that follows existing repo patterns.
3. Update focused tests or docs when the behavior changes.
4. Run focused validation appropriate to the change:
   `git diff --check`, relevant `uv run pytest ...`, relevant `uv run ruff check ...`,
   and TOML parsing for TOML-only changes.
5. Commit with an English message and include `Closes #N` when the issue is
   fully fixed.
6. Push only commits created by this automation run, or commits already
   documented in memory as pending automation work. Do not push unrelated local
   commits silently.

If validation fails and cannot be fixed quickly, leave the working tree in a
clear state, do not push broken work, and report the failing command and next
step.

## No-Issue Run

If there are no open issues:

1. Do not invent code changes.
2. Push only if there is an already-created automation commit that clearly
   belongs to this workflow and is safe to publish.
3. Record the no-op triage result in memory.

## Final Response

Report the result concisely in Japanese:

- pull status
- issue count and triage result
- HarnessOps update status
- changes made
- validation run
- commit and push status
- blockers, especially `hops` or GitHub auth issues

End with exactly one `::inbox-item{...}` directive.
