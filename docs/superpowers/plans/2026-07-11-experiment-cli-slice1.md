# Experiment CLI Slice 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add experiment-ledger schema v2, typed integrity/phase projection, an atomic experiment creation workflow, migration, and the canonical `runo experiment new/show/check` CLI.

**Architecture:** Replace the single experiment gate module with a facade package split into models, schema/storage, projection, workspace mutation, and the existing bulk gate. `research/experiments.toml` remains the machine source of truth; Markdown proposal files are linked narrative attachments. CLI callbacks remain thin and call application services with stable human/JSON rendering.

**Tech Stack:** Python 3.10+, frozen dataclasses, TOML/JSON, Typer, pytest, Ruff, strict mypy.

**Status:** active

## Global Constraints

- Do not automate scientific candidate selection or `WAIT`/`EXPAND`/`REVISE`/`STOP` decisions.
- Preserve the public import `runops.application.research.experiments.validate_bulk_experiment_gate` and schema-v1 bulk-submit compatibility until migration is explicitly applied.
- Schema-v2 records created by ordinary commands are complete; only migrated legacy records may carry explicit blockers.
- Persisted experiment phase is forbidden; phase is derived from ledger, surveys, run manifests, and artifact indexes.
- Mutations use immutable plan/apply types, revalidate stale identities, never overwrite proposal files, and report recovery paths on incomplete rollback.
- `--dry-run` skips all writes; `--json` uses a versioned envelope; `--yes` is only explicit machine confirmation for an effectful JSON create and never bypasses validation.
- Use `.venv` through `uv run`; on KUDPC login nodes execute Python/test payloads through `tssrun -p gr20001b`.
- Keep `runo` and `runops` command trees identical.

---

### Task 1: Typed experiment package and schema-v2 reader

**Files:**
- Delete: `src/runops/application/research/experiments.py`
- Create: `src/runops/application/research/experiments/__init__.py`
- Create: `src/runops/application/research/experiments/models.py`
- Create: `src/runops/application/research/experiments/schema.py`
- Create: `src/runops/application/research/experiments/gate.py`
- Modify: `tests/test_application/test_experiment_gate.py`
- Create: `tests/test_application/test_experiment_schema.py`

**Interfaces:**
- Produces: `load_experiment_ledger(project_root: Path) -> ExperimentLedger`
- Produces: `read_experiment_spec(path: Path) -> ExperimentCreateSpec`
- Preserves: `validate_bulk_experiment_gate(survey_dir: Path) -> ExperimentAuthorization | None`
- Produces immutable `ExperimentCandidate`, `ExperimentAuthorizationScope`, `ExperimentRecord`, `ExperimentLedger`, and `ExperimentCreateSpec`.

- [ ] **Step 1: Write failing schema-v2 and compatibility tests**

```python
def test_schema_v2_loads_complete_typed_record(project_root: Path) -> None:
    ledger = load_experiment_ledger(project_root)
    record = ledger.experiments[0]
    assert ledger.schema_version == 2
    assert record.id == "E1"
    assert record.selected_candidate == "C1"
    assert record.cost_ceiling_core_hours == 128.0
    assert record.migration_blockers == ()


def test_schema_v2_rejects_persisted_phase(project_root: Path) -> None:
    _write_ledger(project_root, {"schema_version": 2, "experiments": [{"id": "E1", "phase": "pilot-ready"}]})
    with pytest.raises(SimctlError, match="phase is derived and must not be stored"):
        load_experiment_ledger(project_root)


def test_schema_v1_bulk_gate_remains_compatible(tmp_path: Path) -> None:
    survey = _project(tmp_path, schema_version=1, stage="pilot")
    assert validate_bulk_experiment_gate(survey) is not None
```

- [ ] **Step 2: Run tests and verify the red state**

Run:

```bash
tssrun -p gr20001b uv run pytest tests/test_application/test_experiment_schema.py tests/test_application/test_experiment_gate.py -q
```

Expected: collection fails because the package models and `load_experiment_ledger` do not exist.

