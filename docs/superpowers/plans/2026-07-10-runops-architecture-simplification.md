# runops Architecture Simplification Implementation Plan

**Status:** completed
**Outcome:** Architecture simplification completed through the commit series ending in `beb2774`, with full quality gates and independent review passing on 2026-07-10.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore one coherent Execution Kernel and Agent gateway by repairing the manifest contract, introducing capability-oriented application services, removing duplicated submit rules, and reducing the largest interface/adapter hotspots.

**Architecture:** Keep one `runops` distribution. Pure state and contracts stay in `runops.core`; orchestrating capabilities live in `runops.application`; CLI and MCP translate at the edge; Slurm and simulator adapters implement injected ports. Internal import paths may break, while CLI behavior and project state remain compatible unless explicitly documented.

**Tech Stack:** Python 3.10+, Typer, TOML (`tomli`/`tomli_w`), Slurm command wrappers, pytest, ruff, mypy strict, uv.

## Global Constraints

- `runo` remains the preferred executable and `runops` remains an equivalent alias.
- The canonical manifest sections are `run`, `path`, `origin`, `classification`, `simulator`, `launcher`, `simulator_source`, `job`, `variation`, `params_snapshot`, and `files`.
- Manifest mutation preserves unknown top-level sections and unknown fields inside known sections by semantic value; comments and TOML table order are not preservation guarantees.
- This change does not add a manifest schema-version field or a partial version migration protocol.
- CLI dry-run, MCP plan, and actual submit use one `SubmitPlan`; an invalid plan cannot be applied.
- `runops.core` must not import `runops.application`, `runops.cli`, `runops.mcp`, `runops.slurm`, `runops.adapters`, or `runops.harness`.
- Story acceptance remains experimental; grouped `runo runs ...` and `runo analyze ...` commands are the current v0 surface.
- No new runtime dependency, build backend, package manager, or Python-version change.
- Python/test payloads on KUDPC login nodes run inside a `tssrun` or `sbatch` compute allocation; git and small text inspection may run on the login node.
- Preserve unrelated user changes and commit each task independently with an English Conventional Commit message.

---

### Task 1: Make `manifest.toml` lossless and canonical

**Files:**
- Modify: `src/runops/core/manifest.py`
- Modify: `schemas/manifest.json`
- Modify: `tests/test_core/test_manifest.py`
- Modify: `tests/test_core/test_schemas.py`
- Modify: `tests/test_core/test_run_creation.py`
- Modify: `SPEC.md`
- Modify: `docs/toml-reference.md`

**Interfaces:**
- Produces: `ManifestData.extra_sections: dict[str, Any]`
- Preserves: existing `read_manifest`, `write_manifest`, and `update_manifest` signatures
- Contract: canonical fields override conflicting keys in `extra_sections`

- [ ] **Step 1: Add failing lossless round-trip tests**

Add focused tests equivalent to:

```python
def test_manifest_roundtrip_preserves_unknown_sections(tmp_path: Path) -> None:
    run_dir = tmp_path / "R20260710-0001"
    run_dir.mkdir()
    (run_dir / "manifest.toml").write_text(
        '[run]\nid = "R20260710-0001"\nstatus = "created"\n'
        '[extensions.plugin]\nenabled = true\nitems = ["a", "b"]\n',
        encoding="utf-8",
    )

    manifest = read_manifest(run_dir)
    manifest.run["display_name"] = "kept"
    write_manifest(run_dir, manifest)

    raw = tomllib.loads((run_dir / "manifest.toml").read_text(encoding="utf-8"))
    assert raw["extensions"]["plugin"] == {
        "enabled": True,
        "items": ["a", "b"],
    }
```

Also cover unknown fields inside `run`, deep-copy isolation, and canonical-section precedence over conflicting `extra_sections`.

- [ ] **Step 2: Run the focused tests and verify RED**

Run inside the compute allocation:

```bash
uv run pytest tests/test_core/test_manifest.py -k 'unknown or roundtrip or extra' -q
```

Expected: failure because unknown top-level sections are discarded and `extra_sections` does not exist.

