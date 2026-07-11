# Agent Routine CLI Redesign

**Status:** approved
**Date:** 2026-07-11

## Purpose

Move deterministic research-operation work out of generated Agent skills and
into typed runops models and intuitive CLI commands. Agents and humans retain
scientific judgment; runops owns identifiers, validation, state projection,
cost and scope checks, execution plans, and repeatable filesystem operations.

This is a target-model redesign implemented in vertical slices. It is not a
general workflow engine and does not automatically choose hypotheses, candidate
experiments, or scientific decisions.

## Design principles

1. One source of truth for each kind of state.
2. Derived phase and readiness are computed, not copied between files.
3. Mutating commands use an internal plan/apply boundary and stale-plan check.
4. Read commands never mutate unless an explicit `--refresh` is supplied.
5. `--dry-run`, `--yes`, and `--json` have consistent meanings.
6. High-cost or destructive work fails closed and cannot be bypassed by
   decomposing a bulk operation into smaller Agent-issued commands.
7. Existing common commands remain compatibility and low-level escape paths.

## State ownership

```text
Experiment intent
  research/experiments.toml
          |
          v
Survey execution plan
  survey.toml
          |
          v
Run execution state
  manifest.toml
          |
          v
Artifact readiness
  analysis/summary.json + artifacts.toml
```

### Experiment

The experiment ledger owns stable experiment identity, title/question,
candidate comparison, selected candidate, cost ceiling, proposal reference,
scientific decision, review reference, and authorized scope. It does not own
Slurm or run lifecycle state.

`research/experiments.toml` evolves to schema version 2. A record that can be
prepared contains:

- stable `id`, display `title`, and active `question`;
- at least two candidates with information gain, falsification value, estimated
  core-hours, and operational risk;
- `selected_candidate`, `proposal`, `decision`, optional `review`, and cost
  ceiling;
- optional authorization containing stage, survey path, review path, and
  maximum core-hours.

Migration may preserve an incomplete legacy record with explicit blockers, but
ordinary `experiment new` never creates placeholder scientific values.

The persisted decision remains `WAIT`, `EXPAND`, `REVISE`, or `STOP`. A phase
such as `pilot-ready`, `pilot-active`, `review-pending`, or `full-active` is a
projection derived from the ledger, referenced surveys, run manifests, and
artifact indexes. Phase is never written back as a second source of truth.

### Survey

`survey.toml [research]` references an experiment, selected candidate, and
`stage = "pilot" | "full"`. A prepared pilot or full survey is one explicit
parameter matrix; its generated run set is derived from origin metadata in run
manifests rather than copied into the experiment ledger.

### Run

`manifest.toml` remains the sole source of run identity, state, scheduler
attempts, provenance, and origin. Experiment commands call existing run
creation, submission, synchronization, and lifecycle application services.

### Artifact

Analysis summaries and artifact indexes own mechanical readiness. Experiment
status reports required, present, missing, and stale artifacts without copying
their inventories into the ledger or agenda.

### Narrative documents

`research/agenda.md`, proposals, and reviews explain evidence and reasoning.
They are attachments, not machine gates. The CLI validates their paths and
links them to structured records; it does not parse a magic Markdown string
such as `Decision: EXPAND` as authorization.

## Canonical CLI

### Experiment lifecycle

```bash
runo experiment new NAME [--from SPEC]
runo experiment show [EXPERIMENT] [--json]
runo experiment check [EXPERIMENT] [--json]
runo experiment prepare EXPERIMENT --survey DIR --stage pilot|full [--dry-run]
runo experiment decide EXPERIMENT EXPAND --review FILE --survey DIR \
  --max-core-hours N [--dry-run]
runo experiment submit EXPERIMENT --stage pilot|full [--dry-run] [--yes]
```

- `new` plans and creates one complete structured record and proposal template.
  In a terminal it uses a guided prompt; `--from` accepts a typed TOML/JSON
  specification for non-interactive Agent use.
- `show` returns the derived phase, candidate and budget summary, survey/run
  counts, artifact readiness, blockers, and exact next commands.
- `check` validates cross-file integrity without mutation.
- `prepare` validates survey linkage, expands the matrix, identifies the exact
  run set, and reports total cost and authorized scope.
- `decide` records a supplied human/Agent decision. `EXPAND` requires a review,
  complete pilot evidence, explicit full survey scope, and cost ceiling. Other
  decisions reject full-scope options. The CLI validates the decision but never
  invents it.
- `submit` resolves the prepared run set and delegates to existing per-run
  submission services after stage, budget, review, and stale-state validation.

### Run overview

```bash
runo runs overview [TARGET] [--refresh] [--json]
```

Without `--refresh`, overview is read-only. With it, scheduler state is synced
before projection. Output includes lifecycle counts, current attempts, adapter
progress, last activity age, failed reasons, artifact readiness, and hang
candidates. A hang candidate is advisory and never changes state or cancels a
job automatically.

### Analysis build

```bash
runo analyze build TARGET [--dry-run] [--yes] [--json]
```