- [ ] **Step 3: Implement frozen models**

```python
ExperimentStage = Literal["pilot", "full"]
ExperimentDecision = Literal["WAIT", "EXPAND", "REVISE", "STOP"]


@dataclass(frozen=True)
class ExperimentCandidate:
    id: str
    information_gain: str
    falsification: str
    estimated_core_hours: float
    operational_risk: str


@dataclass(frozen=True)
class ExperimentAuthorizationScope:
    stage: ExperimentStage
    survey: Path
    review: Path
    max_core_hours: float


@dataclass(frozen=True)
class ExperimentAuthorization:
    experiment_id: str
    stage: ExperimentStage
    decision: ExperimentDecision
    proposal_path: Path
    review_path: Path | None
    selected_candidate: str


@dataclass(frozen=True)
class ExperimentRecord:
    id: str
    title: str | None
    question: str | None
    decision: ExperimentDecision
    proposal: Path
    review: Path | None
    selected_candidate: str
    cost_ceiling_core_hours: float | None
    candidates: tuple[ExperimentCandidate, ...]
    authorization: ExperimentAuthorizationScope | None = None
    migration_blockers: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExperimentLedger:
    path: Path
    schema_version: int
    experiments: tuple[ExperimentRecord, ...]
    identity: tuple[int, int, int]


@dataclass(frozen=True)
class ExperimentCreateSpec:
    title: str
    question: str
    selected_candidate: str
    cost_ceiling_core_hours: float
    candidates: tuple[ExperimentCandidate, ...]
```

`identity` is `(st_dev, st_ino, st_mtime_ns)` and is captured from the opened ledger after parsing.

- [ ] **Step 4: Implement strict schema parsing and spec input**

`schema.py` must accept ledger schema 1 or 2, reject duplicate IDs/candidate IDs, booleans as numeric costs, absolute/escaping project paths, unknown decisions/stages, selected candidates not in the candidate set, and persisted `phase`. Schema 1 is converted in memory without rewriting: missing v2 scientific fields become `None` and synthetic migration blockers, while the compatibility gate enforces the original v1 fields only. Schema 2 accepts `migration_blockers` only when non-empty and rejects authorization unless all four authorization fields are valid. Complete schema-2 records reject `None` for title, question, or cost ceiling.

`read_experiment_spec()` accepts `.toml` and `.json` with this exact non-interactive shape:

```toml
title = "Ion depletion pilot"
question = "Does vti widen the depletion cone?"
selected_candidate = "C1"
cost_ceiling_core_hours = 128.0

[[candidates]]
id = "C1"
information_gain = "Separates thermal and drift scaling"
falsification = "No monotonic cone-angle response"
estimated_core_hours = 32.0
operational_risk = "low"

[[candidates]]
id = "C2"
information_gain = "Tests resolution sensitivity first"
falsification = "Resolution changes the inferred trend"
estimated_core_hours = 64.0
operational_risk = "medium"
```

- [ ] **Step 5: Move the existing bulk gate behind the facade**

`gate.py` consumes `load_experiment_ledger()` for schema 2 and retains the existing schema-1 behavior. A schema-2 record with migration blockers fails closed. A full-stage survey additionally requires matching `authorization.stage`, resolved survey path, review path, and a selected-candidate cost not exceeding both authorization and record ceilings.

`__init__.py` explicitly re-exports all public types plus:

```python
from .gate import validate_bulk_experiment_gate
from .schema import load_experiment_ledger, read_experiment_spec
```

- [ ] **Step 6: Run focused tests and commit**

Run the command from Step 2. Expected: all experiment schema/gate tests pass.

```bash
git add src/runops/application/research/experiments tests/test_application/test_experiment_gate.py tests/test_application/test_experiment_schema.py
git commit -m "refactor: type experiment ledger schema"
```

---

### Task 2: Integrity checks and derived experiment projection