- [ ] **Step 3: Implement semantic preservation**

Use this shape in `ManifestData`:

```python
_KNOWN_MANIFEST_SECTIONS = (
    "run",
    "path",
    "origin",
    "classification",
    "simulator",
    "launcher",
    "simulator_source",
    "job",
    "variation",
    "params_snapshot",
    "files",
)

@dataclass
class ManifestData:
    # existing canonical fields stay in their current order
    extra_sections: dict[str, Any] = field(default_factory=dict, repr=False)
```

`from_dict()` deep-copies keys outside `_KNOWN_MANIFEST_SECTIONS`. `to_dict()` starts from a deep copy of extras, removes reserved canonical names, then writes canonical sections. Validate that a present canonical section is a TOML table and raise `ManifestError` otherwise.

- [ ] **Step 4: Align the JSON Schema and generated-shape tests**

Keep `additionalProperties: true`. Require the existing SPEC minimum at the root:

```json
[
  "run",
  "origin",
  "simulator",
  "launcher",
  "simulator_source",
  "job",
  "params_snapshot"
]
```

Require `origin.case`, `simulator.name`, `launcher.name`, `job.scheduler`, `job.job_id`, and `job.submitted_at`. Add an assertion that `build_manifest()` emits all canonical sections and these required fields.

- [ ] **Step 5: Replace the stale manifest reference**

Update SPEC section 12 and only the manifest portion of `docs/toml-reference.md` to use `[origin]`, `[simulator]`, `[launcher]`, `[simulator_source]`, and `[params_snapshot]`. Document open-world preservation and recommend third-party data under `[extensions.<namespace>]`. Do not alter case/survey `[params]` documentation.

- [ ] **Step 6: Verify GREEN and commit**

```bash
uv run pytest tests/test_core/test_manifest.py tests/test_core/test_schemas.py tests/test_core/test_run_creation.py -q
uv run ruff check src/runops/core/manifest.py tests/test_core/test_manifest.py tests/test_core/test_schemas.py
git diff --check
git add src/runops/core/manifest.py schemas/manifest.json tests/test_core/test_manifest.py tests/test_core/test_schemas.py tests/test_core/test_run_creation.py SPEC.md docs/toml-reference.md
git commit -m "fix: preserve manifest extension data"
```

### Task 2: Establish the application package and relocate orchestration

**Files:**
- Create: `src/runops/application/__init__.py`
- Move: `src/runops/core/actions/` → `src/runops/application/actions/`
- Move: `src/runops/core/run_creation/` → `src/runops/application/run_creation/`
- Move: `src/runops/core/context.py` → `src/runops/application/context.py`
- Move: `tests/test_core/test_action_contract.py` → `tests/test_application/test_action_contract.py`
- Move: `tests/test_core/test_actions.py` → `tests/test_application/test_actions.py`
- Move: `tests/test_core/test_run_creation.py` → `tests/test_application/test_run_creation.py`
- Move: `tests/test_core/test_context.py` → `tests/test_application/test_context.py`
- Modify: all first-party imports and affected tests
- Create: `tests/test_application/__init__.py`

**Interfaces:**
- Produces: `runops.application.actions` with the existing action names and signatures
- Produces: `runops.application.run_creation` with the existing run-creation facade
- Produces: `runops.application.context.build_project_context`
- Removes: undocumented internal `runops.core.actions`, `runops.core.run_creation`, and `runops.core.context` paths

- [ ] **Step 1: Add a failing application-facade characterization test**

```python
def test_application_actions_expose_registered_actions() -> None:
    from runops.application import actions

    assert set(actions.ACTION_SPECS) == set(actions._DISPATCH)
    assert callable(actions.submit_run)
```

- [ ] **Step 2: Verify RED**

```bash
uv run pytest tests/test_application/test_actions.py -q
```

Expected: import failure because `runops.application` does not exist.

- [ ] **Step 3: Move the three orchestration surfaces without changing behavior**

