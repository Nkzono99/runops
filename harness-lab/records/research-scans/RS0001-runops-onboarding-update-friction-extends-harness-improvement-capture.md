---
id: RS0001
record_type: research_scan
created_at: '2026-05-13T17:59:01+09:00'
status: captured
scope: harnessops-core
existing_dossier: IMP0001
classification:
  capability: harness_improvement_capture
  failure_class: missing_proactive_harness_lab_capture
evidence:
  local:
  - summary: User asked to rewrite setup-runops guidance, speed up tests, surface runops update guidance, support gh auth login during init, and update HarnessOps scaffold.
    ref: conversation-local runops session 2026-05-13
  codebase:
  - summary: Implemented setup-runops after-init guidance, update notice, GitHub auth preflight, and test-speed fixtures.
    ref: src/runops/templates/skills/setup-runops/SKILL.md; src/runops/cli/update_notice.py; src/runops/cli/init/github_auth.py; tests/conftest.py
  external: []
  risk:
  - summary: Generated .new view could hide existing imported feedback if accepted without review.
    ref: harness-lab/views/imported-feedback.md
candidates:
- title: Implementation-friction capture trigger
  relation: extends IMP0001
  recommendation: classify investigated and add guard candidate
  next_command: hops lab investigate/classify --from IMP0001
recommendation: classify
---

# RS0001: Runops onboarding/update friction extends harness improvement capture

## Scope

- scope: harnessops-core
- existing_dossier: IMP0001
- capability: harness_improvement_capture
- failure_class: missing_proactive_harness_lab_capture

## Evidence

### Local

- User asked to rewrite setup-runops guidance, speed up tests, surface runops update guidance, support gh auth login during init, and update HarnessOps scaffold. (ref: conversation-local runops session 2026-05-13)

### Codebase

- Implemented setup-runops after-init guidance, update notice, GitHub auth preflight, and test-speed fixtures. (ref: src/runops/templates/skills/setup-runops/SKILL.md; src/runops/cli/update_notice.py; src/runops/cli/init/github_auth.py; tests/conftest.py)

### External

- なし

### Risk And Counterexample

- Generated .new view could hide existing imported feedback if accepted without review. (ref: harness-lab/views/imported-feedback.md)

## Candidates

| candidate | relation | recommendation | next_command |
|---|---|---|---|
| Implementation-friction capture trigger | extends IMP0001 | classify investigated and add guard candidate | hops lab investigate/classify --from IMP0001 |

## Recommendation

classify

## Next Commands

- `hops lab investigate/classify --from IMP0001`