**Files:**
- Create: `src/runops/application/research/experiments/projection.py`
- Modify: `src/runops/application/research/experiments/models.py`
- Modify: `src/runops/application/research/experiments/__init__.py`
- Create: `tests/test_application/test_experiment_projection.py`

**Interfaces:**
- Produces: `check_experiments(project_root: Path, experiment_id: str | None = None) -> tuple[ExperimentIssue, ...]`
- Produces: `project_experiment(project_root: Path, experiment_id: str) -> ExperimentProjection`
- Produces: `list_experiment_projections(project_root: Path) -> tuple[ExperimentProjection, ...]`

- [ ] **Step 1: Write failing projection tests**

```python
def test_projection_derives_blocked_without_persisting_phase(project_root: Path) -> None:
    projection = project_experiment(project_root, "E1")
    assert projection.phase == "blocked"
    assert "proposal_missing" in {item.code for item in projection.blockers}
    assert projection.next_actions == ("Create the proposal attachment.",)


def test_projection_derives_full_authorized_from_scope(project_root: Path) -> None:
    _write_complete_project(project_root, decision="EXPAND", authorization=True)
    projection = project_experiment(project_root, "E1")
    assert projection.phase == "full-authorized"
    assert projection.blockers == ()
    assert projection.next_commands == (
        "runo experiment submit E1 --stage full --dry-run",
    )
```

- [ ] **Step 2: Verify the tests fail because projection APIs are absent**

Run:

```bash
tssrun -p gr20001b uv run pytest tests/test_application/test_experiment_projection.py -q
```

Expected: import/attribute failure for `project_experiment`.

- [ ] **Step 3: Add projection types**

```python
IssueSeverity = Literal["error", "warning"]
ExperimentPhase = Literal[
    "blocked", "proposed", "pilot-planned", "pilot-ready",
    "pilot-active", "review-pending", "full-authorized",
    "full-active", "revising", "stopped", "completed",
]


@dataclass(frozen=True)
class ExperimentIssue:
    severity: IssueSeverity
    code: str
    message: str
    path: Path | None = None

    def to_dict(self, project_root: Path) -> dict[str, str]:
        data = {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
        }
        if self.path is not None:
            data["path"] = self.path.resolve().relative_to(
                project_root.resolve()
            ).as_posix()
        return data


@dataclass(frozen=True)
class ExperimentProjection:
    experiment: ExperimentRecord
    phase: ExperimentPhase
    surveys: tuple[Path, ...]
    run_counts: Mapping[str, int]
    required_artifacts: int
    present_artifacts: int
    blockers: tuple[ExperimentIssue, ...]
    warnings: tuple[ExperimentIssue, ...]
    next_actions: tuple[str, ...]
    next_commands: tuple[str, ...]

    def to_dict(self, project_root: Path) -> dict[str, Any]:
        def display(path: Path) -> str:
            return path.resolve().relative_to(project_root.resolve()).as_posix()

        return {
            "experiment": {
                "id": self.experiment.id,
                "title": self.experiment.title,
                "question": self.experiment.question,
                "decision": self.experiment.decision,
                "selected_candidate": self.experiment.selected_candidate,
            },
            "phase": self.phase,
            "surveys": [display(path) for path in self.surveys],
            "run_counts": dict(self.run_counts),
            "artifact_readiness": {
                "required": self.required_artifacts,
                "present": self.present_artifacts,
            },
            "blockers": [item.to_dict(project_root) for item in self.blockers],
            "warnings": [item.to_dict(project_root) for item in self.warnings],
            "next_actions": list(self.next_actions),
            "next_commands": list(self.next_commands),
        }
```

- [ ] **Step 4: Implement deterministic discovery and phase priority**

Scan project-local `survey.toml` files under `runs/`, select `[research].experiment_id`, then discover their run manifests by origin survey path. Read artifact indexes only through existing analysis artifact helpers. Phase priority is exact:

