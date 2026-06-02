# materials/ - source material for humans and agents

`materials/` is the visible place for source material that should stay easy to
find while working with an AI agent. Put papers, manuals, figures, copied
snippets, and small source indexes here.

This directory is different from generated runops state:

- `materials/`, `notes/`, and `research/` are human/agent shared workspace.
- `.runops/knowledge/` is generated agent context such as `enabled/imports.md`.
- `refs/` may contain optional mirrored external repositories when enabled with
  `runo init --with-refs` or managed manually.

## Suggested layout

| Path | Purpose |
| --- | --- |
| `papers/` | PDFs, BibTeX snippets, and paper-specific notes |
| `manuals/` | Site, simulator, and tool manuals supplied by humans |
| `figures/` | Reference figures that are not generated run outputs |
| `snippets/` | Copied examples, short configs, and source excerpts |
| `index.toml` | Optional hand-written or generated material index |

Large PDFs remain visible in VS Code Explorer, and the scaffolded VS Code
settings exclude `materials/**/*.pdf` from text search to keep search results
usable. The scaffolded `.gitignore` also treats bulky binaries such as
`materials/**/*.pdf`, `materials/**/*.pptx`, `materials/**/*.docx`, and
`materials/**/*.zip` as local by default while keeping `materials/README.md`
and `materials/index.toml` tracked.

## Notes

- Prefer relative links from `notes/reports/` to materials when writing reports.
- Do not put generated run outputs here; keep those under `runs/**/analysis/` or
  export bundles.
- If a material becomes part of shared lab knowledge, move or copy it into a
  dedicated knowledge source repository and attach it with
  `runo knowledge source attach`.
