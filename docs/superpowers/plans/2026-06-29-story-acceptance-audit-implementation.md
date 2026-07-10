# Story Acceptance Audit Implementation Plan

**Status:** completed
**Outcome:** Initial story audit delivered in commit `e5d14f0`; strict schema and source follow-ups are tracked by `2026-07-10-review-followups.md`.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement deterministic story acceptance audit workspaces for issue #107.

**Architecture:** Add focused core logic under `src/runops/core/analysis/story.py` for story creation, parsing, artifact collection, selector matching, and report generation. Keep `src/runops/cli/analyze.py` thin: resolve CLI arguments, call core functions, and print output paths.

**Tech Stack:** Python 3.10+, Typer, `tomllib`/`tomli`, `tomli_w`, pytest, existing runops analysis artifact indexes.

## Global Constraints

- Work on `main` in this repository; AGENTS.md says current development is main-first.
- Use TDD: add failing tests before production code.
- Do not run pytest directly on the KUDPC login node; route pytest through `tssrun -p gr20001g -t 0:20:0 --rsc p=1:t=2:c=2`.
- Keep CLI logic thin and domain logic under `src/runops/core/analysis/`.
- Initial CLI is flat: `runo analyze new-story` and `runo analyze audit-story`.
- Initial selectors are string-based `kind:name` selectors.

---

### Task 1: Core Story Workspace And Audit Logic

**Files:**
- Create: `src/runops/core/analysis/story.py`
- Modify: `src/runops/core/analysis/__init__.py`
- Test: `tests/test_core/test_analysis_story.py`

**Interfaces:**
- Produces: `create_story_workspace(project_root: Path, story_id: str, *, title: str = "", sources: tuple[Path, ...] = ()) -> StoryWorkspaceResult`
- Produces: `audit_story_workspace(story_dir: Path) -> StoryAuditResult`
- Produces dataclasses: `StoryWorkspaceResult`, `StoryAuditResult`

- [ ] **Step 1: Write failing core tests**

Add `tests/test_core/test_analysis_story.py` with tests for:

```python
def test_create_story_workspace_writes_story_toml(tmp_path: Path) -> None:
    result = create_story_workspace(
        tmp_path,
        "surface adhesion",
        title="Surface adhesion story",
        sources=(tmp_path / "runs" / "scan",),
    )
    assert result.story_id == "surface-adhesion"
    assert (result.story_dir / "story.toml").is_file()
```

```python
def test_audit_story_workspace_reports_covered_missing_and_weak_steps(tmp_path: Path) -> None:
    # Build one run artifact index with a main figure and a draft figure.
    # Write story.toml with three steps: covered, missing, weak.
    result = audit_story_workspace(story_dir)
    assert result.overall_status == "partial"
    assert (story_dir / "audit.json").is_file()
    assert (story_dir / "audit.md").is_file()
```

```python
def test_audit_story_workspace_rejects_duplicate_step_ids(tmp_path: Path) -> None:
    with pytest.raises(SimctlError, match="Duplicate story step id"):
        audit_story_workspace(story_dir)
```

- [ ] **Step 2: Verify RED**

Run:

```bash
tssrun -p gr20001g -t 0:20:0 --rsc p=1:t=2:c=2 \
  bash -lc 'cd <repo-root> && uv run pytest tests/test_core/test_analysis_story.py -q'
```

Expected: FAIL because `runops.core.analysis.story` does not exist.

- [ ] **Step 3: Implement core logic**

Create `src/runops/core/analysis/story.py` with:

- TOML loading/writing helpers;
- `slugify_story_id`;
- story source resolution relative to project root;
- run artifact collection from `analysis/artifacts.toml`;
- survey artifact collection from `summary/artifacts.toml`;
- selector matching for `kind:name` against `kind`, `name`, `id`, `title`, `quantity`, `path`, and `tags`;
- per-step status: `covered`, `partial`, `missing`, `blocked`;
- report writers for `audit.json` and `audit.md`.

Update `src/runops/core/analysis/__init__.py` to export the new dataclasses and functions.

- [ ] **Step 4: Verify GREEN**

Run the same pytest command. Expected: PASS.

---

### Task 2: CLI Commands

**Files:**
- Modify: `src/runops/cli/analyze.py`
- Modify: `src/runops/cli/main.py`
- Test: `tests/test_cli/test_analyze.py`