```text
blocking issue -> blocked
decision STOP -> stopped
decision REVISE -> revising
all full runs completed and required artifacts present -> completed
any full run submitted/running -> full-active
decision EXPAND with valid authorization -> full-authorized
pilot runs completed but evidence incomplete or decision WAIT -> review-pending
any pilot run submitted/running -> pilot-active
pilot run set exists -> pilot-ready
pilot survey exists -> pilot-planned
otherwise -> proposed
```

Missing/invalid referenced paths are issues, not uncaught exceptions. Unknown run states and stale artifact indexes are warnings. Output ordering is experiment ID, path, and issue code stable.

- [ ] **Step 5: Run tests and commit**

Run the Step 2 command. Expected: all projection tests pass.

```bash
git add src/runops/application/research/experiments tests/test_application/test_experiment_projection.py
git commit -m "feat: project experiment readiness"
```

---

### Task 3: Atomic experiment creation plan/apply

**Files:**
- Create: `src/runops/application/research/experiments/workspace.py`
- Modify: `src/runops/application/research/experiments/models.py`
- Modify: `src/runops/application/research/experiments/schema.py`
- Modify: `src/runops/application/research/experiments/__init__.py`
- Create: `tests/test_application/test_experiment_workspace.py`

**Interfaces:**
- Produces: `plan_create_experiment(request: ExperimentCreateRequest) -> ExperimentCreatePlan`
- Produces: `apply_create_experiment(plan: ExperimentCreatePlan) -> ExperimentCreateResult`

- [ ] **Step 1: Write failing plan/apply and rollback tests**

```python
def test_create_plan_is_non_mutating(project_root: Path, spec_path: Path) -> None:
    spec = read_experiment_spec(spec_path)
    plan = plan_create_experiment(ExperimentCreateRequest(project_root, "E1", spec))
    assert plan.experiment_id == "E1"
    assert plan.ledger_after.schema_version == 2
    assert not plan.proposal_path.exists()


def test_apply_rejects_stale_ledger(project_root: Path, spec_path: Path) -> None:
    spec = read_experiment_spec(spec_path)
    plan = plan_create_experiment(ExperimentCreateRequest(project_root, "E1", spec))
    _touch_ledger(project_root)
    with pytest.raises(ExperimentStalePlanError):
        apply_create_experiment(plan)


def test_apply_rolls_back_proposal_when_ledger_publish_fails(project_root: Path, spec_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    spec = read_experiment_spec(spec_path)
    plan = plan_create_experiment(ExperimentCreateRequest(project_root, "E1", spec))
    monkeypatch.setattr(workspace, "_publish_ledger", Mock(side_effect=OSError("disk full")))
    with pytest.raises(ExperimentCreateApplyError) as caught:
        apply_create_experiment(plan)
    assert not plan.proposal_path.exists()
    assert caught.value.recovery_path is None
```

- [ ] **Step 2: Verify the focused tests fail**

Run:

```bash
tssrun -p gr20001b uv run pytest tests/test_application/test_experiment_workspace.py -q
```

Expected: missing workspace APIs.

- [ ] **Step 3: Add immutable request/plan/result/error types**

```python
@dataclass(frozen=True)
class ExperimentCreateRequest:
    project_root: Path
    experiment_id: str
    spec: ExperimentCreateSpec


@dataclass(frozen=True)
class ExperimentCreatePlan:
    project_root: Path
    experiment_id: str
    ledger_path: Path
    ledger_identity: tuple[int, int, int]
    ledger_after: ExperimentLedger
    proposal_path: Path
    proposal_text: str


@dataclass(frozen=True)
class ExperimentCreateResult:
    experiment: ExperimentRecord
    ledger_path: Path
    proposal_path: Path
```

Add `ExperimentStalePlanError` and `ExperimentCreateApplyError` carrying completed paths, failed path, recovery path, and cause.

- [ ] **Step 4: Implement validation, rendering, staging, and rollback**

Experiment IDs use `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`; duplicates compare exactly. The proposal is `research/proposals/<id>.md`, created from a deterministic template containing title, question, candidate table, falsification criteria, budget, evidence, and review sections. The plan rejects existing proposal paths and non-schema-2 ledgers.

