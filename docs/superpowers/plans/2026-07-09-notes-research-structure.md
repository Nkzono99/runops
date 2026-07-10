# Notes Research Structure Implementation Plan

**Status:** completed
**Outcome:** Notes and research scaffolding delivered in commit `22997ba`.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add scaffold and skill guidance that keeps daily notes, reports, research decisions, and cross-run artifacts separated.

**Architecture:** This is a template-only harness improvement. `runo init` creates the physical directories and README files; generated skills teach agents how to route new content without editing existing user projects.

**Tech Stack:** Python 3.10+, Typer init scaffold, package static templates, pytest, ruff, KUDPC `tssrun` for tests.

## Global Constraints

- Do not edit `<external-read-only-project>`; use it only as read-only evidence.
- Keep project-state guidance in `src/runops/templates/`.
- Use TDD: tests first, then template/scaffold edits.
- Run tests through KUDPC Slurm from `gardenia` login nodes.

---

### Task 1: Scaffold Report Index Structure

**Files:**
- Create: `src/runops/templates/scaffold/notes/reports/README.md`
- Modify: `src/runops/cli/init/scaffold.py`
- Modify: `tests/test_cli/test_init.py`

**Interfaces:**
- Consumes: `load_static("scaffold/notes/reports/README.md")`
- Produces: new project files `notes/reports/README.md`, `notes/reports/archive/`, and `notes/reports/figures/`

- [x] **Step 1: Write failing init assertions**

Add assertions to `tests/test_cli/test_init.py::TestInit::test_init_creates_all_files`:

```python
assert (tmp_path / "notes" / "reports" / "README.md").is_file()
assert (tmp_path / "notes" / "reports" / "archive").is_dir()
assert (tmp_path / "notes" / "reports" / "figures").is_dir()
```

Add a content test that reads `notes/reports/README.md` and checks:

```python
assert "Recommended Reading Order" in report_readme
assert "Machine-Readable Entry Points" in report_readme
assert "Heavy / Recovery-Only Material" in report_readme
assert "Markdown image" in report_readme
```

- [x] **Step 2: Verify RED**

Run:

```bash
tssrun -p gr20001g -t 0:10:0 --rsc p=1:t=2:c=2 \
  bash -lc 'cd <repo-root> && uv run pytest tests/test_cli/test_init.py::TestInit::test_init_creates_all_files tests/test_cli/test_init.py::TestInit::test_init_reports_readme_content -q'
```

Expected: fail because `notes/reports/README.md`, `archive/`, and `figures/` are missing.

- [x] **Step 3: Implement scaffold**

Update `_create_notes_skeleton()` to create `notes/reports/archive/`,
`notes/reports/figures/`, and write the new static README if missing.

- [x] **Step 4: Verify GREEN**

Run the same pytest command and expect pass.

### Task 2: Strengthen Routing Guidance

**Files:**
- Modify: `src/runops/templates/scaffold/notes/README.md`
- Modify: `src/runops/templates/scaffold/research/README.md`
- Modify: `src/runops/templates/scaffold/research/agenda.md`
- Modify: `src/runops/templates/skills/note/SKILL.md`
- Modify: `src/runops/templates/skills/research-agenda/SKILL.md`
- Modify: `src/runops/templates/skills/summarize-script/SKILL.md`
- Modify: `tests/test_cli/test_init.py`
- Modify: `tests/test_harness/test_codex.py`

**Interfaces:**
- Produces: generated guidance strings used by `.agents/skills/*` and scaffolded `notes/`/`research/`

- [x] **Step 1: Write failing guidance assertions**

Assert generated files contain:

```python
"notes/reports/README.md"
"analysis/cross_run/<comparison_id>/"
"agenda.md is not an artifact ledger"
"Do not put chronological notes or artifact inventories back into agenda.md"
```

- [x] **Step 2: Verify RED**

Run targeted init/harness tests with `tssrun`.

- [x] **Step 3: Update templates**

Add explicit routing rules:

- daily chronology -> `notes/YYYY-MM-DD.md`
- reading order -> `notes/reports/README.md`
- refined prose -> `notes/reports/<topic>.md`
- old/full report -> `notes/reports/archive/`
- report-owned figures -> `notes/reports/figures/`
- cross-run machine artifacts -> `analysis/cross_run/<comparison_id>/`
- current decision -> `research/agenda.md`
- proposals/reviews -> `research/proposals/`, `research/reviews/`

- [x] **Step 4: Verify GREEN**

Run targeted init/harness tests with `tssrun`.

### Task 3: Quality Gate

**Files:**
- All changed files.

**Interfaces:**
- Produces: verified template/scaffold change.

- [x] **Step 1: Format/lint changed files**

Run:

```bash
tssrun -p gr20001g -t 0:30:0 --rsc p=1:t=2:c=2 \
  bash -lc 'cd <repo-root> && uv run ruff format --check src/runops/cli/init/scaffold.py tests/test_cli/test_init.py tests/test_harness/test_codex.py && uv run ruff check src/runops/cli/init/scaffold.py tests/test_cli/test_init.py tests/test_harness/test_codex.py'
```

- [x] **Step 2: Run relevant tests**

Run:

```bash
tssrun -p gr20001g -t 0:30:0 --rsc p=1:t=2:c=2 \
  bash -lc 'cd <repo-root> && uv run pytest tests/test_cli/test_init.py tests/test_harness/test_codex.py -q'
```

- [x] **Step 3: Review diff**

Run `git diff --check`, `git diff --stat`, and `git status --short --branch`.