Preserve the existing `__all__` names. Update imports in CLI, MCP registry/tools, harness, tests, and remaining application modules. Do not leave compatibility shims under `runops.core`, because those shims would invert the intended dependency.

- [ ] **Step 4: Verify moved behavior**

```bash
uv run pytest tests/test_application/test_actions.py tests/test_application/test_action_contract.py tests/test_application/test_run_creation.py tests/test_application/test_context.py tests/test_cli/test_create.py tests/test_cli/test_context_cli.py -q
uv run python -c 'from runops.application.actions import submit_run; from runops.application.run_creation import create_case_run; from runops.application.context import build_project_context'
```

- [ ] **Step 5: Commit**

```bash
git diff --check
git add src/runops/application src/runops/core tests src/runops/cli src/runops/mcp src/runops/harness
git commit -m "refactor: introduce application orchestration layer"
```

### Task 3: Move capability workflows out of core and enforce the boundary

**Files:**
- Move: `src/runops/core/analysis/` → `src/runops/application/analysis/`
- Move: `src/runops/core/publication/` → `src/runops/application/publication/`
- Move: `src/runops/core/readiness.py` → `src/runops/application/execution/readiness.py`
- Move: `src/runops/core/retry.py` → `src/runops/application/execution/retry.py`
- Move: `src/runops/core/plugins.py` → `src/runops/application/gateway/plugins.py`
- Move: `src/runops/core/lint/` → `src/runops/application/operator/lint/`
- Move: `src/runops/core/migrations/` → `src/runops/application/operator/migrations/`
- Move: `tests/test_core/test_analysis.py` → `tests/test_application/test_analysis.py`
- Move: `tests/test_core/test_analysis_comparison.py` → `tests/test_application/test_analysis_comparison.py`
- Move: `tests/test_core/test_analysis_story.py` → `tests/test_application/test_analysis_story.py`
- Move: `tests/test_core/test_lint.py` → `tests/test_application/test_lint.py`
- Move: `tests/test_core/test_plugins.py` → `tests/test_application/test_plugins.py`
- Move: `tests/test_core/test_publication.py` → `tests/test_application/test_publication.py`
- Move: `tests/test_core/test_readiness.py` → `tests/test_application/test_readiness.py`
- Move: `tests/test_core/test_retry.py` → `tests/test_application/test_retry.py`
- Move: `tests/test_core/test_migrations.py` → `tests/test_application/test_migrations.py`
- Create: `src/runops/core/project_files.py`
- Create: `tests/test_architecture/test_core_import_boundaries.py`
- Modify: affected CLI, MCP, harness, application, migration, and test imports

**Interfaces:**
- Produces capability packages under `runops.application`
- Keeps pure models under `runops.core.models`
- Produces `runops.core.project_files.GITIGNORE_MANAGED_START/END`

- [ ] **Step 1: Add the failing AST boundary test**

```python
FORBIDDEN = {"application", "cli", "mcp", "slurm", "adapters", "harness"}

def test_core_does_not_import_interface_or_infrastructure_packages() -> None:
    violations: list[str] = []
    for path in sorted((REPO_ROOT / "src" / "runops" / "core").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names = import_names(node)
            for name in names:
                parts = name.split(".")
                if len(parts) >= 3 and parts[:2] == ["runops", "core"]:
                    continue
                if len(parts) >= 2 and parts[0] == "runops" and parts[1] in FORBIDDEN:
                    violations.append(f"{path.relative_to(REPO_ROOT)}: {name}")
    assert violations == []
```

`import_names()` handles both `ast.Import` and `ast.ImportFrom` and returns fully qualified module names.

- [ ] **Step 2: Verify RED and record the current violations**

```bash
uv run pytest tests/test_architecture/test_core_import_boundaries.py -q
```

Expected: violations from analysis, readiness, retry, plugins, and lint structure.

- [ ] **Step 3: Move the capability packages and neutralize the gitignore marker**

Move whole cohesive packages rather than leaving `core` facades that import outward. Put the managed `.gitignore` marker in `core/project_files.py`; `harness/builder.py` re-exports it for existing harness tests while `application.operator.lint` imports the neutral definition. Move migrations with the operator capability because v0 migration handlers use analysis artifact workflows; leaving a `core.migrations` facade would reintroduce `core -> application`.

