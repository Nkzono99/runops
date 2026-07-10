# runops Architecture Simplification Design

## Status

- Date: 2026-07-10
- Scope: runops v0 internal architecture, public contract alignment, and Agent-facing guidance
- Decision: approved for implementation

## Context

runops has grown from a Slurm run manager into an Agent-first research operations
tool. The newer analysis, research, knowledge, MCP, plugin, harness, demo, and story
features are individually useful, but they were added across several pre-existing
boundaries. The result is not one isolated large-file problem:

- `.codex/rules/architecture.md` prohibits `core -> slurm/adapters` imports while
  `docs/architecture.md` documents `core/actions` and `core/run_creation` as
  orchestration exceptions.
- CLI, ActionSpec, and MCP independently implement parts of the same use cases.
  Submission planning is the highest-risk example because plan and apply can drift.
- `manifest.toml` is the declared source of truth, but its SPEC, JSON Schema,
  serializer, and user reference do not describe the same shape. Unknown top-level
  sections accepted by the schema are currently lost on a read/write cycle.
- Product concepts and maturity are unclear. Stable execution state, experimental
  story workspaces, Agent gateway integrations, and developer utilities appear in
  the same command and documentation inventories without an explicit boundary.
- Several edge modules have accumulated application logic: `mcp/tools.py`,
  `cli/update_harness.py`, `cli/init/command.py`, and `cli/notes.py`.
- Simulator adapters combine simulator behavior with interactive Typer prompting,
  common executable resolution, provenance collection, template metadata, and Agent
  integration metadata.

The design must improve these structural causes while keeping runops usable during
the transition. A broad rewrite or premature multi-package split would add more
coordination contracts before the existing contracts are coherent.

## Goals

1. Make the dependency direction unambiguous and mechanically enforceable.
2. Give each behavioral rule one implementation used by CLI, MCP, and Agent actions.
3. Make `manifest.toml` a lossless, documented, versionable source of truth.
4. Separate the stable execution kernel from optional or experimental capabilities.
5. Reduce large edge modules and adapter duplication by extracting cohesive units.
6. Replace duplicated or stale command/schema tables in Agent guidance with canonical
   references and parity checks.
7. Preserve current project state and core CLI behavior unless an intentional v0
   migration is documented.

## Non-goals

- Splitting runops into multiple distributions in this change.
- Replacing Typer, TOML, Slurm, pytest, or the current build backend.
- Generalizing every scheduler or simulator before a second implementation exists.
- Rewriting pure domain modules that already have a clear responsibility.
- Treating internal Python import paths as public API when they are undocumented and
  used only by runops itself.

## Product Boundaries

runops remains one installable package, organized around four bounded contexts.

### 1. Execution Kernel

Candidate-stable contract:

- project, campaign, case, survey, and run identity;
- `manifest.toml`, run state, provenance, and directory layout;
- run creation, submission planning/application, synchronization, retry, archive,
  cancellation, and deletion;
- simulator, launcher, scheduler, and site contracts.

This is the product center. A feature that changes execution state must enter through
an application use case and must update the manifest contract deliberately.

### 2. Research Workspace

Capability-oriented and allowed to evolve during v0:

- analysis summaries, collections, plots, publication exports, comparisons, stories;
- notes, reports, research agenda, proposals, reviews, facts, and insights;
- explicit knowledge sources and imported context.

These artifacts follow one maturity flow rather than being described as unrelated
stores:

```text
raw notes/materials
    -> current decision (agenda) or refined report
    -> analysis/publication artifact
    -> reusable insight/fact
```

Story acceptance remains experimental. Its schema and commands are not promoted to
the candidate-stable Execution Kernel contract until real project use validates them.

### 3. Agent Gateway

MCP, ActionSpec, generated harnesses, Codex plugin recommendations, and safety gates
are interfaces to the other contexts. They do not own duplicate domain rules.

- MCP owns transport, envelope, safety metadata, and result serialization.
- ActionSpec owns use-case metadata, risk, cost, and interface mappings.
- harnesses own instructions and confirmation policy.
- plugin recommendations own advisory integration metadata only.

