# Review Follow-ups Implementation Plan

**Status:** completed
**Outcome:** All six review follow-ups were implemented in `7735525` and `2d286f8`; execution/notebook prerequisites were closed in `beb2774`.
**Source:** `_handoff/review.md`
**Scope:** BEACH attempt tracking, story audit correctness, event-log secrecy,
research pilot governance, CLI composition, and development-document lifecycle.

## Delivery order

The work is intentionally ordered by operational risk: incorrect run state and
secret persistence first, workflow improvements next, structural cleanup last.
Every behavior change starts with a failing test and preserves the public CLI
surface unless this plan explicitly changes a documented experimental contract.

### 1. BEACH current-attempt progress

**Files:**

- Modify `src/runops/adapters/contrib/beach/adapter.py`
- Modify `tests/test_adapters/test_beach.py`
- Modify `SPEC.md`

**Acceptance:**

- A current `job_id` selects only `stdout.<job_id>.log`, `<job_id>.out`, and the
  corresponding stderr names; an empty current log never falls back to an older
  attempt.
- Without manifest job metadata, only the newest stdout candidate is inspected.
- `batch N/N` is progress, not proof of normal completion.
- A current-attempt error log takes precedence over progress.
- A pre-attempt `summary.txt` cannot mark a retry complete.
- `summarize()` reports progress from the same attempt used by `detect_status()`.

### 2. Story acceptance audit correctness

**Files:**

- Modify `src/runops/application/analysis/story.py`
- Modify `src/runops/cli/analyze.py`
- Modify `tests/test_application/test_analysis_story.py`
- Modify the relevant CLI story tests
- Modify `SPEC.md` and `.codex/rules/commands.md` only if the experimental
  contract description needs clarification

**Acceptance:**

- `required_artifacts` and `acceptable_status` must be non-empty string arrays.
- Missing or invalid sources cannot produce an overall `covered` result.
- Relative source paths resolve from project root, independent of process cwd.
- Source `kind` is validated and checked against the discovered source type.
- `name` is preserved as the human title; explicit `--id` is kept exactly after
  validation, while names without an ASCII slug get a deterministic hash ID.
- Invalid input writes no audit artifacts.

### 3. Event-log secrecy

**Files:**

- Modify `src/runops/core/event_log.py`
- Modify `src/runops/cli/main.py`
- Modify `tests/test_core/test_event_log.py`
- Modify `tests/test_cli/test_event_log.py`

**Acceptance:**

- `cli_invocation` records the program identity but no raw argv or option values.
- Secret-bearing keys are recognized case-insensitively across hyphen/underscore
  variants and replaced recursively.
- Free-form strings redact common assignment forms and URL userinfo.
- Tests cover `--token value`, `--token=value`, nested mappings, and URL
  credentials and assert the original secret is absent from the whole JSONL file.

### 4. Research Director and pilot gate

**Files:**

- Add project-harness templates under `src/runops/templates/skills/`
- Modify the research agenda template and related generated-harness guidance
- Modify `src/runops/harness/builder.py` only if discovery requires registration
- Modify `tests/test_harness/`
- Modify `docs/layers/research.md` and command/workflow documentation

**Acceptance:**

- Generated projects expose a research-director workflow that turns the mutable
  agenda into a bounded experiment proposal.
- Survey execution guidance requires a pilot, result review, and explicit
  `EXPAND` decision before full submission.
- The agenda template tracks active experiment portfolio and stop/expand criteria.
- Harness generation remains idempotent and does not overwrite edited files.

### 5. CLI composition boundary

**Files:**

- Modify `src/runops/cli/main.py`
- Add or modify CLI group-composition modules under `src/runops/cli/`
- Modify command-tree characterization tests
- Modify ActionSpec conformance tests where action-facing commands are covered

**Acceptance:**

- `main.py` builds the root app by importing complete group apps rather than
  enumerating each group command.
- The command paths and help-visible options remain unchanged for both `runo` and
  the `runops` alias.
- No domain rule is generated from Typer metadata; ActionSpec stays the semantic
  contract for action-facing operations.

### 6. Development-document lifecycle

**Files:**

- Modify `docs/superpowers/plans/*.md`
- Add or modify `docs/superpowers/README.md`
- Add a lightweight documentation-policy test if an existing test location fits

**Acceptance:**

- Every tracked plan declares `active`, `completed`, or `superseded` status.
- Completed plans identify their outcome or implementing commit(s).
- Machine-specific absolute checkout paths are removed from tracked plans.
- Product specifications remain normative; implementation plans are explicitly
  historical once completed.
- This plan is marked `completed` only after all quality gates pass.

## Verification

Run focused tests after each item on a KUDPC compute node. At the end run:

```bash
uv run ruff format --check src/ tests/
uv run ruff check src/ tests/
uv run mypy src/
uv run pytest tests/ -x -q
uv run pytest --cov=runops --cov-branch --cov-report=term-missing --cov-fail-under=80
```

Record the exact verification result in this document and only then change the
status to `completed`.

## Verification result

Executed on the KUDPC `eb` compute queue after the final review fixes:

- `uv run ruff format --check src/ tests/`: 318 files already formatted
- `uv run ruff check src/ tests/`: all checks passed
- `uv run mypy src/`: no issues in 207 source files
- `uv run pytest tests/ -x -q`: 1498 passed
- branch coverage gate: 1498 passed, 81.84% total coverage (minimum 80%)
- independent final review: Critical 0, Important 0, verdict Ready
