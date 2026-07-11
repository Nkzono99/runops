# Typed Story Audit Package Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split Story Audit into a typed six-module package while preserving every public import, output shape, diagnostic, and acceptance decision.

**Architecture:** Convert `story.py` into a compatibility package first, then extract immutable models, schema parsing, source collection, pure audit decisions, rendering, and filesystem orchestration in dependency order. Untyped mappings remain only at TOML/artifact and legacy-result boundaries.

**Tech Stack:** Python 3.10+, frozen dataclasses, `Literal`, TOML (`tomllib`/`tomli`, `tomli-w`), JSON, pytest, Ruff, strict mypy.

**Status:** active

## Global Constraints

- Preserve imports from `runops.application.analysis` and `runops.application.analysis.story`.
- Preserve `story.toml`, `audit.json`, and `audit.md` content and formatting for valid inputs.
- Preserve existing `SimctlError` diagnostics and blocked/missing/partial/covered precedence.
- Keep `StoryAuditResult.steps: list[dict[str, Any]]` and `warnings: list[str]` at the public boundary.
- Do not add dependencies or project-state migrations.
- Run tests and Python payloads through `tssrun -p gr20001b` on KUDPC.

---

### Task 1: Establish the compatibility package

**Files:**
- Move: `src/runops/application/analysis/story.py` → `src/runops/application/analysis/story/workspace.py`
- Create: `src/runops/application/analysis/story/__init__.py`
- Modify: `tests/test_application/test_analysis_story.py`

**Interfaces:**
- Consumes: the existing five public story symbols.
- Produces: a package facade re-exporting the exact same objects and signatures.

- [ ] **Step 1: Add facade characterization assertions**

Add a test importing both `runops.application.analysis` and
`runops.application.analysis.story`, then assert identity for
`StoryAuditResult`, `StoryWorkspaceResult`, `audit_story_workspace`,
`create_story_workspace`, and `slugify_story_id`.

- [ ] **Step 2: Run the current story tests**

```bash
tssrun -p gr20001b uv run pytest tests/test_application/test_analysis_story.py tests/test_cli/test_analyze.py -q
```

Expected: the new facade assertion fails before the package exists or passes
against the current module; record the baseline output before moving files.

- [ ] **Step 3: Move the implementation and create the facade**

Move the file with `git mv`, update its imports only as required, and create:

```python
from .workspace import (
    StoryAuditResult,
    StoryWorkspaceResult,
    audit_story_workspace,
    create_story_workspace,
    slugify_story_id,
)

__all__ = [
    "StoryAuditResult",
    "StoryWorkspaceResult",
    "audit_story_workspace",
    "create_story_workspace",
    "slugify_story_id",
]
```

- [ ] **Step 4: Verify compatibility**

