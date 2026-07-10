# Notes Research Structure Design

## Context

`project_dust_release` shows the operational shape runops projects drift toward
after long campaigns: daily notes, compact agendas, refined reports, archived
full logs, paper handoff indexes, and cross-run artifact indexes all coexist.
The project should not be edited for this change; it is a read-only example.

## Goal

Make runops scaffold and generated skills steer future projects toward a stable
human-facing directory structure for notes, reports, research decisions, and
cross-run artifacts.

## Chosen Approach

Use the full scaffold + skill + tests approach.

## Directory Contract

```text
notes/
  YYYY-MM-DD.md
  history/YYYY/YYYY-MM-DD.md
  reports/
    README.md
    <topic>.md
    archive/
    figures/

research/
  agenda.md
  paper_requests.toml
  proposals/
  reviews/

analysis/
  cross_run/<comparison_id>/
    README.md
    data/
    figures/
    reports/
    scripts/
    logs/
```

## Rules

- `notes/YYYY-MM-DD.md` is append-only chronological work log.
- `notes/history/` stores archived daily logs and recovery-only full logs.
- `notes/reports/README.md` is the human reading-order index.
- `notes/reports/<topic>.md` is refined prose and can be rewritten.
- `notes/reports/archive/` stores old/full/recovery-only reports.
- `notes/reports/figures/` stores report-owned representative figures.
- `research/agenda.md` is a compact current decision ledger, not an artifact
  ledger or chronological notebook.
- `research/proposals/` is for high-cost or direction-changing pre-run
  decisions.
- `research/reviews/` is for checkpoint snapshots, pivot/pause/kill decisions,
  and major result reviews.
- `analysis/cross_run/<comparison_id>/` stores machine-readable cross-run
  artifacts, scripts, logs, and generated figures.
- Human-facing notes and reports should embed representative figures with
  Markdown image syntax instead of only listing links.

## Implementation Scope

- Add a scaffolded `notes/reports/README.md` template.
- Extend scaffold creation to create `notes/reports/archive/` and
  `notes/reports/figures/`.
- Extend notes, research-agenda, and summarize-script skills to route content
  into the right layer.
- Update init and harness tests so generated guidance preserves this structure.

## Out of Scope

- Do not edit `<external-read-only-project>`.
- Do not migrate existing project files.
- Do not add a new CLI compaction command in this slice.