- [ ] **Step 4: Update call sites and test layout**

Move capability tests from `tests/test_core/` to `tests/test_application/` when their subject moved. Keep manifest/state/project/case/survey tests in `tests/test_core/`. Update `cli/migrate.py` to the operator migration package and include `tests/test_cli/test_migrate.py` in verification. Preserve behavior assertions; only imports and patch targets change.

- [ ] **Step 5: Verify GREEN and commit**

```bash
uv run pytest tests/test_architecture tests/test_application tests/test_cli/test_analyze.py tests/test_cli/test_retry.py tests/test_cli/test_plugins.py tests/test_cli/test_lint.py tests/test_cli/test_migrate.py tests/test_mcp -q
uv run ruff check src/runops/core src/runops/application tests/test_architecture tests/test_application
git diff --check
git add src/runops tests src/runops/harness
git commit -m "refactor: enforce core dependency boundaries"
```

### Task 4: Implement one submission plan/apply use case

**Files:**
- Create: `src/runops/application/execution/submission.py`
- Create: `src/runops/application/ports/scheduler.py`
- Create: `src/runops/application/execution/__init__.py`
- Modify: `src/runops/application/actions/run_lifecycle.py`
- Modify: `src/runops/slurm/submit.py`
- Create: `tests/test_application/test_submission.py`
- Modify: `tests/test_slurm/test_slurm_submit.py`

**Interfaces:**
- Produces: `SubmitRequest`, `SubmitPrecondition`, `SubmitPlan`, `SubmissionResult`
- Produces: `plan_submit(request)`, `apply_submit(plan, submitter, now=...)`
- Produces: `runops.slurm.submit.submit_command(command, runner=None) -> str`

- [ ] **Step 1: Write failing plan and apply tests**

The desired API is:

```python
request = SubmitRequest(
    run_dir=run_dir,
    queue_name="debug",
    qos="normal",
    afterok="123",
)
plan = plan_submit(request)
assert plan.ready is True
assert plan.command == (
    "sbatch",
    f"--chdir={run_dir / 'work'}",
    "--dependency=afterok:123",
    "--partition=debug",
    "--qos=normal",
    str(run_dir / "submit" / "job.sh"),
)
```

Cover all preconditions in one plan: created state, script exists/readable/contains `#SBATCH`, and non-empty input. Verify `apply_submit()` refuses a blocked plan and does not mutate the manifest when the submitter raises.

- [ ] **Step 2: Verify RED**

```bash
uv run pytest tests/test_application/test_submission.py -q
```

- [ ] **Step 3: Implement immutable request/plan/result types**

Use frozen dataclasses. `SubmitPlan.failed_preconditions` and `.ready` are derived properties. `apply_submit()` accepts a `Submitter = Callable[[tuple[str, ...]], str]` and an injected UTC clock. It records job attempt metadata and transitions to `submitted` only after the external call succeeds.

- [ ] **Step 4: Make Slurm execute the exact planned vector**

Add:

```python
def submit_command(
    command: tuple[str, ...],
    *,
    runner: CommandRunner | None = None,
) -> str:
    if not command or command[0] != "sbatch":
        raise SlurmSubmitError("submission command must start with 'sbatch'")
    result = (runner or _default_runner)(list(command))
    if result.returncode != 0:
        raise SlurmSubmitError(...)
    return parse_job_id(result.stdout)
```

Keep `sbatch_submit()` as the public convenience wrapper and implement it via `submit_command()`.

- [ ] **Step 5: Replace action implementation with the shared use case**

`application.actions.submit_run()` builds a request, plans, maps failed preconditions to `ActionStatus.PRECONDITION_FAILED`, applies with `submit_command`, and maps the typed result to the existing `ActionResult` payload.

- [ ] **Step 6: Verify GREEN and commit**