Run the Step 2 command. Expected: all Story application and CLI tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/runops/application/analysis/story tests/test_application/test_analysis_story.py
git commit -m "refactor: package story audit implementation"
```

### Task 2: Introduce typed models and schema parsing

**Files:**
- Create: `src/runops/application/analysis/story/models.py`
- Create: `src/runops/application/analysis/story/schema.py`
- Create: `tests/test_application/test_story_schema.py`
- Modify: `src/runops/application/analysis/story/workspace.py`

**Interfaces:**
- Produces: `StorySource`, `StoryStep`, `StorySpec`, `ArtifactRecord`, `ArtifactEvidence`, `StepAudit`, `StoryAudit`, source/status literals, `read_story_spec(Path, default_id) -> StorySpec`, and `story_spec_payload(StorySpec) -> dict[str, object]`.
- Consumes later: source, audit, render, and workspace stages.

- [ ] **Step 1: Write failing model/schema tests**

Construct a valid TOML fixture and assert exact frozen records:

```python
spec = read_story_spec(path, default_id="fallback")
assert spec.sources == (StorySource(kind="survey", path="runs/scan"),)
assert spec.steps[0].required_artifacts == ("figure:surface",)
```

Parameterize the existing invalid schema cases and assert the same messages for
boolean schema version, unknown source kind, duplicate step ids, empty steps,
and invalid required/acceptable arrays. Assert `story_spec_payload()` recreates
the starter TOML mapping with lists at the serialization boundary.

- [ ] **Step 2: Run schema tests and verify RED**

```bash
tssrun -p gr20001b uv run pytest tests/test_application/test_story_schema.py -q
```

Expected: import failure because typed model/schema modules do not exist.

- [ ] **Step 3: Implement immutable models**

Implement the exact dataclasses from the approved design. `ArtifactRecord`
stores normalized matching attributes, `tags: tuple[str, ...]`, and
`present_fields: frozenset[str]`; `ArtifactEvidence.to_dict()` emits only the
legacy summary keys present in the source plus `selector`. `StepAudit.to_dict()`
emits list/dict containers matching the legacy audit JSON.

- [ ] **Step 4: Implement schema parsing and switch workspace reads**

Move `_read_story`, `_read_sources`, `_read_steps`, `_required_string`, and
`_required_string_array` into `schema.py`. Expose:

```python
def read_story_spec(story_path: Path, *, default_id: str) -> StorySpec: ...
def story_spec_payload(spec: StorySpec) -> dict[str, object]: ...
```

Change workspace creation to build a `StorySpec` and serialize it, and audit
orchestration to consume `StorySpec`. Do not change source/audit dictionaries
yet; bridge typed records locally until later tasks extract them.

- [ ] **Step 5: Verify schema and end-to-end behavior**

```bash
tssrun -p gr20001b uv run pytest tests/test_application/test_story_schema.py tests/test_application/test_analysis_story.py -q
```

Expected: all tests pass with unchanged errors and files.

- [ ] **Step 6: Commit**

```bash
git add src/runops/application/analysis/story tests/test_application/test_story_schema.py
git commit -m "refactor: type story schema records"
```

### Task 3: Extract typed source collection

**Files:**
- Create: `src/runops/application/analysis/story/sources.py`
- Create: `tests/test_application/test_story_sources.py`
- Modify: `src/runops/application/analysis/story/workspace.py`

**Interfaces:**
- Consumes: `StorySource`, `ArtifactRecord`.
- Produces: `SourceCollection` and `collect_source_artifacts(project_root: Path, source: StorySource) -> SourceCollection`.

- [ ] **Step 1: Write failing source tests**

Cover mapping normalization, absent optional fields, tag conversion, missing
source warning, declared/detected kind mismatch, run artifacts, survey indexes,
and comparison manifest artifacts. Assert the current display paths and exact
warning/error text.

- [ ] **Step 2: Run source tests and verify RED**

```bash
tssrun -p gr20001b uv run pytest tests/test_application/test_story_sources.py -q
```

Expected: import failure because `sources.py` does not exist.

- [ ] **Step 3: Move source discovery and normalize records**

Move `_collect_source_artifacts`, `_detect_source_kind`, comparison/index/run
readers, TOML mapping reads, source path resolution, display paths, and tag-list
normalization to `sources.py`. Convert every external mapping once with:

```python
def artifact_record(payload: Mapping[str, object]) -> ArtifactRecord: ...
```

Keep matching-relevant string conversion and summary omission behavior identical.

- [ ] **Step 4: Switch workspace to typed source collections**

Accumulate tuples of `ArtifactRecord` and warnings from `SourceCollection`.
Keep the existing missing-source prefix rule for `source_blocked`.

- [ ] **Step 5: Verify source and end-to-end tests**

```bash
tssrun -p gr20001b uv run pytest tests/test_application/test_story_sources.py tests/test_application/test_analysis_story.py tests/test_cli/test_analyze.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/runops/application/analysis/story tests/test_application/test_story_sources.py
git commit -m "refactor: extract typed story sources"
```

### Task 4: Extract pure audit decisions and rendering

**Files:**
- Create: `src/runops/application/analysis/story/audit.py`
- Create: `src/runops/application/analysis/story/render.py`
- Create: `tests/test_application/test_story_audit.py`
- Create: `tests/test_application/test_story_render.py`
- Modify: `src/runops/application/analysis/story/workspace.py`

**Interfaces:**
- Audit produces: `audit_step(StoryStep, Sequence[ArtifactRecord], source_blocked=False) -> StepAudit` and `overall_status(Sequence[StepAudit], Sequence[str]) -> OverallStatus`.
- Render produces: `audit_payload(StoryAudit) -> dict[str, object]` and `render_audit_markdown(StoryAudit) -> str`.

- [ ] **Step 1: Write failing pure audit tests**

Build typed records without files and cover accepted, weak, missing, mixed,
blocked, tag/name/id/title/quantity/path selectors, kind-qualified selectors,
and every overall precedence branch. Assert `StepAudit` records, not dictionaries.

- [ ] **Step 2: Write failing render compatibility tests**

Build one fixed `StoryAudit` with a fixed timestamp. Assert the complete payload
and complete Markdown string, including omitted evidence keys, ordering, labels,
and trailing newline.

- [ ] **Step 3: Run new tests and verify RED**

```bash
tssrun -p gr20001b uv run pytest tests/test_application/test_story_audit.py tests/test_application/test_story_render.py -q
```

Expected: import failures because audit/render modules do not exist.

- [ ] **Step 4: Extract filesystem-free audit logic**

Move selector parsing, token normalization, artifact matching, evidence
construction, step status, and overall status to `audit.py`. This module imports
only collections/regex/path helpers and `models`; it must not import TOML, JSON,
project discovery, or filesystem orchestration.

- [ ] **Step 5: Extract pure render logic and simplify workspace**

Move payload and Markdown creation to `render.py`. Workspace constructs one
typed `StoryAudit`, writes `json.dumps(audit_payload(...), indent=2,
sort_keys=True) + "\n"`, writes Markdown, then converts `StepAudit.to_dict()`
values into the public `StoryAuditResult.steps` list.

- [ ] **Step 6: Verify all Story behavior**

```bash
tssrun -p gr20001b uv run pytest tests/test_application/test_story_audit.py tests/test_application/test_story_render.py tests/test_application/test_analysis_story.py tests/test_cli/test_analyze.py -q
```

Expected: all tests pass and `workspace.py` contains orchestration only.

- [ ] **Step 7: Commit**

```bash
git add src/runops/application/analysis/story tests/test_application/test_story_audit.py tests/test_application/test_story_render.py
git commit -m "refactor: isolate story audit decisions and rendering"
```

### Task 5: Enforce typed boundaries and migrated coverage floors

**Files:**
- Modify: `pyproject.toml`
- Modify: `tests/test_application/test_coverage_policy.py`
- Modify: `tests/test_application/test_analysis_story.py`

**Interfaces:**
- Consumes: the six new package modules and Wave 1 coverage checker.
- Produces: exact-file floors for every Story package responsibility.

- [ ] **Step 1: Add failing structure and policy assertions**

Assert `story.py` no longer exists, all six modules exist, the package facade
exports the five compatibility symbols, and source text for `models.py`,
`audit.py`, and `render.py` contains neither `Any` imports nor
`dict[str, Any]`. Update the policy test expectation to require the six approved
Story paths and reject the removed monolith path.

- [ ] **Step 2: Run focused tests and verify RED**

```bash
tssrun -p gr20001b uv run pytest tests/test_application/test_analysis_story.py tests/test_application/test_coverage_policy.py -q
```

Expected: policy assertions fail while `pyproject.toml` still names `story.py`.

- [ ] **Step 3: Replace the Story coverage policy entry**

Use the approved floors: models 95, schema 90, audit 95, sources 80, render 90,
workspace 80. Do not add glob semantics to the checker.

- [ ] **Step 4: Run focused tests and real branch coverage**

```bash
tssrun -p gr20001b uv run pytest tests/test_application/test_story_*.py tests/test_application/test_analysis_story.py -q
tssrun -p gr20001b uv run pytest --cov=runops --cov-branch --cov-report=term-missing --cov-report=json:coverage.json --cov-fail-under=80
tssrun -p gr20001b uv run python -m runops.application.operator.coverage_policy coverage.json
```

Expected: all tests and all exact-file floors pass. Add targeted tests for any
uncovered meaningful branch; do not lower approved floors.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml tests/test_application src/runops/application/analysis/story
git commit -m "test: enforce typed story package boundaries"
```

