# Story Acceptance Audit Design

## Context

Issue #107 asks runops to help verify whether a research campaign satisfies the
user's intended scientific story, not merely whether many analysis artifacts
exist. Existing runops layers already provide run-local summaries,
`analysis/artifacts.toml`, survey `summary/` outputs, cross-run comparison
workspaces, research notes, and publication exports. The missing layer is a
project-level acceptance audit that maps narrative claims to concrete evidence
and exposes missing or weak links.

This feature should not try to prove scientific correctness. It should make the
evidence contract explicit so humans and agents can see which artifacts support
which story steps, which artifacts are stale or screening-only, and what remains
missing before a result is treated as complete.

## Goals

- Add a first-class project-level workspace for story acceptance audits under
  `analysis/stories/<story_id>/`.
- Keep `research/agenda.md` compact by moving detailed evidence inventories into
  story audit reports.
- Reuse existing runops artifact indexes and summaries instead of inventing a
  separate artifact database.
- Produce both machine-readable and human-readable audit outputs.
- Make the initial implementation deterministic and conservative: classify
  evidence coverage from explicit metadata and file indexes, not from AI
  interpretation.

## Non-Goals

- Do not automatically judge physics validity or manuscript readiness.
- Do not require a database or web UI.
- Do not replace `analysis/cross_run/`; story audits may reference comparison
  workspaces as evidence sources.
- Do not make the story schema a public v1 contract before it has been exercised
  on real projects.

## Proposed User Model

Create a story workspace:

```bash
runo analyze new-story surface-adhesion-scaling --source runs/sheath_scan
```

Audit it after editing the generated `story.toml`:

```bash
runo analyze audit-story analysis/stories/surface-adhesion-scaling
```

Generated files:

```text
analysis/stories/<story_id>/
  story.toml
  audit.json
  audit.md
```

The initial CLI exposes `runo analyze new-story` plus
`runo analyze audit-story` while keeping the same workspace layout.

## Story Schema

`story.toml` is a user-editable spec. A minimal example:

```toml
schema_version = 1
id = "surface-adhesion-scaling"
title = "Surface potential to adhesion and scaling story"
status = "draft"

[[sources]]
kind = "survey"
path = "runs/sheath_scan"

[[steps]]
id = "surface-potential"
title = "Surface-potential visualization"
required_artifacts = ["figure:surface_potential", "table:surface_metrics"]
acceptable_status = ["main", "accepted", "draft"]
claim_ceiling = "static field evidence; not dynamic adhesion proof"

[[steps]]
id = "force-time"
title = "Force-time history"
required_artifacts = ["figure:force_time", "data:force_timeseries"]
acceptable_status = ["main", "accepted"]
claim_ceiling = "requires matching snapshot convention with velocity analysis"
```

The first schema should support:

- `sources[]`: run, survey, path, or cross-run comparison source.
- `steps[]`: narrative steps with stable ids and short titles.
- `required_artifacts`: explicit artifact selectors.
- `acceptable_status`: allowed artifact maturity/status labels.
- `claim_ceiling`: human-written limit on what the evidence can claim.
- `notes`: optional context for the auditor and future readers.

Artifact selectors should start simple. A selector can match kind and a tag-like
field, for example `figure:surface_potential`. Unknown selector fields should be
reported as missing rather than treated as errors.

## Audit Output

`audit.json` should contain:

- story metadata and generation timestamp;
- resolved sources and any source-read warnings;
- one result per story step;
- matched artifacts with path, kind, title, status, source scope, and provenance
  where available;
- missing required artifacts;
- weak evidence where artifacts exist but status is outside
  `acceptable_status`;
- claim ceilings copied from the story spec;
- overall status: `covered`, `partial`, `missing`, or `blocked`.

`audit.md` should be a concise report for humans and agents. It should lead with
overall status, then list each step with covered evidence, weak/missing items,
and next action. It should not copy large external reports or logs.

## Data Flow

1. Resolve the story workspace and load `story.toml`.
2. Resolve each source relative to the project root.
3. Collect artifact indexes from:
   - run-local `analysis/artifacts.toml`;
   - survey `summary/artifacts.toml`;
   - `analysis/cross_run/<id>/manifest.toml` artifact lists when present;
   - publication export manifests in a later phase.
4. Normalize artifact records into a small internal model.
5. Match each step's `required_artifacts` against normalized artifacts.
6. Compute per-step and overall audit status.
7. Write `audit.json` and `audit.md`.

The core logic belongs under `src/runops/core/analysis/` so the CLI remains a
thin wrapper. CLI code should only resolve paths, call the core action, and
print generated output locations.

## Error Handling

- Missing `story.toml`: fail with a clear message.
- Invalid TOML or duplicate step ids: fail before writing audit outputs.
- Missing source path: report the source as blocked and keep auditing other
  sources when possible.
- Missing artifact index: warn and continue; the resulting step can become
  `missing` or `partial`.
- Unknown artifact selector syntax: treat that selector as missing and include a
  warning in both outputs.
- Existing `audit.json` / `audit.md`: overwrite only after the audit computation
  succeeds.

## Relationship To Existing Layers

- `analysis/artifacts.toml` remains the source of artifact metadata.
- `analysis/cross_run/` remains the workspace for comparison scripts, figures,
  and intermediate data.
- `analysis/stories/` is an acceptance layer that references artifacts from
  runs, surveys, and comparisons.
- `research/agenda.md` should link to the current story audit instead of
  embedding long evidence inventories.
- Publication export can later include `analysis/stories/<story_id>/audit.*` as
  paper-facing acceptance evidence.

## Implementation Slices

1. Document and scaffold `analysis/stories/<story_id>/story.toml`.
2. Implement deterministic artifact collection and selector matching for run and
   survey artifact indexes.
3. Generate `audit.json` and `audit.md`.
4. Add cross-run comparison source support.
5. Add publication export inclusion and richer lint checks once the schema has
   been used on real projects.

## Testing

- Unit tests for story TOML parsing, duplicate ids, and selector parsing.
- Unit tests for matching required artifacts against normalized artifact records.
- Workflow tests for `runo analyze audit-story` on a fixture project with:
  - a fully covered step;
  - a missing artifact;
  - a weak artifact status;
  - a missing source path.
- CLI tests should assert exit codes and generated output paths without relying
  on HPC execution.

## Initial Decisions

- Use a flat initial CLI: `runo analyze new-story` and
  `runo analyze audit-story`. This matches the current `analyze.py` command
  shape and avoids adding nested Typer plumbing for the first slice.
- Keep artifact selectors string-based for v0, using `kind:name` syntax such as
  `figure:surface_potential`. Structured TOML selectors can be added later
  without changing the workspace layout.
- Recommend a small maturity vocabulary in templates: `main`, `accepted`,
  `draft`, `sensitivity`, `caveat`, `screening`, `stale`, and `excluded`. The
  auditor should still accept project-specific labels and classify them by
  `acceptable_status` rather than by a hard-coded global list.
