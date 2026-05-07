# Refactor Playbook for Python Packages

Use this playbook to reduce structural risk while keeping behavior stable.

## Large module decomposition

1. Identify cohesive clusters: data models, parsing, validation, I/O, formatting, orchestration, adapters.
2. Extract private helpers first. Prefer `_module.py` for implementation details and keep public names where they already are.
3. Add re-exports in the original module if callers may import moved symbols directly.
4. Move tests last only if the test layout becomes confusing. Do not rewrite assertions just because files moved.
5. Run targeted tests and API snapshot comparison after each extraction.

Good extraction sequence:

```text
package/core.py                 # public imports remain stable
package/_parsing.py             # extracted internals
package/_validation.py          # extracted internals
package/__init__.py             # unchanged or explicit re-exports
```

## Circular import cleanup

1. Confirm the cycle with import graph evidence or runtime traceback.
2. Classify the edge causing the cycle:
   - type-only dependency
   - shared constant/config
   - base class/protocol dependency
   - runtime factory dependency
   - package `__init__.py` re-export dependency
3. Apply the smallest fix:
   - move type-only imports under `if TYPE_CHECKING:` and use postponed annotations where compatible
   - move shared contracts to a neutral module such as `_types.py`, `_protocols.py`, or `_contracts.py`
   - inject a dependency instead of importing a concrete implementation
   - move import from package `__init__.py` to the concrete submodule
4. Use local imports only when the runtime dependency is genuinely lazy or expensive; otherwise treat local imports as a tactical workaround.

## Dependency boundaries

Prefer inward-facing dependencies:

```text
public API / CLI
    -> application services
        -> domain logic
            -> utilities/types
        -> adapters/integrations
```

Avoid domain modules importing CLI, HTTP clients, database adapters, or test fixtures. When a low-level module needs behavior from a higher-level module, define a protocol or callback at the lower level and let the higher level wire it.

## Compatibility shims

When moving a public symbol:

```python
# old_module.py
from .new_module import PublicClass, public_function

__all__ = ["PublicClass", "public_function"]
```

When replacing behavior, keep old names as thin wrappers until the user explicitly accepts a breaking change.

## Testability refactor

For code with weak tests:

1. Add characterization tests for current externally visible behavior.
2. Extract pure functions around business logic.
3. Separate I/O from transformation.
4. Add dependency injection for clocks, randomness, filesystem, network, and subprocess calls.
5. Keep snapshots small and semantic; avoid brittle full-output snapshots unless the output format is the contract.

## Naming and layout conventions

- Use `_private.py` modules for implementation details.
- Keep public modules stable unless the package is pre-release or the user requests breaking changes.
- Avoid catch-all `utils.py` growth; split by domain responsibility.
- Keep `__init__.py` lightweight. Heavy imports in `__init__.py` can cause slow imports and circular dependencies.
