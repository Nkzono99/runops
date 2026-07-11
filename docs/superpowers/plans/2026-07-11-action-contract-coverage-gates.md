# Action Contract and Critical Coverage Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add bidirectional CLI/MCP action metadata checks and per-file coverage regression floors for critical runops modules.

**Architecture:** Keep the public Typer and MCP handlers unchanged and add small immutable metadata beside each interface. Conformance helpers compare that metadata with `ACTION_SPECS`; a separate filesystem-only application module evaluates coverage.py JSON against policy stored in `pyproject.toml`.

**Tech Stack:** Python 3.10+, dataclasses, Typer metadata, TOML via `tomllib`/`tomli`, pytest, pytest-cov, GitHub Actions.

**Status:** active

## Global Constraints

- Do not generate Typer callbacks or MCP handlers from `ActionSpec`.
- Do not add runtime dependencies or public CLI/MCP names.
- New mandatory CLI catalog coverage is limited to the current `ActionSpec` surface.
- Every ActionSpec MCP tool and every external/destructive MCP tool has an explicit reverse binding.
- Keep global combined line/branch coverage at 80% and enforce the seven approved per-file floors.
- Run Python and test commands on KUDPC through `tssrun`; do not execute payloads on the login node.

---

### Task 1: Bidirectional CLI operation contract

**Files:**
- Create: `src/runops/cli/operations.py`
- Modify: `tests/test_application/test_action_contract.py`

**Interfaces:**
- Consumes: `ACTION_SPECS: dict[str, ActionSpec]` and the existing Typer app tree.
- Produces: `CliOperationBinding`, `CLI_OPERATION_BINDINGS`, and `cli_operation_issues(bindings, action_specs) -> tuple[str, ...]`.

- [ ] **Step 1: Write failing contract tests**

Import the new catalog and add tests which assert that every advertised CLI path round-trips exactly, every catalog path exists in `_collect_cli_commands(cli_app)`, `("runs", "retry")` binds both `plan_retry` and `retry_run`, and the validator reports unknown actions, duplicate paths, missing advertised paths, and extra action/path pairs. Construct altered tuples of `CliOperationBinding` in each negative test so failures do not mutate global metadata.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
tssrun -p gr20001b uv run pytest tests/test_application/test_action_contract.py -q
```

Expected: collection fails because `runops.cli.operations` does not exist.

- [ ] **Step 3: Implement the immutable CLI catalog and validator**

Create the following interface and populate one binding for each unique `ActionSpec.cli_commands` path:

```python
@dataclass(frozen=True)
class CliOperationBinding:
    command_path: tuple[str, ...]
    action_names: tuple[str, ...]
    effect: Literal["read", "write", "external", "destructive"]


def cli_operation_issues(
    bindings: Sequence[CliOperationBinding] = CLI_OPERATION_BINDINGS,
    action_specs: Mapping[str, ActionSpec] = ACTION_SPECS,
) -> tuple[str, ...]:
    """Return deterministic CLI/action contract violations."""
