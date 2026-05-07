# Verification Matrix

Use the strongest feasible gate stack while keeping feedback fast.

## Baseline first

Run verification before edits when practical. If a gate fails before the refactor, preserve the output and separate it from new failures.

Minimum baseline:

```bash
git status --short
git diff --stat
python scripts/inspect_python_package.py --root . --format markdown
python scripts/api_surface_snapshot.py snapshot --root . --output /tmp/api-before.json
```

## Gate selection

| Situation | Preferred gates |
|---|---|
| Touched one pure module | targeted unit tests, AST parse, API snapshot compare |
| Moved public symbols | API snapshot compare, import smoke, targeted import tests |
| Changed CLI/entry point | CLI `--help`, targeted CLI tests, packaging metadata check |
| Changed pyproject/setup | build metadata check, package discovery, tests, import smoke |
| Broke circular imports | import smoke, targeted tests, import graph inspection |
| Added typing | mypy/pyright if configured, tests |
| Large package reshaping | targeted tests per area, full pytest, tox/nox if configured |

## Recommended command order

```bash
python scripts/refactor_quality_gate.py plan --root .
python scripts/refactor_quality_gate.py run --root . --output /tmp/refactor-gates.json
```

If auto-running is too broad, manually run the subset relevant to touched files.

## Failure handling

- Do not continue broad refactoring when a new syntax error exists.
- For new test failures, inspect whether the failure is expected from an intentional contract change. If not, fix before proceeding.
- For baseline failures, keep them visible and avoid claiming the repository is fully green.
- For missing tooling, report the skipped command and avoid inventing pass results.

## Final report template

```text
Refactor readiness: READY | READY WITH CAVEATS | BLOCKED

Scope:
- ...

Compatibility:
- Public API: unchanged | compatible shim added | intentional breaking change
- Entry points: unchanged | changed as documented

Verification:
- PASS python -m pytest tests/test_x.py
- PASS API snapshot compare
- SKIPPED python -m mypy package (mypy not installed)

Residual risk:
- ...
```
