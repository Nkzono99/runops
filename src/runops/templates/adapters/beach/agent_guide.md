### BEACH runops fallback guide

This generated guide is intentionally small. BEACH-specific parameter design,
configuration review, run diagnosis, output analysis, and visualization should
come from the recommended external Codex plugin `BEACH Context`
(`beach-context`) when it is available.

Before using this fallback, run:

```bash
uvx --from runops runo plugins --check
uvx --from runops runo plugins --json
```

Use the `delegated_capabilities` index to route BEACH work such as
`config-review`, `case-design`, `run-diagnose`, `output-analysis`, and
`visualization-script` to the plugin. runops does not install or enable the
plugin; that remains user-local Codex state.

#### runops responsibilities

- Treat the run directory and `manifest.toml` as the source of truth.
- Let the BEACH adapter render `input/beach.toml` and detect required outputs.
- Keep `work/`, `input/`, `submit/`, and `manifest.toml` under runops control.
- Use `runo runs create`, `runo runs submit`, `runo runs status`,
  `runo analyze summarize`, and `runo analyze collect` instead of ad hoc file movement.

#### Minimal fallback facts

- Main rendered input: `input/beach.toml`.
- Primary completion / summary file: `work/latest/summary.txt`.
- Common output categories: charge CSVs, mesh CSVs, history CSVs, and summary
  text. Use adapter-required output metadata for exact project checks.
- For parameter meaning, numerical stability, physical interpretation, and
  plotting details, prefer `BEACH Context`, enabled knowledge imports, project
  materials, or BEACH upstream documentation.

Do not treat this file as a full BEACH manual. It is only the runops-side
handoff point when richer simulator context has not been installed or mounted.
