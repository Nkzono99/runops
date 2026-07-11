# Action Contract and Critical Coverage Gates Design

**Status:** approved
**Date:** 2026-07-11

## Purpose

Wave 1 closes two related quality gaps without widening runops's public CLI:

1. effectful ActionSpec-facing CLI/MCP operations must remain bidirectionally
   consistent with their application action contract;
2. globally high coverage must not hide regressions in a small set of critical
   execution, state, security, adapter, and audit modules.

The change adds explicit metadata and conformance checks. It does not generate
Typer signatures or MCP handlers from ActionSpec and does not introduce a new
runtime dependency.

## Scope

### Governed CLI operations

The first version governs the existing ActionSpec-facing surface: command paths
that expose an application action or a safety-gated run lifecycle operation.
This includes run creation/survey expansion, submission/sync/retry/lifecycle,
analysis summarize/collect/export, and curated knowledge mutation already named
by `ACTION_SPECS`.

The existing read-only `show_log` ActionSpec also participates so ActionSpec
mappings round-trip completely. This does not require other read-only CLI
commands to enter the catalog; new mandatory coverage remains limited to
state-changing/external operations.

Scaffolding, migration, configuration editing, note/report workspace creation,
and other operator utilities remain covered by the exact command-tree tests but
are not retroactively converted to ActionSpec in this wave. Adding an ActionSpec
for those surfaces is a later, explicit contract decision.

### Governed MCP operations

Every MCP tool named by an ActionSpec receives an explicit `action_name` binding.
Every `external` or `destructive` ToolSpec must have such a binding even when the
tool is disabled and unexposed by default. Read/inspect tools need no binding
unless an ActionSpec already advertises them.

### Critical coverage modules

The policy initially governs these source files and combined line/branch floors:

| Module | Floor |
|---|---:|
| `src/runops/core/manifest.py` | 95% |
| `src/runops/application/execution/submission.py` | 90% |
| `src/runops/core/state.py` | 90% |
| `src/runops/core/event_log.py` | 80% |
| `src/runops/slurm/submit.py` | 90% |
| `src/runops/adapters/contrib/beach/adapter.py` | 80% |
| `src/runops/application/analysis/story.py` | 80% |

These floors are below or equal to the verified 2026-07-11 baseline and are
intended as regression guards, not aspirational coverage targets. Raising a
floor is a separate reviewed change. Lowering one requires an explicit rationale
in the commit or review description.

## CLI operation bindings

Add `src/runops/cli/operations.py` with immutable metadata:

```python
@dataclass(frozen=True)
class CliOperationBinding:
    command_path: tuple[str, ...]
    action_names: tuple[str, ...]
    effect: Literal["read", "write", "external", "destructive"]
```

`CLI_OPERATION_BINDINGS` is the explicit CLI-side view of the governed surface.
It is not used to synthesize commands. Existing `cli/groups/*` and `main.py`
continue to register callbacks normally, so command signatures and help output
remain stable.

Multiple action names are allowed because one command may expose distinct plans
or apply paths. For example, `runs retry` maps to `plan_retry` and `retry_run`.
Bindings are keyed by exact grouped command path and must not contain duplicates.

## MCP operation bindings

Extend `ToolSpec` with an optional `action_name: str = ""`. The value is included
in machine-readable tool metadata only when non-empty. Existing names, safety
metadata, enabled/exposed behavior, and result envelopes do not change.

The current bindings include:

- `runops.job.plan_submit` and `runops.job.submit` → `submit_run`
- `runops.job.cancel` → `cancel_run`
- `runops.run.delete` → `delete_run`
- existing read/inspect tools named by an ActionSpec, such as run logs, retain
  their advertised ActionSpec relation

## Bidirectional conformance invariants

Tests and `mcp check` enforce all of the following:

1. every `CliOperationBinding.action_names` value exists in `ACTION_SPECS`;
2. every CLI path advertised by an ActionSpec appears in exactly one CLI binding;
3. every CLI binding path exists in the Typer command tree;
4. the action names listed by the CLI binding exactly match the ActionSpecs that
   advertise that path;
