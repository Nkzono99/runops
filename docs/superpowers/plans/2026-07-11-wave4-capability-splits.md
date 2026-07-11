# Wave 4 Capability Splits Implementation Plan

**Goal:** Split the largest runops modules by capability while preserving their
public contracts and behavior.

**Status:** completed

**Outcome:** Split notebook, submission, plugin gateway, init/doctor, and BEACH
and EMSES adapter metadata/diagnostics behind stable facades; all 1591 tests,
82.51% branch coverage, and 15 critical-module floors pass.

1. Characterize facade imports and the one private submission patch point.
2. Split notebook into models, daily operations, archive planning, and archive
   application.
3. Split submission into models, planning, claim/locking, and apply modules.
4. Split gateway plugins into models, discovery, validation, and inventory.
5. Extract init workflows and adapter metadata/runtime/diagnostics helpers.
6. Move critical coverage floors to meaningful implementation modules.
7. Run focused and full KUDPC quality gates, review the diff, and commit Wave 4.