### Task 6: Full verification and plan closeout

**Files:**
- Modify: `docs/superpowers/plans/2026-07-11-typed-story-audit-package.md`

**Interfaces:**
- Produces: a completed, clean, verified Wave 2 commit series.

- [ ] **Step 1: Run formatting and static checks**

```bash
tssrun -p gr20001b uv run ruff format --check src/ tests/
tssrun -p gr20001b uv run ruff check src/ tests/
tssrun -p gr20001b uv run mypy src/
```

Expected: all commands exit 0.

- [ ] **Step 2: Run full behavior and coverage gates**

```bash
tssrun -p gr20001b uv run pytest tests/ -x -q
tssrun -p gr20001b uv run pytest --cov=runops --cov-branch --cov-report=term-missing --cov-report=json:coverage.json --cov-fail-under=80
tssrun -p gr20001b uv run python -m runops.application.operator.coverage_policy coverage.json
```

Expected: all tests pass, global coverage is at least 80%, and all critical
module floors pass.

- [ ] **Step 3: Run public CLI smoke checks**

```bash
tssrun -p gr20001b uv run runo analyze --help
tssrun -p gr20001b uv run runo mcp check
```

Expected: both commands exit 0 and the public command/action surface is unchanged.

- [ ] **Step 4: Close the plan and review repository state**

Mark all checkboxes complete, set `Status` to `completed`, add a one-line
`Outcome`, then run `git diff --check`, `git status --short`, and inspect the
commit series.

- [ ] **Step 5: Commit closeout corrections**

If formatting or closeout changed tracked files, commit only those changes with
an English `style:`, `test:`, or `docs:` message. Do not create an empty commit.