```bash
uv run pytest tests/test_application/test_submission.py tests/test_application/test_actions.py tests/test_slurm/test_slurm_submit.py -q
uv run mypy src/runops/application/execution src/runops/slurm/submit.py
git diff --check
git add src/runops/application src/runops/slurm/submit.py tests/test_application tests/test_slurm/test_slurm_submit.py
git commit -m "refactor: centralize submission planning"
```

### Task 5: Wire CLI and MCP to the shared submission plan

**Files:**
- Modify: `src/runops/cli/submit.py`
- Modify: `src/runops/mcp/tools.py` (temporary facade implementation before Task 6 extraction)
- Modify: `tests/test_cli/test_submit.py`
- Modify: `tests/test_mcp/test_tools.py`
- Create: `tests/test_application/test_submission_parity.py`

**Interfaces:**
- CLI dry-run renders `SubmitPlan`
- MCP `runops.job.plan_submit` serializes the same `SubmitPlan`
- Actual action applies the same plan implementation

- [ ] **Step 1: Add failing parity tests**

Build one run fixture, call `plan_submit()`, invoke CLI `--dry-run`, and call MCP `job_plan_submit()`. Assert that the MCP `data.command` equals `list(plan.command)` and that CLI output includes every failed precondition for a blocked run.

- [ ] **Step 2: Verify RED**

```bash
uv run pytest tests/test_application/test_submission_parity.py tests/test_cli/test_submit.py -k dry_run tests/test_mcp/test_tools.py -k job_plan_submit -q
```

- [ ] **Step 3: Replace duplicate edge validation**

CLI resolves targets and renders plan status only. MCP resolves project/run identifiers, calls `plan_submit(SubmitRequest(...))`, and translates its typed fields into the existing Ops MCP envelope. Delete its local precondition and command-building block.

- [ ] **Step 4: Verify GREEN and commit**

```bash
uv run pytest tests/test_application/test_submission_parity.py tests/test_cli/test_submit.py tests/test_mcp/test_tools.py tests/test_mcp/test_server.py -q
uv run ruff check src/runops/cli/submit.py src/runops/mcp/tools.py tests/test_application/test_submission_parity.py
git diff --check
git add src/runops/cli/submit.py src/runops/mcp/tools.py tests/test_application/test_submission_parity.py tests/test_cli/test_submit.py tests/test_mcp/test_tools.py
git commit -m "refactor: share submit plans across interfaces"
```

### Task 6: Decompose the MCP tool implementation by capability

**Files:**
- Create: `src/runops/mcp/_tools/__init__.py`
- Create: `src/runops/mcp/_tools/common.py`
- Create: `src/runops/mcp/_tools/provider.py`
- Create: `src/runops/mcp/_tools/project.py`
- Create: `src/runops/mcp/_tools/publication.py`
- Create: `src/runops/mcp/_tools/analysis.py`
- Create: `src/runops/mcp/_tools/paper_requests.py`
- Create: `src/runops/mcp/_tools/runs.py`
- Create: `src/runops/mcp/_tools/scheduler.py`
- Replace: `src/runops/mcp/tools.py` with an explicit compatibility facade
- Modify: `tests/test_mcp/test_tools.py`
- Modify: `tests/test_mcp/test_server.py`

**Interfaces:**
- Preserves all names currently imported from `runops.mcp.tools`
- Keeps transport envelope behavior unchanged
- Uses the shared submission plan in `_tools/scheduler.py`

- [ ] **Step 1: Add facade characterization coverage before extraction**

Assert that the facade exports exactly the registered public callable names and that representative provider, project, publication, analysis, paper, run, and scheduler tools return their current envelope shapes.

- [ ] **Step 2: Run characterization tests before moving code**

```bash
uv run pytest tests/test_mcp/test_tools.py tests/test_mcp/test_server.py -q
```

Expected: PASS; this is characterization evidence for a behavior-preserving refactor.

- [ ] **Step 3: Extract common helpers and capability modules**

Move symbols according to the design map. Each implementation module imports common path/load helpers rather than another tool module. `tools.py` contains only explicit imports/re-exports and `__all__`; no wildcard imports and no lazy circular-import workaround.