```

Use these effects: `show_log=read`; `submit_run` and `sync_run=external`; archive, purge, cancel, and delete actions are `destructive`; all remaining governed actions are `write`. Sort diagnostics and reject duplicate command paths rather than collapsing them into a dictionary.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run the Step 2 command. Expected: all action-contract tests pass.

- [ ] **Step 5: Commit the CLI contract**

```bash
git add src/runops/cli/operations.py tests/test_application/test_action_contract.py
git commit -m "feat: add CLI action operation contract"
```

### Task 2: Bidirectional MCP operation contract

**Files:**
- Modify: `src/runops/mcp/registry.py`
- Modify: `tests/test_application/test_action_contract.py`
- Test: `tests/test_mcp/test_registry.py`

**Interfaces:**
- Consumes: `ActionSpec.mcp_tools`, `ToolSpec.safety`, and Task 1's `cli_operation_issues()`.
- Produces: `ToolSpec.action_name: str`, serialized `action_name`, and conformance report checks for both CLI and MCP reverse mappings.

- [ ] **Step 1: Write failing MCP reverse-contract tests**

Assert these exact bindings: logs to `show_log`; plan-submit and submit to `submit_run`; cancel to `cancel_run`; delete to `delete_run`. Add a test that every external/destructive spec has a non-empty action and confirmation metadata, and assert `conformance_report()` contains successful `cli_action_bindings_conform` and `mcp_action_bindings_conform` checks. Extend the serialization assertion so bound tools include `action_name` while `runops.health` omits it.

- [ ] **Step 2: Run focused tests and verify RED**

```bash
tssrun -p gr20001b uv run pytest tests/test_application/test_action_contract.py tests/test_mcp/test_registry.py -q
```

Expected: failures because `ToolSpec` has no `action_name` and the conformance checks are absent.

- [ ] **Step 3: Add ToolSpec bindings and conformance checks**

Add `action_name: str = ""` after the existing default fields and serialize it only when non-empty. Bind the five tools listed in Step 1. In `conformance_report()`, call `cli_operation_issues()` and add one deterministic CLI check; then compare both directions of `ActionSpec.mcp_tools` and `ToolSpec.action_name`, require all external/destructive tools to be bound, and retain the existing explicit-confirmation check.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the Step 2 command. Expected: all tests pass and `runo mcp check` remains compatible.

- [ ] **Step 5: Commit the MCP contract**

```bash
git add src/runops/mcp/registry.py tests/test_application/test_action_contract.py tests/test_mcp/test_registry.py
git commit -m "feat: enforce bidirectional MCP action bindings"
```

### Task 3: Critical-module coverage evaluator

**Files:**
- Create: `src/runops/application/operator/coverage_policy.py`
- Create: `tests/test_application/test_coverage_policy.py`
- Modify: `pyproject.toml`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: coverage.py JSON `files[path].summary.percent_covered` and `[tool.runops.coverage-policy.modules]`.
- Produces: `CoverageViolation`, `load_coverage_policy(Path) -> dict[str, float]`, `evaluate_coverage_policy(Path, Mapping[str, float]) -> tuple[CoverageViolation, ...]`, and `main(Sequence[str] | None) -> int`.

- [ ] **Step 1: Write failing unit tests**

Use `tmp_path` fixtures to cover a passing report, a below-floor violation with actual and required values, a missing report file entry, malformed JSON, missing policy table, and thresholds below 0, above 100, or non-numeric. Exercise `main()` with `capsys` and require exit 0 with a pass summary or exit 1 with concise sorted violations.

- [ ] **Step 2: Run the unit test and verify RED**

```bash
tssrun -p gr20001b uv run pytest tests/test_application/test_coverage_policy.py -q
```

Expected: collection fails because the module does not exist.

- [ ] **Step 3: Implement the evaluator and approved policy**

Parse TOML with stdlib `tomllib` on Python 3.11+ and `tomli` otherwise. Validate thresholds as real numbers excluding booleans, normalize them to float, parse JSON with `json.loads`, and return sorted immutable violations. `main()` accepts positional `coverage_json` and optional `--config`, catches parse/configuration exceptions, writes one diagnostic to stderr, and returns 1. Add the seven approved floors to `pyproject.toml` and `/coverage.json` to `.gitignore`.

- [ ] **Step 4: Run the unit test and verify GREEN**

Run the Step 2 command. Expected: all coverage-policy tests pass.

- [ ] **Step 5: Commit the evaluator**

```bash
git add src/runops/application/operator/coverage_policy.py tests/test_application/test_coverage_policy.py pyproject.toml .gitignore
git commit -m "feat: enforce critical module coverage floors"
```

### Task 4: Wire the coverage gate into development and publication

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `.github/workflows/publish.yml`
- Modify: `.agents/skills/check/SKILL.md`
- Modify: `.codex/rules/dev-workflow.md`

**Interfaces:**
- Consumes: Task 3's module entry point and `coverage.json` artifact.
- Produces: identical local, CI, and release coverage commands.

- [ ] **Step 1: Add a failing workflow/documentation consistency test**

Extend `tests/test_harness/test_development_guidance.py` with a parameterized test over `.github/workflows/ci.yml`, `.github/workflows/publish.yml`, `.agents/skills/check/SKILL.md`, and `.codex/rules/dev-workflow.md`. Assert every file contains `--cov-report=json:coverage.json` and `python -m runops.application.operator.coverage_policy coverage.json`.

- [ ] **Step 2: Run the focused test and verify RED**

```bash
tssrun -p gr20001b uv run pytest tests/test_harness/test_development_guidance.py -q
```

Expected: the new assertions fail because the JSON report and checker command are absent.

- [ ] **Step 3: Update all quality-gate command definitions**

Add `--cov-report=json:coverage.json` to the existing coverage invocation and run:

```bash
uv run python -m runops.application.operator.coverage_policy coverage.json
```

immediately afterward in CI, publish verification, `$check`, and the development workflow reference.

- [ ] **Step 4: Run focused tests and a real coverage report**

```bash
tssrun -p gr20001b uv run pytest tests/test_harness/test_development_guidance.py -q
tssrun -p gr20001b uv run pytest --cov=runops --cov-branch --cov-report=term-missing --cov-report=json:coverage.json --cov-fail-under=80
tssrun -p gr20001b uv run python -m runops.application.operator.coverage_policy coverage.json
```

Expected: harness test passes, global coverage is at least 80%, and every critical module meets its floor.

- [ ] **Step 5: Commit workflow integration**

```bash
git add .github/workflows/ci.yml .github/workflows/publish.yml .agents/skills/check/SKILL.md .codex/rules/dev-workflow.md tests/test_harness/test_development_guidance.py
git commit -m "ci: enforce critical module coverage policy"
```

### Task 5: Full verification and documentation closeout

**Files:**
- Modify only if required by verified drift: `.codex/rules/commands.md`

**Interfaces:**
- Consumes: all prior task outputs.
- Produces: a clean, fully verified Wave 1 commit series.

- [ ] **Step 1: Run formatting and static analysis**

```bash
tssrun -p gr20001b uv run ruff format --check src/ tests/
tssrun -p gr20001b uv run ruff check src/ tests/
tssrun -p gr20001b uv run mypy src/
```

Expected: all commands exit 0.

- [ ] **Step 2: Run the complete test and coverage gates**

```bash
tssrun -p gr20001b uv run pytest tests/ -x -q
tssrun -p gr20001b uv run pytest --cov=runops --cov-branch --cov-report=term-missing --cov-report=json:coverage.json --cov-fail-under=80
tssrun -p gr20001b uv run python -m runops.application.operator.coverage_policy coverage.json
```

Expected: all tests pass, global coverage is at least 80%, and no critical-module violation is printed.

- [ ] **Step 3: Run interface smoke checks**

```bash
tssrun -p gr20001b uv run runo mcp check
tssrun -p gr20001b uv run runo --help
```

Expected: both commands exit 0 and public command names are unchanged.

- [ ] **Step 4: Review the final diff and repository state**

```bash
git diff --check
git status --short
git log --oneline -6
```

Expected: no whitespace errors; only intentional uncommitted formatter fixes, if any, remain.

- [ ] **Step 5: Commit any verified closeout correction**

If Step 4 found a required tracked correction, stage only that file and commit it with an English `fix:`, `test:`, or `docs:` message describing the correction. Otherwise, do not create an empty commit.
