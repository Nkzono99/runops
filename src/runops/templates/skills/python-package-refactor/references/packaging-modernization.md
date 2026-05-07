# Packaging Modernization Notes

Modernize packaging conservatively. Packaging changes can break installation, editable installs, source distributions, wheels, entry points, package data, and downstream imports.

## Inspection checklist

- `pyproject.toml`: build system, project metadata, dependencies, optional dependencies, tool configs.
- `setup.cfg` / `setup.py`: legacy metadata, package discovery, entry points, package data.
- Lockfiles: `uv.lock`, `poetry.lock`, `pdm.lock`, `requirements*.txt`.
- Build/test tools: tox, nox, hatch, poetry, pdm, uv, setuptools, flit.
- Source layout: `src/package` vs flat `package`.
- Namespace packages and implicit namespace packages.
- Package data: `MANIFEST.in`, `include-package-data`, `tool.setuptools.package-data`.

## Conservative modernization rules

- Do not switch package manager or build backend unless explicitly requested.
- Do not remove `setup.py` or `setup.cfg` until metadata is fully represented elsewhere and the project no longer relies on imperative setup behavior.
- Preserve Python version classifiers and `requires-python` unless the user requests a support policy change.
- Preserve extras names because downstream users may install `package[extra]`.
- Preserve entry point names and target callables unless a CLI migration is explicitly requested.
- Build metadata changes should be followed by at least import smoke and, when feasible, wheel/sdist build checks.

## `src/` layout migration caution

Moving to `src/` can improve test isolation but is a high-impact change. It requires updates to package discovery, tests, imports, CI, docs, and editable install assumptions. Treat it as a separate refactor unless it is the user's explicit goal.

## Package data caution

When moving modules, verify data file access patterns:

- `importlib.resources.files(...)`
- `pkg_resources` legacy access
- relative filesystem paths based on `__file__`
- templates, schemas, fixtures, py.typed, type stubs

Package data failures often appear only after building/installing a wheel, not when running from the source tree.