- [ ] **Step 4: Update patch targets and verify the facade**

Tests patch the implementation module that owns the dependency (for example `_tools.project.shutil`), not the facade. Server registration continues importing the facade.

- [ ] **Step 5: Verify and commit**

```bash
uv run pytest tests/test_mcp -q
uv run mypy src/runops/mcp
uv run ruff check src/runops/mcp tests/test_mcp
git diff --check
git add src/runops/mcp tests/test_mcp
git commit -m "refactor: split MCP tools by capability"
```

### Task 7: Deduplicate bundled adapter runtime and provenance behavior

**Files:**
- Create: `src/runops/adapters/_provenance.py`
- Create: `src/runops/adapters/_runtime.py`
- Modify: `src/runops/adapters/generic.py`
- Modify: `src/runops/adapters/contrib/beach/adapter.py`
- Modify: `src/runops/adapters/contrib/emses/adapter.py`
- Create: `tests/test_adapters/test_provenance.py`
- Create: `tests/test_adapters/test_runtime.py`
- Modify: existing bundled-adapter tests

**Interfaces:**
- Produces: `collect_executable_provenance(runtime_info: Mapping[str, Any]) -> dict[str, Any]`
- Produces: `ExecutableRuntimeDefaults`
- Produces: `resolve_executable_runtime(config, mode, *, defaults, which, start_dir)`

- [ ] **Step 1: Add failing shared-helper tests**

Cover package/local-source/local-executable modes, invalid/missing values, injected executable lookup, executable SHA-256, clean/dirty Git source state, and non-file executable behavior.

- [ ] **Step 2: Verify RED**

```bash
uv run pytest tests/test_adapters/test_provenance.py tests/test_adapters/test_runtime.py -q
```

- [ ] **Step 3: Extract provenance without changing payload keys**

The helper returns the current keys: `resolver_mode`, `executable`, `exe_hash`, `git_commit`, `git_dirty`, `source_repo`, `build_command`, and `package_version`. All three bundled adapters delegate to it.

- [ ] **Step 4: Extract executable resolution with explicit defaults**

Use a frozen defaults dataclass and injected `which`. Preserve simulator-specific default executable/build-command/package discovery through arguments, not `if simulator == ...` branching in the helper.

- [ ] **Step 5: Verify bundled behavior and commit**

```bash
uv run pytest tests/test_adapters -q
uv run mypy src/runops/adapters
uv run ruff check src/runops/adapters tests/test_adapters
git diff --check
git add src/runops/adapters tests/test_adapters
git commit -m "refactor: share adapter runtime helpers"
```

### Task 8: Move notebook behavior out of Typer and simplify duplicate CLI options

**Files:**
- Create: `src/runops/application/research/__init__.py`
- Create: `src/runops/application/research/notebook.py`
- Modify: `src/runops/cli/notes.py`
- Modify: `src/runops/cli/update.py`
- Create: `tests/test_application/test_notebook.py`
- Modify: `tests/test_cli/test_notes.py`
- Modify: `tests/test_cli/test_update.py`

**Interfaces:**
- Produces: `NoteAppendRequest`, `NoteAppendResult`, `NoteDaySummary`, `NoteDocument`, `NoteArchivePlan`, and `NoteArchiveResult`
- Produces: `append_note()`, `list_note_days()`, `read_note()`, `plan_note_archive()`, and `apply_note_archive()` with injected dates
- Keeps the four `runo notes` commands and their output behavior
- Makes `--yes` canonical and `--force` a hidden compatibility alias with identical semantics

- [ ] **Step 1: Add failing notebook service tests**

Cover JST day selection, timestamped append, today/latest/date lookup, archive planning, dry-run-equivalent planning, apply, and path traversal rejection. Use an injected `datetime`/`date`; do not patch production globals.

- [ ] **Step 2: Verify RED**

```bash
uv run pytest tests/test_application/test_notebook.py -q
```

- [ ] **Step 3: Extract filesystem behavior and thin the CLI**

