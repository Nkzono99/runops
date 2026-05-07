# Refactor Anti-Patterns to Avoid

- Rewriting many modules before capturing baseline tests or API snapshots.
- Moving public symbols without re-export shims.
- Cleaning imports by deleting imports that are used dynamically or only under optional dependency paths.
- Replacing explicit code with clever abstractions that reduce readability.
- Creating a generic `utils.py` dumping ground instead of domain-specific modules.
- Adding new runtime dependencies for convenience during a behavior-preserving refactor.
- Changing `pyproject.toml` build backend or package discovery as a side effect of internal cleanup.
- Hiding circular imports with local imports everywhere instead of addressing dependency direction.
- Updating tests to match new internals while accidentally dropping behavior assertions.
- Reporting “all tests pass” after only running targeted tests.
- Ignoring baseline failures and then attributing all failures to the refactor.
- Importing packages for smoke tests when `__init__.py` starts services, reads secrets, performs network calls, or mutates production files.