**Interfaces:**
- Consumes: `create_story_workspace(...)`
- Consumes: `audit_story_workspace(...)`
- Produces CLI commands: `runo analyze new-story`, `runo analyze audit-story`

- [ ] **Step 1: Write failing CLI tests**

Add tests to `tests/test_cli/test_analyze.py`:

```python
def test_new_story_creates_workspace(tmp_path: Path) -> None:
    _write_project_file(tmp_path)
    with patch("runops.cli.analyze.Path.cwd", return_value=tmp_path):
        result = runner.invoke(
            app,
            ["analyze", "new-story", "Surface adhesion", "--source", "runs/scan"],
        )
    assert result.exit_code == 0
    assert (tmp_path / "analysis" / "stories" / "surface-adhesion" / "story.toml").is_file()
```

```python
def test_audit_story_writes_outputs(tmp_path: Path) -> None:
    _write_project_file(tmp_path)
    # Build minimal story workspace and artifact index.
    with patch("runops.cli.analyze.Path.cwd", return_value=tmp_path):
        result = runner.invoke(app, ["analyze", "audit-story", str(story_dir)])
    assert result.exit_code == 0
    assert "Audit:" in result.output
```

- [ ] **Step 2: Verify RED**

Run:

```bash
tssrun -p gr20001g -t 0:20:0 --rsc p=1:t=2:c=2 \
  bash -lc 'cd <repo-root> && uv run pytest tests/test_cli/test_analyze.py::TestStoryAudit -q'
```

Expected: FAIL because CLI commands are missing.

- [ ] **Step 3: Implement CLI wiring**

Add `new_story()` and `audit_story()` in `src/runops/cli/analyze.py`, import core story functions, and register them in `src/runops/cli/main.py`.

- [ ] **Step 4: Verify GREEN**

Run the same CLI pytest command. Expected: PASS.

---

### Task 3: Documentation And Command Listing

**Files:**
- Modify: `.codex/rules/commands.md`
- Modify: `docs/toml-reference.md`
- Modify: `docs/superpowers/specs/2026-06-29-story-acceptance-audit-design.md`

**Interfaces:**
- Consumes implemented CLI names and story schema.
- Produces updated user-facing command/schema references.

- [ ] **Step 1: Update docs**

Document:

- `runo analyze new-story NAME [--id ID] [--title TITLE] [--source PATH]`;
- `runo analyze audit-story STORY_DIR`;
- `analysis/stories/<story_id>/story.toml`;
- `audit.json` and `audit.md` output roles.

- [ ] **Step 2: Verify docs contain command names**

Run:

```bash
rg -n "new-story|audit-story|analysis/stories" .codex/rules/commands.md docs/toml-reference.md docs/superpowers/specs/2026-06-29-story-acceptance-audit-design.md
```

Expected: command names and workspace path appear.

---

### Task 4: Final Verification

**Files:**
- Verify all touched files.

- [ ] **Step 1: Run targeted tests on compute node**

```bash
tssrun -p gr20001g -t 0:30:0 --rsc p=1:t=2:c=2 \
  bash -lc 'cd <repo-root> && uv run pytest tests/test_core/test_analysis_story.py tests/test_cli/test_analyze.py::TestStoryAudit -q'
```

- [ ] **Step 2: Run style checks**

```bash
uv run ruff check src/runops/core/analysis/story.py src/runops/core/analysis/__init__.py src/runops/cli/analyze.py src/runops/cli/main.py tests/test_core/test_analysis_story.py tests/test_cli/test_analyze.py
uv run ruff format --check src/runops/core/analysis/story.py src/runops/core/analysis/__init__.py src/runops/cli/analyze.py src/runops/cli/main.py tests/test_core/test_analysis_story.py tests/test_cli/test_analyze.py
```

- [ ] **Step 3: Inspect diff**

```bash
git diff --stat
git diff --check
```

- [ ] **Step 4: Commit**

```bash
git add src/runops/core/analysis/story.py src/runops/core/analysis/__init__.py src/runops/cli/analyze.py src/runops/cli/main.py tests/test_core/test_analysis_story.py tests/test_cli/test_analyze.py .codex/rules/commands.md docs/toml-reference.md docs/superpowers/specs/2026-06-29-story-acceptance-audit-design.md docs/superpowers/plans/2026-06-29-story-acceptance-audit-implementation.md
git commit -m "feat: add story acceptance audit"
```