CLI owns Typer input, stdin, confirmation, and rendering. Application service owns path resolution, parsing, writes, and archive plan/apply. Preserve UTF-8 and existing on-disk format.

- [ ] **Step 4: Hide the duplicate update alias**

Keep the existing `force: bool` parameter for script compatibility, but declare its Typer option with `hidden=True`. Normalize once:

```python
assume_yes = yes or force
```

Use only `assume_yes` below option parsing. Add a help test showing `--yes` but not `--force`, plus a compatibility behavior test.

- [ ] **Step 5: Verify and commit**

```bash
uv run pytest tests/test_application/test_notebook.py tests/test_cli/test_notes.py tests/test_cli/test_update.py -q
uv run mypy src/runops/application/research src/runops/cli/notes.py src/runops/cli/update.py
uv run ruff check src/runops/application/research src/runops/cli/notes.py src/runops/cli/update.py tests/test_application/test_notebook.py
git diff --check
git add src/runops/application/research src/runops/cli/notes.py src/runops/cli/update.py tests/test_application/test_notebook.py tests/test_cli/test_notes.py tests/test_cli/test_update.py
git commit -m "refactor: extract notebook application service"
```

### Task 9: Extract harness upgrade orchestration from CLI

**Files:**
- Create: `src/runops/application/operator/harness_upgrade.py`
- Modify: `src/runops/cli/update_harness.py`
- Create: `tests/test_application/test_harness_upgrade.py`
- Modify: `tests/test_cli/test_update_harness.py`

**Interfaces:**
- Produces: `HarnessUpgradeRequest`, `HarnessUpgradePlan`, `plan_harness_upgrade()`, `apply_harness_upgrade()`
- Injects version source and command runner
- Keeps Typer option behavior and output stable

- [ ] **Step 1: Add failing application tests**

Cover version discovery, explicit target resolution, upgrade-chain construction, exact `uvx --from runops==<version>` command vectors, dry-run plan, command failure, and successful sequential application. Use complete fake version-source and command-result structures.

- [ ] **Step 2: Verify RED**

```bash
uv run pytest tests/test_application/test_harness_upgrade.py -q
```

- [ ] **Step 3: Move orchestration below Typer**

Move `_fetch_pypi_runops_versions`, target/chain planning, command-vector construction, and sequential runner logic into the application module. CLI retains option validation, prompts, and formatted plan/result output.

- [ ] **Step 4: Verify and commit**

```bash
uv run pytest tests/test_application/test_harness_upgrade.py tests/test_cli/test_update_harness.py -q
uv run mypy src/runops/application/operator/harness_upgrade.py src/runops/cli/update_harness.py
uv run ruff check src/runops/application/operator/harness_upgrade.py src/runops/cli/update_harness.py tests/test_application/test_harness_upgrade.py
git diff --check
git add src/runops/application/operator/harness_upgrade.py src/runops/cli/update_harness.py tests/test_application/test_harness_upgrade.py tests/test_cli/test_update_harness.py
git commit -m "refactor: extract harness upgrade service"
```

### Task 10: Align architecture, SPEC, and Agent guidance

**Files:**
- Modify: `.codex/rules/architecture.md`
- Modify: `.claude/rules/architecture.md`
- Modify: `docs/architecture.md`
- Modify: `docs/layers/interface.md`
- Modify: `docs/layers/knowledge.md`
- Modify: `SPEC.md`
- Modify: `docs/migrations/v0.md`
- Modify: `.agents/skills/implement-core/SKILL.md`
- Modify: `.agents/skills/implement-cli/SKILL.md`
- Modify: `.claude/agents/implement-core.md`
- Modify: `.claude/agents/implement-cli.md`
- Modify: `.codex/agents/implement-core.toml`
- Modify: `.codex/agents/implement-cli.toml`
- Modify: `.agents/skills/spec-reviewer/SKILL.md`
- Modify: `.agents/skills/test-writer/SKILL.md`
- Modify corresponding Claude agent mirrors
- Create: `tests/test_harness/test_development_guidance.py`

