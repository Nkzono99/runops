---
name: python-package-refactor
description: Safely refactor Python packages and libraries with repository inspection, public API preservation, import-boundary cleanup, packaging modernization, tests, typing, linting, and behavior-preserving code changes. Use when working on Python package architecture, module layout, pyproject/setup configuration, dependency boundaries, circular imports, API compatibility, large-module decomposition, or refactoring pull requests. Do not use for isolated Python snippets or unrelated bug fixes unless the user asks for package-level refactoring.
---

# Python Package Refactor

Refactor Python packages as a controlled engineering change, not a rewrite. Preserve behavior and public API by default, make changes in small reversible batches, and verify each batch with evidence from the repository.

## Operating principles

- Start from repository evidence: package metadata, source layout, tests, imports, public exports, CI/tooling, and current failures.
- Preserve the public contract unless the user explicitly requests a breaking change. Treat `__all__`, package `__init__.py`, documented imports, tests, CLI entry points, and packaging metadata as API signals.
- Prefer incremental, PR-sized changes over broad rewrites. Keep diffs readable and explain tradeoffs.
- Do not change runtime dependencies, build backend, Python version support, import paths, serialization formats, or CLI behavior unless required by the requested refactor.
- Never claim success without running the strongest feasible verification gates. If the environment cannot run a gate, record the exact reason and use narrower static or smoke checks.
- Keep generated artifacts out of the repo unless requested. Use `/tmp` or `/mnt/data` for temporary reports when possible.

## Quick start

From the repository root:

```bash
uv run python .agents/skills/python-package-refactor/scripts/inspect_python_package.py --root . --format markdown
uv run python .agents/skills/python-package-refactor/scripts/api_surface_snapshot.py snapshot --root . --output /tmp/api-before.json
uv run python .agents/skills/python-package-refactor/scripts/refactor_quality_gate.py plan --root .
```

After a refactor batch:

```bash
uv run python .agents/skills/python-package-refactor/scripts/api_surface_snapshot.py snapshot --root . --output /tmp/api-after.json
uv run python .agents/skills/python-package-refactor/scripts/api_surface_snapshot.py compare /tmp/api-before.json /tmp/api-after.json
uv run python .agents/skills/python-package-refactor/scripts/refactor_quality_gate.py run --root . --output /tmp/refactor-gates.json
```

If this skill is installed somewhere other than `.agents/skills/python-package-refactor`, adjust the script paths to the actual skill directory.

## Workflow

### 1) Scope and baseline

1. Confirm the requested refactor goal, in-scope paths, and compatibility expectations from the prompt and repository context.
2. Inspect repository shape:
   - `pyproject.toml`, `setup.cfg`, `setup.py`, lockfiles, `tox.ini`, `noxfile.py`, CI files.
   - `src/` layout vs flat layout, package roots, namespace packages, tests, examples, docs.
   - configured tools such as pytest, ruff, black, mypy, pyright, tox, nox, hatch, poetry, pdm, or uv.
3. Capture a baseline before modifying files:
   - `git status --short`
   - `git diff --stat`
   - `inspect_python_package.py`
   - `api_surface_snapshot.py snapshot`
   - available tests or at least targeted import/syntax checks.
4. If baseline tests already fail, record those failures separately so they are not confused with regressions introduced by the refactor.

### 2) Plan the smallest safe cut

Write a concise refactor plan before editing. Include:

- Goal and non-goals.
- Files to touch and why.
- Expected API impact: `none`, `compatible`, or `intentional breaking`.
- Verification gates to run.
- Rollback strategy.

Choose the least invasive refactor that removes the bottleneck. Favor extraction, adapter modules, dependency inversion, and compatibility shims over wholesale rearchitecture.

### 3) Implement in small batches

Use these patterns when applicable:

- **Large module decomposition:** extract cohesive helpers into private modules first, then move public entry points only with re-export shims.
- **Circular import cleanup:** move shared types/protocols to a neutral module, replace module-level imports with dependency injection, and use local imports only as a temporary containment measure.
- **Public API preservation:** keep old import paths working via package-level re-exports or thin wrappers; add deprecation comments only when the user asks for migration behavior.
- **Packaging cleanup:** modernize `pyproject.toml` conservatively; do not switch build backends or package managers without a clear benefit and user intent.
- **Typing cleanup:** add annotations where they reduce ambiguity; avoid large type-only rewrites that obscure behavior-preserving diffs.
- **Testability refactor:** add characterization tests around current behavior before changing internals, especially for parsers, serializers, CLI paths, data models, and error handling.

### 4) Verify after each meaningful batch

Run gates from narrow to broad:

1. Syntax/AST parse for touched files.
2. Targeted tests for touched behavior.
3. Import smoke for top-level packages when safe.
4. API surface comparison.
5. Lint/type checks that are configured in the repo.
6. Full test suite or tox/nox matrix when feasible.

Do not overstate results. If only targeted tests ran, say that. If a tool is not installed, report the skipped gate and the command that would run in a provisioned environment.

### 5) Final delivery contract

When reporting results, include:

- **Scope:** files/modules changed and the refactor goal achieved.
- **Compatibility:** public API impact and any intentional migration notes.
- **Verification:** commands run, pass/fail result, and baseline failures if any.
- **Risk:** residual risk and the most useful next verification step.
- **Diff hygiene:** mention uncommitted/generated files only if relevant.

## Gate policy

Use these labels in final readiness calls when helpful:

- **READY**: No new failures in feasible gates, public API snapshot changes are expected, and touched behavior has tests or smoke coverage.
- **READY WITH CAVEATS**: The refactor appears correct, but a broad gate could not run, baseline failures exist, or coverage is partial. State the caveat precisely.
- **BLOCKED**: A new syntax error, test failure, unintended public API change, dependency/build metadata regression, or import regression remains. Provide concrete unblock steps.

## Reference routing

Load the smallest relevant reference file:

- `references/refactor-playbook.md` for module decomposition, circular imports, dependency boundaries, and behavior-preserving patterns.
- `references/api-compatibility.md` for public API preservation, re-export shims, entry points, and deprecation strategy.
- `references/verification.md` for gate selection, baseline handling, and final reporting.
- `references/packaging-modernization.md` for `pyproject.toml`, package discovery, lockfiles, optional dependencies, and package data.
- `references/anti-patterns.md` for common refactor failures to avoid.

## Tooling notes

The bundled scripts use only the Python standard library. They are safe to copy into a repository-local tools directory if the skill path is inconvenient.

- `scripts/inspect_python_package.py` — repository/package shape, tool detection, AST issues, import graph hints, hotspots.
- `scripts/api_surface_snapshot.py` — static public API snapshot and before/after comparison without importing project code.
- `scripts/import_smoke.py` — optional top-level import smoke test. Use carefully for packages with import-time side effects.
- `scripts/refactor_quality_gate.py` — proposes or runs a practical gate stack based on repository configuration.
