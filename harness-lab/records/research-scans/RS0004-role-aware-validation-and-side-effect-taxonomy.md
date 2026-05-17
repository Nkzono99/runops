---
id: RS0004
record_type: research_scan
created_at: '2026-05-18T04:14:46+09:00'
status: captured
scope: harnessops-core
existing_dossier:
classification:
  capability: steward_validation
  failure_class: repo_role_validation_blindspot
evidence:
  local:
  - summary: runops declares target-repository role and repo-native safety/validation requirements; daily finalize policy requires repo-native validation plus HOPS checks before publish or merge.
    ref: .harnessops/project.toml
  codebase:
  - summary: AGENTS.md defines runops-specific validation commands and separates GitHub/repo writes from high-cost HPC execution concerns.
    ref: AGENTS.md
  external: []
  risk:
  - summary: 'Scope creep: HOPS should expose hooks and side-effect categories without embedding runops-specific validation logic.'
    ref: open-meta counterframe 20260518
candidates:
- title: Repo role health contract and side-effect taxonomy
  relation: new
  recommendation: Investigate target-owned validation signals and side-effect domains before proposing HOPS core changes.
  next_command: hops lab classify or eval-case create after priority selection
recommendation: Queue for later priority review; prefer target-owned health signal contracts over baking runops checks into HOPS core.
---

# RS0004: Role-aware validation and side-effect taxonomy

## Scope

- scope: harnessops-core
- existing_dossier: 未設定
- capability: steward_validation
- failure_class: repo_role_validation_blindspot

## Evidence

### Local

- runops declares target-repository role and repo-native safety/validation requirements; daily finalize policy requires repo-native validation plus HOPS checks before publish or merge. (ref: .harnessops/project.toml)

### Codebase

- AGENTS.md defines runops-specific validation commands and separates GitHub/repo writes from high-cost HPC execution concerns. (ref: AGENTS.md)

### External

- なし

### Risk And Counterexample

- Scope creep: HOPS should expose hooks and side-effect categories without embedding runops-specific validation logic. (ref: open-meta counterframe 20260518)

## Candidates

| candidate | relation | recommendation | next_command |
|---|---|---|---|
| Repo role health contract and side-effect taxonomy | new | Investigate target-owned validation signals and side-effect domains before proposing HOPS core changes. | hops lab classify or eval-case create after priority selection |

## Recommendation

Queue for later priority review; prefer target-owned health signal contracts over baking runops checks into HOPS core.

## Next Commands

- `hops lab classify or eval-case create after priority selection`
