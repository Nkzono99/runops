### EMSES runops fallback guide

This generated guide is intentionally small. MPIEMSES3D-specific input review,
parameter design, run diagnosis, HDF5 output analysis, emout usage, and
visualization should come from the recommended external Codex plugins
`MPIEMSES3D Context` (`mpiemses3d-context`) and `emout Context`
(`emout-context`) when they are available.

Before using this fallback, run:

```bash
uvx --from runops runo plugins --check
uvx --from runops runo plugins --json
```

Use the `delegated_capabilities` index to route work such as `input-review`,
`parameter-design`, `run-diagnose`, `output-analysis`, and
`visualization-script` to the relevant plugin. runops does not install or
enable plugins; that remains user-local Codex state.

#### runops responsibilities

- Treat the run directory and `manifest.toml` as the source of truth.
- Let the EMSES adapter render `input/plasma.toml` and detect required outputs.
- Keep `work/`, `input/`, `submit/`, and `manifest.toml` under runops control.
- Keep MPI launch behavior in launcher/job.sh layers. Python should not become
  a rank wrapper.
- Use `runo runs create`, `runo runs submit`, `runo runs status`,
  `runo analyze summarize`, and `runo analyze collect` instead of ad hoc file movement.

#### Minimal fallback facts

- Main rendered input: `input/plasma.toml`.
- Common output categories: stdout/stderr logs, `energy`, HDF5 diagnostics, and
  restart snapshots. Use adapter-required output metadata for exact project
  checks.
- For namelist meaning, numerical stability, physical interpretation, emout
  APIs, and plotting details, prefer `MPIEMSES3D Context`, `emout Context`,
  enabled knowledge imports, project materials, or upstream documentation.

Do not treat this file as a full MPIEMSES3D manual. It is only the runops-side
handoff point when richer simulator context has not been installed or mounted.
