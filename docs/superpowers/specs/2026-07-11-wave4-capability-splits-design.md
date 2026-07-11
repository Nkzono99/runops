# Wave 4 Capability Splits Design

**Status:** approved
**Date:** 2026-07-11

## Purpose

Wave 4 reduces responsibility concentration in the largest application, CLI,
and adapter modules without changing command behavior, public import paths, or
persisted project state.

## Compatibility boundary

- Existing public imports remain available from their current module paths.
- `application.research.notebook`, `application.execution.submission`, and
  `application.gateway.plugins` become facade packages that re-export the
  existing public API.
- The test-observed private name `submission._fsync_directory` remains
  patchable through the facade during this wave.
- `cli.init.command` and each simulator `adapter.py` remain import-compatible
  facades.
- No TOML schema, CLI option, MCP tool, or manifest transition changes.

## Capability boundaries

### Wave 4A

- notebook: models/errors, daily note access, archive planning, secure archive
  application;
- submission: models/errors, precondition planning, claim/locking, apply and
  persistence;
- gateway plugins: models, discovery, validation, inventory/project loading.

### Wave 4B

- init command: project initialization workflow and doctor workflow;
- BEACH and EMSES adapters: declarative metadata, runtime/input preparation,
  and attempt-aware diagnostics.

Adapter classes stay in `adapter.py`; extracted capabilities are implementation
helpers so registry identities and downstream subclasses remain stable.

## Dependency direction

Models and errors have no dependency on orchestration modules. Planning and
validation depend on models. Effectful apply/runtime modules may depend on
planning and models. Facades depend inward on each capability and contain no
domain decisions.

## Coverage policy

When a governed monolith becomes a package, its single-file coverage floor is
replaced by floors on the security- or state-critical implementation modules.
Thin facades are covered by import-contract tests but are not used to satisfy a
critical behavioral floor trivially.

The submission floor therefore moves from the former monolith to `apply.py`,
`claim.py`, and `planning.py`, each retaining the 90% floor. BEACH keeps its
adapter contract floor and adds an 80% floor for the extracted attempt-aware
`diagnostics.py` capability.

## Verification

Each capability split runs its focused tests. Wave 4 closes only after Ruff
format/check, strict mypy, the full pytest branch-coverage gate, and the updated
critical-module coverage policy all pass on a KUDPC compute allocation.