### 4. Operator and Developer Utilities

Bootstrap, migration, update, update-harness, demo replay, lint, and diagnostics are
operator/developer capabilities. They remain available but are not part of the
Execution Kernel domain model.

## Internal Architecture

The dependency direction is:

```text
cli / mcp / generated harness
             |
             v
application/{execution, experiment, analysis, knowledge, operator}
             |
             v
core domain + contracts

composition roots also construct infrastructure implementations:
slurm / simulator adapters / launchers / job generation / filesystem / network
             |
             +---- implement application ports ----^
```

### Core

`runops.core` contains scheduler- and interface-neutral state, parsing, validation,
value objects, and deterministic filesystem contracts. It must not import `cli`,
`mcp`, `slurm`, concrete adapters, `harness`, or network-facing implementations.

Shared constants needed by core health checks must live in a neutral core contract,
not be imported from an outer implementation module.

### Application

`runops.application` contains use cases. It is divided by capability so it does not
become a new catch-all layer. Each use case exposes typed request, plan, and result
objects where a plan/apply split matters.

Application code may depend on core contracts and on protocols defined at the
application boundary. Concrete Slurm, adapter-registry, filesystem, clock, network,
and subprocess behavior is supplied by a composition root.

### Interfaces and Infrastructure

CLI and MCP translate inputs and format outputs. They may select a composition root,
but they do not repeat preconditions or command construction.

Existing top-level infrastructure packages (`slurm`, `adapters`, `launchers`,
`jobgen`, `harness`) can remain in place. Moving them under a new directory would be
cosmetic until their dependency contracts are clean.

## Manifest Contract

The canonical manifest section names are those emitted by `ManifestData` and shown in
SPEC section 12:

```text
run, path, origin, classification, simulator, launcher,
simulator_source, job, variation, params_snapshot, files
```

The contract follows these rules:

1. A read/write or update cycle is lossless for unknown top-level sections and
   unknown fields inside known sections.
2. Known sections take precedence over extension data during serialization; an
   extension cannot shadow a canonical section.
3. Manifests generated by runops contain every section and required field identified
   by SPEC section 12, even when optional values are empty.
4. Existing v0 manifests with missing optional sections remain readable. Health/lint
   reports missing required contract data and migration may normalize it; ordinary
   reads do not destroy it.
5. `schemas/manifest.json`, SPEC, `docs/toml-reference.md`, scaffold/Agent guidance,
   and serializer tests use the same names.
6. Future schema-versioning work may add an explicit version field, but this change
   does not invent a partial version protocol without migration semantics.

## Submission Use Case

Submission establishes the migration pattern for other application behavior.

`runops.application.execution.submission` owns:

- `SubmitRequest`: run directory and optional queue/QOS/dependency overrides;
- `SubmitPrecondition`: stable name, status, and human-readable detail;
- `SubmitPlan`: normalized run identity, paths, scheduler-neutral options,
  preconditions, and the exact argument vector that will be applied;
- `plan_submit()`: deterministic validation and plan construction;
- `submit()`: apply an already-valid plan through a scheduler port, then update state.

CLI `--dry-run`, MCP `runops.job.plan_submit`, bulk submission, and actual submit use
the same plan. An invalid plan cannot be applied. The scheduler call is injected and
tests use a complete fake result rather than invoking Slurm.

The initial port can be intentionally narrow—submission only. Query/cancel ports are
added when their corresponding use cases move; no speculative universal scheduler
interface is required.

## Edge and Adapter Decomposition

After the shared submission seam is established:

- MCP tools are grouped by project, publication, analysis, paper request, run, and
  scheduler capabilities. `runops.mcp.tools` remains a compatibility facade for
  internal imports while implementation modules own cohesive behavior.
- Paper-request validation and publication/analysis queries move below the transport
  adapter when they are reusable business rules.
- CLI notebook and harness-update behavior moves into capability-specific application
  services; Typer functions retain prompting and rendering only.
