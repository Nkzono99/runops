# Template Layout

This package stores text that runops copies or renders into user projects.
Keep Python-side routing in `runops.harness` / CLI modules, and keep generated
file bodies here.

Current layout:

- `harness/` — agent harness output templates. Agent-specific files live under
  `harness/<agent>/`; shared instruction templates live under
  `harness/shared/`. `CLAUDE.md` and `AGENTS.md` have separate entrypoint
  templates and include shared partials where their behaviour overlaps.
- `skills/` — shared `SKILL.md` source templates. They render to both
  `.claude/skills/` and `.agents/skills/`, with agent-specific invocation
  syntax injected by the harness builder.
- `scaffold/` — generic project scaffold files that are not primarily agent
  harness files, such as `.gitignore`, `campaign.toml`, `notes/`, and editor
  settings.
- `adapters/` — simulator-specific case/input templates and adapter guides.
- Root-level templates are legacy convenience paths. Avoid adding new files at
  the root; place them in the domain-specific directory instead.

Target shape over time:

```text
templates/
  adapters/
  harness/
    codex/
    claude/
    shared/
  project/
```

Move existing templates gradually when they are already being edited so
`runo update-harness` diffs remain understandable for existing projects.