Apply rechecks the ledger identity and proposal absence, retains the original ledger bytes for rollback, stages both sibling files with mode `0o600`, fsyncs each file, publishes the proposal with no-replace semantics, atomically replaces the ledger, and fsyncs both directories. On any failure after proposal publication it restores the original ledger when replacement occurred and removes only the proposal inode it created. An ambiguous restore or cleanup reports the retained recovery path and completed effects.

- [ ] **Step 5: Run tests and commit**

Run the Step 2 command. Expected: all workspace tests pass.

```bash
git add src/runops/application/research/experiments tests/test_application/test_experiment_workspace.py
git commit -m "feat: create experiments atomically"
```

---

### Task 4: Experiment CLI and action contract

**Files:**
- Create: `src/runops/cli/experiment.py`
- Create: `src/runops/cli/groups/experiment.py`
- Modify: `src/runops/cli/groups/__init__.py`
- Modify: `src/runops/cli/main.py`
- Create: `src/runops/application/actions/research.py`
- Modify: `src/runops/application/actions/__init__.py`
- Modify: `src/runops/application/actions/registry.py`
- Modify: `src/runops/application/actions/specs.py`
- Modify: `src/runops/cli/operations.py`
- Modify: `src/runops/mcp/safety.py`
- Modify: `src/runops/mcp/registry.py`
- Create: `tests/test_cli/test_experiment.py`
- Modify: `tests/test_cli/test_main.py`
- Modify: `tests/test_application/test_action_contract.py`
- Modify: `tests/test_mcp/test_registry.py`

**Interfaces:**
- CLI: `runo experiment new NAME [--from SPEC] [--dry-run] [--yes] [--json]`
- CLI: `runo experiment show [EXPERIMENT] [--json]`
- CLI: `runo experiment check [EXPERIMENT] [--json]`
- Action: `create_experiment(project_root: Path, experiment_id: str, spec_path: Path, dry_run: bool = False) -> ActionResult`

- [ ] **Step 1: Write failing command-tree and behavior tests**

```python
def test_experiment_new_from_spec_and_show_json(project_root: Path, spec_path: Path) -> None:
    created = runner.invoke(app, ["experiment", "new", "E1", "--from", str(spec_path), "--json", "--yes"])
    assert created.exit_code == 0
    payload = json.loads(created.stdout)
    assert payload["schema_version"] == 1
    assert payload["status"] == "success"
    shown = runner.invoke(app, ["experiment", "show", "E1", "--json"])
    assert json.loads(shown.stdout)["data"]["experiment"]["id"] == "E1"


def test_experiment_check_returns_one_for_errors(project_root: Path) -> None:
    result = runner.invoke(app, ["experiment", "check", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["status"] == "blocked"
```

Update the exact command-tree expectation with `experiment new`, `experiment show`, and `experiment check` for both executables.

- [ ] **Step 2: Verify CLI tests fail with an unknown command**

Run:

```bash
tssrun -p gr20001b uv run pytest tests/test_cli/test_experiment.py tests/test_cli/test_main.py tests/test_application/test_action_contract.py tests/test_mcp/test_registry.py -q
```

Expected: `No such command 'experiment'` and missing action binding.

- [ ] **Step 3: Implement the thin Typer group and rendering**

Use a common envelope:

```python
def _envelope(status: str, *, data: dict[str, Any], warnings: Sequence[str] = (), blockers: Sequence[str] = (), next_actions: Sequence[str] = ()) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": status,
        "data": data,
        "warnings": list(warnings),
        "blockers": list(blockers),
        "next_actions": list(next_actions),
    }
```

`new --dry-run` renders `ExperimentCreatePlan` and writes nothing. For machine use, `new --json` without `--yes` returns the plan and performs no writes; `new --json --yes` applies and returns created ledger/proposal paths. Human output may apply without `--yes` after showing the low-risk plan. Without `--from`, prompt for title, question, selected candidate, cost ceiling, and at least two complete candidates before planning. `show` requires an ID when multiple records exist and selects the sole record when omitted. `check` prints every issue and exits 1 only when an error-level issue exists.

