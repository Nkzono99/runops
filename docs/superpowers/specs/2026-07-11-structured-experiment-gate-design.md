# Structured Experiment Gate Design

**Status:** approved
**Date:** 2026-07-11

## Purpose

Make the proposal → pilot → review → expansion policy enforceable before any
survey-backed bulk submission. Replace prose-only Research Director selection
with a structured comparison of at least two candidates.

## Machine sources

`research/experiments.toml` is the machine-readable experiment ledger:

```toml
schema_version = 1

[[experiments]]
id = "E1"
decision = "WAIT" # WAIT/EXPAND/REVISE/STOP
proposal = "research/proposals/2026-07-11-topic.md"
review = ""
selected_candidate = "C1"

[[experiments.candidates]]
id = "C1"
information_gain = "high"
falsification = "observable that rejects the hypothesis"
estimated_core_hours = 12.0
operational_risk = "low"

[[experiments.candidates]]
id = "C2"
information_gain = "medium"
falsification = "alternative rejection observation"
estimated_core_hours = 30.0
operational_risk = "medium"
```

Each governed `survey.toml` contains:

```toml
[research]
experiment_id = "E1"
stage = "pilot" # pilot/full
```

## Gate rules

The application validator runs before bulk plan construction and therefore
before any scheduler call.

- directories without `survey.toml` keep the existing generic bulk behavior;
- a survey with no valid `[research]` table fails closed;
- the referenced ledger and experiment must exist;
- every experiment needs at least two uniquely identified candidates;
- every candidate needs information gain, falsification, non-negative core-hour
  estimate, and operational risk;
- `selected_candidate` must name one candidate;
- the proposal path must be project-relative and exist;
- `stage = "pilot"` is allowed while decision is WAIT/REVISE/STOP/EXPAND;
- `stage = "full"` requires decision EXPAND and an existing project-relative
  review path;
- `--dry-run` uses the same gate; `--yes` cannot bypass it.

Failures are `SimctlError` values with an actionable experiment/survey field.
The gate is filesystem-only and never edits research state.

## Research Director workflow

The generated Research Director skill must write/update the ledger, compare at
least two candidates on the four required dimensions, name the selected
candidate, and keep the Markdown proposal as the human rationale/evidence
artifact. `review-pilot` updates decision/review in the ledger as well as the
human review and agenda. `run-all` invokes a dry-run first and treats gate
failure as non-bypassable.

## Compatibility

No CLI name changes. Existing generic bulk directories remain compatible.
Existing survey-backed bulk submission becomes intentionally fail-closed and is
documented in `docs/migrations/v0.md`. Single-run pilot submission is unchanged.

## Testing

Unit tests cover valid pilot/full gates and every missing/mismatched field. CLI
tests prove gate failure occurs before plan construction/submission, dry-run is
also gated, generic directories remain compatible, and `--yes` cannot bypass.
Harness tests verify generated skills and scaffold contain the structured
contract.