5. every ActionSpec MCP tool exists and its ToolSpec points back to that action;
6. every ToolSpec with `action_name` is advertised by the corresponding
   ActionSpec;
7. every external/destructive ToolSpec has an ActionSpec binding and explicit
   confirmation metadata.

Failure messages list the missing or conflicting command/tool and action names.
Conformance does not infer effects from command names, options, or callback
implementation because those heuristics are unstable.

## Coverage policy

Store policy data in `pyproject.toml`:

```toml
[tool.runops.coverage-policy.modules]
"src/runops/core/manifest.py" = 95
```

Add `src/runops/application/operator/coverage_policy.py`, which:

- reads coverage.py JSON output and the policy table;
- uses each file's combined line/branch `percent_covered` value;
- reports missing files, malformed thresholds, and each floor violation;
- returns exit code 0 only when every governed module meets its floor;
- provides a small `python -m` entry point without adding a console script.

The internal API is:

```python
@dataclass(frozen=True)
class CoverageViolation:
    path: str
    actual: float | None
    required: float
    reason: str

def load_coverage_policy(config_path: Path) -> dict[str, float]: ...
def evaluate_coverage_policy(
    report_path: Path,
    policy: Mapping[str, float],
) -> tuple[CoverageViolation, ...]: ...
def main(argv: Sequence[str] | None = None) -> int: ...
```

The module command accepts `COVERAGE_JSON` and optional
`--config PYPROJECT_TOML`; the config defaults to `pyproject.toml` in cwd.

The checker is deterministic and filesystem-only. It does not invoke tests or
Git and is unit-tested with temporary JSON/TOML fixtures.

CI and publish verification run one coverage command that emits both terminal
and JSON reports, followed by the policy checker:

```bash
uv run pytest --cov=runops --cov-branch --cov-report=term-missing \
  --cov-report=json:coverage.json --cov-fail-under=80
uv run python -m runops.application.operator.coverage_policy coverage.json
```

`coverage.json` remains an untracked build artifact. The standard `$check`
skill and `.codex/rules/dev-workflow.md` use the same commands.
The repository `.gitignore` adds `coverage.json`; generated runops project
gitignore templates do not change because this is a runops-development artifact.

## Error handling

- Duplicate CLI bindings are an import-time configuration error in tests, not a
  silent last-write-wins map.
- Unknown action names and asymmetric mappings fail conformance with exact paths.
- Missing or invalid coverage JSON exits nonzero with one concise diagnostic.
- A policy path absent from the report is a failure; it is never treated as 0%
  success or silently skipped.
- Thresholds must be numeric values in the closed interval `[0, 100]`.

## Testing

### Action contract tests

- characterize the current governed CLI path set;
- prove missing, duplicate, extra, and mismatched bindings are rejected;
- verify `runs retry` supports its two ActionSpecs;
- verify unsafe MCP tools cannot omit `action_name`;
- verify ActionSpec and ToolSpec MCP mappings agree in both directions;
- keep the exact `runo`/`runops` command-tree test unchanged.

### Coverage policy tests

- all modules meet floors;
- one module below floor reports actual and required percentages;
- policy file missing from coverage JSON fails;
- malformed JSON and invalid thresholds fail clearly;
- real repository coverage output passes the policy in CI.

### Regression gates

- Ruff format/check for `src/` and `tests/`;
- strict mypy for `src/`;
- full pytest suite;
- global branch coverage floor 80%;
- critical-module coverage policy.

## Compatibility and migration

There is no project-state migration and no CLI/MCP name change. `ToolSpec.to_dict()`
adds `action_name` only for bound tools; consumers that ignore unknown metadata
remain compatible. The coverage policy affects only runops development and
release verification.

## Deferred decisions

- converting every read-only or operator CLI command into a shared operation
  catalog;
- generating Typer callbacks, MCP handlers, or safety metadata from ActionSpec;
- changed-line coverage and third-party diff-coverage dependencies;
- adding ActionSpecs for notes, migration, setup, and workspace scaffolding.