- [ ] **Step 4: Add action registry metadata**

Add a `create_experiment` action and dispatch entry with exact signature parity:

```python
def create_experiment(
    project_root: Path,
    experiment_id: str,
    spec_path: Path,
    dry_run: bool = False,
) -> ActionResult:
    spec = read_experiment_spec(spec_path)
    plan = plan_create_experiment(
        ExperimentCreateRequest(project_root, experiment_id, spec)
    )
    if dry_run:
        return ActionResult(
            action="create_experiment",
            status=ActionStatus.SUCCESS,
            message=f"Planned experiment {experiment_id}",
            data={"dry_run": True, "proposal": str(plan.proposal_path)},
        )
    result = apply_create_experiment(plan)
    return ActionResult(
        action="create_experiment",
        status=ActionStatus.SUCCESS,
        message=f"Created experiment {experiment_id}",
        data={
            "dry_run": False,
            "ledger": str(result.ledger_path),
            "proposal": str(result.proposal_path),
        },
    )


"create_experiment": ActionSpec(
    name="create_experiment",
    description="Create a typed experiment record and proposal attachment.",
    required_params=("project_root", "experiment_id", "spec_path"),
    optional_params=("dry_run",),
    preconditions=("project loaded", "experiment ledger schema == 2", "experiment id unused"),
    state_change="-> experiment proposed",
    risk_level="low",
    cost_class="low",
    cli_commands=(("experiment", "new"),),
    mcp_tools=("runops.experiment.create",),
)


ToolSpec(
    "runops.experiment.create",
    "Create an experiment record and proposal. Disabled in MCP Slice 1.",
    WRITE_DISABLED,
    enabled=False,
    exposed=False,
    action_name="create_experiment",
)
```

Bind `("experiment", "new")` as a `write` operation. Add `WRITE_DISABLED = SafetyMetadata(level=3, safety_class="write", side_effects=True, writes_files=True)` and a disabled, unexposed `runops.experiment.create` ToolSpec pointing back to `create_experiment`; no MCP handler is exposed in Slice 1. `show` and `check` remain unbound read operations because the governed action catalog does not require every read-only command.

- [ ] **Step 5: Run tests and commit**

Run the Step 2 command. Expected: all CLI/action tests pass.

```bash
git add src/runops/cli src/runops/application/actions src/runops/mcp tests/test_cli tests/test_application/test_action_contract.py tests/test_mcp/test_registry.py
git commit -m "feat: add experiment inspection CLI"
```

---

### Task 5: Schema-v1 migration and new-project scaffold

**Files:**
- Modify: `src/runops/application/operator/migrations/v0.py`
- Modify: `src/runops/templates/scaffold/research/experiments.toml`
- Modify: `tests/test_application/test_migrations.py`
- Modify: `tests/test_cli/test_init.py`
- Modify: `tests/test_cli/test_update_harness.py`
- Modify: `docs/migrations/v0.md`
- Modify: `SPEC.md`
- Modify: `.codex/rules/commands.md`
- Modify: `.claude/rules/commands.md`

**Interfaces:**
- Migration: `M0-0004 Experiment ledger schema 2`
- Handler: `apply_experiment_ledger_v2(context: MigrationContext) -> MigrationResult`

- [ ] **Step 1: Write failing migration/scaffold tests**

```python
def test_experiment_v2_migration_preserves_unknown_fields_and_blocks_missing_science(project_root: Path) -> None:
    _write_v1_ledger(project_root, extra={"private_note": "keep"})
    result = run_migration("v0", "0004", project_root=project_root, yes=True)
    raw = _read_toml(project_root / "research/experiments.toml")
    assert result.status == "applied"
    assert raw["schema_version"] == 2
    assert raw["experiments"][0]["private_note"] == "keep"
    assert set(raw["experiments"][0]["migration_blockers"]) == {
        "title", "question", "cost_ceiling_core_hours"
    }


def test_new_project_scaffolds_empty_schema_v2_ledger(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init", "--path", str(tmp_path / "project"), "--yes", "--no-harnessops"])
    assert result.exit_code == 0
    assert _read_toml(tmp_path / "project/research/experiments.toml") == {"schema_version": 2}
```