The command computes an idempotent analysis plan and performs only missing or
stale deterministic steps: per-run summarize, survey collect, configured plot
recipes, and artifact-index generation. Custom scientific interpretation and
new analysis-script authoring remain Agent/human work.

### Lifecycle cleanup

```bash
runo runs cleanup TARGET [--dry-run] [--yes] [--json]
```

Cleanup projects legal archive and purge candidates from run state, storage,
and current submission claims. It never deletes completed or archived run
directories. Existing `archive`, `purge-work`, `cancel`, and `delete` remain
explicit low-level commands.

## Common command behavior

- Read-only commands use no confirmation and have no hidden writes.
- Mutating commands create an immutable plan containing target identities,
  expected states, paths, cost, warnings, and effects.
- `--dry-run` renders that same plan and never applies it.
- The default interactive path renders the plan and asks once when confirmation
  is required.
- `--yes` skips only the prompt; it cannot skip scientific, cost, state, or
  safety gates.
- `--json` uses versioned envelopes containing `status`, `data`, `warnings`,
  `blockers`, and `next_actions`. Effectful JSON commands still require `--yes`
  or remain dry-run.
- Every effectful canonical command receives ActionSpec, CLI operation, and MCP
  metadata bindings even if its first public interface is CLI-only.

## Data flow and failure handling

### Plan and stale validation

Plans capture experiment ID, ledger identity, survey identity, selected
candidate, decision/review authorization, run IDs and states, estimated cost,
and artifact fingerprints. Apply re-reads all governed sources before the first
effect and reports a typed stale-plan error on any change.

### Multi-file creation

`experiment new` stages the proposal and ledger update, validates both, and
publishes them with rollback before reporting success. Existing user files are
never overwritten. A recovery path is reported if rollback cannot complete.

### Bulk submission

Bulk submit is not transactional after scheduler acceptance. Results explicitly
classify submitted, skipped, rejected, outcome-unknown, and not-attempted runs.
An unknown scheduler outcome stops further submission and keeps the existing
fail-closed claim semantics. The command never retries or falls back to
individual submission automatically.

### Analysis and cleanup

Analysis writes continue to use staging and atomic publication. Cleanup
revalidates run state and submission claim immediately before each operation,
returns partial completion explicitly, and never widens its target set during
apply.

### Operational records

Run manifests remain the authoritative submission record. Experiment commands
may append a concise notebook/event summary after successful effects, but a
secondary note failure is a warning and cannot make scheduler acceptance
ambiguous.

## Compatibility and migration

- Existing `runs sweep`, `runs submit`, `runs sync`, `analyze summarize`,
  `analyze collect`, `runs archive`, and `runs purge-work` remain supported.
- Generated skills migrate to canonical commands while retaining scientific
  judgment, evidence review, and simulator-specific work.
- A versioned project-state migration upgrades experiment ledger schema 1 to 2
  without inventing missing scientific values. Records requiring human input
  remain valid but blocked with explicit fields to complete.
- Markdown `Decision:` parsing remains a compatibility read path during the v0
  migration window but cannot create new authorization after schema 2 is
  applied.
- CLI aliases are documented in `docs/migrations/v0.md`; no force migration is
  performed during ordinary commands.

## Harness simplification

After each canonical command ships, generated skills stop reproducing its shell
loops or editing its machine state directly:

- `check-status` calls `runs overview` and interprets warnings;
- `run-all` calls experiment prepare/show/submit and handles human approval;
- `review-pilot` evaluates evidence, then records the supplied decision through
  `experiment decide`;
- `analyze` calls `analyze build` before scientific interpretation;
- `cleanup` calls `runs cleanup` and explains destructive choices.

Skills continue to explain scientific judgment, escalation, and simulator
plugin delegation. They do not become alternate implementations of runops.

## Implementation slices

1. Experiment schema 2, projection, integrity checker, migration, and
   `experiment new/show/check`.
2. Experiment prepare/decide/submit and structured authorization.
3. Run overview and adapter-neutral health projection.
4. Idempotent analysis build.
5. Modeled cleanup plan/apply.
6. Generated-harness simplification, command documentation, and compatibility
   migration notes.

Each slice preserves a usable repository and passes the full quality gate before
the next begins.

## Testing and acceptance

- Unit tests cover experiment parsing, derived phase, blockers, next actions,
  budget and authorization gates, health projection, analysis planning, and
  cleanup planning.
- Failure-injection tests cover stale plans, multi-file rollback, partial bulk
  submission, outcome-unknown claims, atomic analysis publication, and cleanup
  state races.
- CLI tests freeze human and JSON output contracts, dry-run behavior,
  confirmation semantics, and compatibility paths.
- Migration tests cover complete schema-1 records, incomplete records, repeated
  application, and preservation of unknown fields.
- Harness tests prove generated skills use canonical commands and no longer
  contain replaced shell loops or direct structured-state edits.
- Ruff format/check, strict mypy, full branch coverage, and critical-module
  coverage floors remain release gates.

The redesign is accepted when each identified deterministic routine has one
canonical CLI path, generated Agents no longer need to implement it from prose,
scientific decisions remain explicit inputs, and existing projects have a
documented migration and compatibility path.
