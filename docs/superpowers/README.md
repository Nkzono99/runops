# Design and implementation records

`docs/superpowers/` contains approved design snapshots and execution plans. These
files explain why and how a change was built; they are not the current product
specification or a general TODO backlog.

Normative behavior belongs in `SPEC.md`, `.codex/rules/*.md`, and the relevant
topic documentation under `docs/`. When a plan and a normative document differ,
the normative document wins.

## Lifecycle

Every file under `plans/` declares one status near the title:

- `active`: implementation or verification is still in progress.
- `completed`: the plan is historical and has an `Outcome` naming the result or
  implementing commit(s).
- `superseded`: a newer named plan or decision replaced it.

Checkboxes are execution-time notes. Unchecked boxes in a completed plan do not
reopen work; `Status` is authoritative. New follow-up findings belong in a new
plan or the project issue/feedback workflow, with a link back to the historical
record.

## Portability

Plans and design snapshots use repository-relative paths and placeholders such
as `<repo-root>` or `<external-read-only-project>`. User names, checkout roots,
login hosts, temporary directories, and other machine-specific absolute paths
must not be committed.