- [ ] **Step 2: Verify migration and init tests fail**

Run:

```bash
tssrun -p gr20001b uv run pytest tests/test_application/test_migrations.py tests/test_cli/test_init.py tests/test_cli/test_update_harness.py -q
```

Expected: M0-0004 is unregistered and scaffold schema is 1.

- [ ] **Step 3: Implement human-gated idempotent migration**

Register number `0004`, type `breaking-project-state`, impact `("research", "experiment-ledger")`, `human_gate=True`. Dry-run reports only `research/experiments.toml`. Empty schema-1 ledgers become `{schema_version = 2}`. Existing records retain all known and unknown fields; missing `title`, `question`, or non-negative `cost_ceiling_core_hours` are listed in stable `migration_blockers`. Repeated application returns `skipped`. Invalid TOML and non-list experiments return warnings without replacing the source file.

- [ ] **Step 4: Update scaffold, specification, command references, and migration notes**

Document state ownership, derived phase, schema 2, the three canonical commands, JSON envelope, explicit migration command, and schema-1 compatibility window. Mirror shared command guidance in Codex and Claude rules intentionally.

- [ ] **Step 5: Run tests and commit**

Run the Step 2 command. Expected: all migration/init/update-harness tests pass.

```bash
git add src/runops/application/operator/migrations/v0.py src/runops/templates/scaffold/research/experiments.toml tests docs SPEC.md .codex/rules/commands.md .claude/rules/commands.md
git commit -m "feat: migrate experiment ledger to schema 2"
```

---

### Task 6: Slice-1 verification, coverage policy, and closeout

**Files:**
- Modify: `pyproject.toml`
- Modify: `docs/superpowers/plans/2026-07-11-experiment-cli-slice1.md`

**Interfaces:**
- Adds critical floors for `experiments/schema.py`, `experiments/projection.py`, and `experiments/workspace.py` at verified baselines no lower than 85%.

- [ ] **Step 1: Run focused quality checks**

```bash
tssrun -p gr20001b uv run ruff format --check src/ tests/
tssrun -p gr20001b uv run ruff check src/ tests/
tssrun -p gr20001b uv run mypy src/
tssrun -p gr20001b uv run pytest tests/test_application/test_experiment_gate.py tests/test_application/test_experiment_schema.py tests/test_application/test_experiment_projection.py tests/test_application/test_experiment_workspace.py tests/test_cli/test_experiment.py tests/test_application/test_migrations.py -q
```

Expected: all commands pass.

- [ ] **Step 2: Run the full branch-coverage gate**

```bash
tssrun -p gr20001b uv run pytest --cov=runops --cov-branch --cov-report=term-missing --cov-report=json:coverage.json --cov-fail-under=80
```

Expected: all tests pass and total branch coverage is at least 80%.

- [ ] **Step 3: Set and verify meaningful critical floors**

Read exact `percent_covered` values for the three new implementation modules from `coverage.json`; set floors to the greatest whole number not exceeding each baseline, with a minimum of 85. Do not put a floor on the facade or thin CLI.

```bash
tssrun -p gr20001b uv run python -m runops.application.operator.coverage_policy coverage.json
```

Expected: every governed module meets its floor.

- [ ] **Step 4: Review compatibility and close the plan**

Confirm schema-v1 bulk gate tests still pass, no public import moved without a facade, `runo`/`runops` command trees match, migration preserves unknown fields, generated skills have not yet been changed, and `git diff --check` is clean. Change plan status to `completed` and add an Outcome line with test count and coverage.

- [ ] **Step 5: Commit closeout**

```bash
git add pyproject.toml docs/superpowers/plans/2026-07-11-experiment-cli-slice1.md
git commit -m "docs: close experiment CLI slice 1"
```