- Common executable resolution and provenance collection are extracted from bundled
  adapters. Interactive configuration becomes declarative metadata rendered by CLI.
  Simulator-specific input/output/status behavior stays in each adapter.

Large files are not rejected by line count alone. A split is required when a file
owns multiple reasons to change or duplicates a rule owned elsewhere.

## Public Surface and Maturity Policy

- `runo` is the preferred executable and `runops` remains its stable alias.
- Grouped commands (`runo runs ...`, `runo analyze ...`) are the current v0 surface.
  Old flat examples are documentation bugs, not compatibility requirements.
- Duplicate confirmation options are consolidated. `--yes` is canonical; a retained
  `--force` spelling must be a hidden/deprecated compatibility alias with no separate
  semantics, or be removed with a v0 migration note.
- A polling CLI table is not a real-time service. SPEC's dashboard non-goal is narrowed
  to persistent Web/service dashboards so it does not contradict `--watch` views.
- Candidate-stable, experimental, and operator/developer surfaces are labeled in
  canonical documentation. Experimental features can be regrouped or removed during
  v0 with a migration note when project state is affected.

## Drift Prevention

Automated tests enforce:

1. forbidden imports from core into interface/infrastructure packages;
2. ActionSpec mappings refer to registered CLI commands and MCP tools;
3. CLI/MCP submission planning returns equivalent preconditions and argument vectors;
4. manifest generated shape and lossless round trips;
5. `runo` and `runops` expose the same command tree;
6. Codex/Claude command references and shared generated harness sources do not silently
   omit registered candidate-stable commands;
7. bundled development skills refer to canonical specs instead of embedding stale
   command and manifest tables.

Generated inventories are preferred when they stay readable and deterministic.
Otherwise, small parity tests are preferred over checking in another generated copy.

## Error Handling

- Domain and application failures use typed result/error objects or existing runops
  exception classes; CLI and MCP translate them at their respective edges.
- Broad exception capture is permitted only at a process/transport boundary where it
  is converted into an error envelope and logged. It must not hide programming errors
  inside reusable application services.
- Plan failures report all deterministic precondition failures in one result.
- Manifest mutation is atomic and never drops data that was successfully parsed.
- External submission failure leaves the manifest in its pre-submit state.

## Migration Strategy

Changes are delivered in independently testable commits:

1. document the architecture and capture API/quality baselines;
2. repair manifest round-trip and contract documentation;
3. add the application submission seam and scheduler port;
4. wire CLI, ActionSpec, and MCP to the shared use case;
5. enforce dependency and interface parity;
6. clean stale public guidance and duplicate options;
7. decompose the largest edge/adapter responsibilities using the proven pattern.

Internal imports may change without compatibility shims. Public CLI behavior, project
schemas, and generated project state require tests and a migration note for intentional
breaks. Each commit must leave the tree passing its targeted gates.

## Verification

Verification runs from narrow to broad:

- focused manifest, application, CLI, MCP, Slurm, adapter, and harness tests;
- static API snapshot comparison with intentional internal moves reviewed;
- `ruff format --check`, `ruff check`, and strict `mypy`;
- full pytest suite and branch coverage at least 80%;
- CLI help smoke for both executable names;
- import-boundary and documentation parity tests.

On KUDPC login nodes, Python and test payloads run through a compute-node allocation;
editing and small git/text inspection stay on the login node.

## Acceptance Criteria

The simplification is complete when:

- manifest updates preserve unknown sections and all canonical documentation agrees;
- CLI dry-run, MCP plan, and actual submission share one plan implementation;
- core has no forbidden imports covered by the architecture boundary;
- MCP/CLI/adapter hotspots have been reduced along responsibility boundaries without
  changing unrelated behavior;
- stale flat-command and manifest examples no longer exist in active Agent guidance;
- experimental versus candidate-stable features are explicit;
- all repository quality gates pass on the final tree;
- commits are small enough to review and contain no unrelated user changes.