**Interfaces:**
- Defines one current v0 command surface and one internal dependency model
- Labels Execution Kernel, Research Workspace, Agent Gateway, and Operator/Developer utilities
- Removes stale ULID/`[state]`/`[parameters]` manifest examples from active guidance

- [ ] **Step 1: Add failing drift tests**

Assert that active development guidance contains `RYYYYMMDD-NNNN`, `params_snapshot`, `runo runs submit`, and references to `SPEC.md`/`.codex/rules/commands.md`; assert it does not contain `01HQ3`, `[state]`, `[parameters]`, or obsolete flat examples such as ``runops submit RUN``.

- [ ] **Step 2: Verify RED**

```bash
uv run pytest tests/test_harness/test_development_guidance.py -q
```

- [ ] **Step 3: Update architecture and product maturity docs**

Document the actual `core -> application -> interfaces/infrastructure` direction, the four bounded contexts, research-information maturity flow, story experimental status, and the distinction between CLI polling views and a persistent real-time dashboard service.

- [ ] **Step 4: Replace duplicated guidance tables with canonical references**

Keep skills concise: responsibilities, boundaries, workflow, and links to the current SPEC/command rule. Do not copy the entire command inventory or manifest schema into three Agent formats. Preserve Codex/Claude intent and update both development harnesses together.

- [ ] **Step 5: Record intentional v0 surface cleanup**

Document grouped commands as current, `--yes` as canonical, hidden `--force` compatibility, and internal Python import moves. No project-state migration is needed for internal moves.

- [ ] **Step 6: Verify and commit**

```bash
uv run pytest tests/test_harness/test_development_guidance.py tests/test_application/test_action_contract.py tests/test_cli/test_main.py -q
git diff --check
git add .codex .claude .agents docs SPEC.md tests/test_harness/test_development_guidance.py
git commit -m "docs: align architecture and agent guidance"
```

### Task 11: Final API, quality, and completion audit

**Files:**
- Modify only files required to fix verified regressions or review findings
- Read: `docs/superpowers/specs/2026-07-10-runops-architecture-simplification-design.md`
- Read: this plan

**Interfaces:**
- Produces final evidence for every acceptance criterion

- [ ] **Step 1: Capture and compare the static API**

```bash
uv run python .agents/skills/python-package-refactor/scripts/api_surface_snapshot.py snapshot --root . --output .superpowers/baselines/api-after.json
uv run python .agents/skills/python-package-refactor/scripts/api_surface_snapshot.py compare .superpowers/baselines/api-before.json .superpowers/baselines/api-after.json
```

Review internal moves as intentional; reject changes to package entry points, CLI commands, adapter exports, schemas, or documented public imports unless covered by the design.

- [ ] **Step 2: Run import smoke and full quality gates**

Inside the compute allocation:

```bash
uv run python .agents/skills/python-package-refactor/scripts/import_smoke.py --root . --format json --output .superpowers/baselines/import-smoke-after.json
uv run ruff format --check src/ tests/
uv run ruff check src/ tests/
uv run mypy src/
uv run pytest tests/ -x -q
uv run pytest --cov=runops --cov-branch --cov-report=term-missing --cov-fail-under=80
uv run runo --help
uv run runops --help
```

- [ ] **Step 3: Audit acceptance criteria one by one**

Use source, tests, command output, and git history to prove:

```text
manifest lossless + canonical
one submit plan across CLI/MCP/apply
core forbidden imports == 0
MCP/CLI/adapter hotspots reduced by responsibility
stale active guidance removed
maturity boundaries explicit
all quality gates green
```

- [ ] **Step 4: Run final code review and fix all Critical/Important findings**

Create one review package from `dc515a7` to final HEAD. Dispatch a broad reviewer against the design and this plan. Apply fixes in one final fix wave, re-run covering tests, and re-review.

- [ ] **Step 5: Commit final verified fixes if any**

```bash
git diff --check
git status --short
git add <only reviewed fix files>
git commit -m "fix: address architecture review findings"
```

Do not create an empty commit when no fix is needed.
