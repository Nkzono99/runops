# API Compatibility Guide

Refactoring a package is successful only if callers can continue to use the same public contract, unless a breaking change is explicitly requested.

## Public API signals

Treat these as public unless repository evidence says otherwise:

- Symbols listed in `__all__`.
- Symbols imported or defined in package-level `__init__.py`.
- Console scripts and entry points in packaging metadata.
- Documented examples and README imports.
- Test imports outside the module being changed.
- Public classes, functions, constants, and modules without a leading underscore.

## Static API snapshot process

Before editing:

```bash
python scripts/api_surface_snapshot.py snapshot --root . --output /tmp/api-before.json
```

After editing:

```bash
python scripts/api_surface_snapshot.py snapshot --root . --output /tmp/api-after.json
python scripts/api_surface_snapshot.py compare /tmp/api-before.json /tmp/api-after.json
```

A static snapshot is not a replacement for tests, but it catches accidental removals, renames, and export drift without importing the package.

## Re-export strategy

When moving a symbol, leave a re-export where callers already import it:

```python
# package/old_location.py
from .new_location import ExistingName

__all__ = ["ExistingName"]
```

Package root re-export:

```python
# package/__init__.py
from .new_location import ExistingName

__all__ = ["ExistingName"]
```

## Deprecation strategy

Only add warnings when the user asks for a migration path or when the repository already uses deprecation warnings. If warnings are added, use `stacklevel=2` so callers see their own call site.

```python
import warnings

from .new_location import new_function


def old_function(*args, **kwargs):
    warnings.warn(
        "old_function is deprecated; use new_function instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return new_function(*args, **kwargs)
```

## Entry points and CLI compatibility

When changing CLI modules:

- Check `[project.scripts]`, `[project.gui-scripts]`, `entry_points`, or `console_scripts`.
- Preserve command names, argument behavior, exit codes, stdout/stderr contract, and environment variable behavior.
- Add a smoke test such as `python -m package --help` or the generated command's `--help` where feasible.

## Serialization and error contracts

Treat these as compatibility-sensitive:

- JSON/YAML/schema field names.
- Exception classes and messages used in tests or docs.
- Dataclass/Pydantic model field defaults.
- Enum values.
- Path formats, file names, and cache keys.
