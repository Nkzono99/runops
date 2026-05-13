---
id: FB0003
record_type: imported_feedback
created_at: '2026-05-13T22:41:39+09:00'
status: triaged
source:
  type: local-capture
  original_id: runops src/runops/harness/harnessops.py; harnessops profiles/builtins/runops-project.yml; harnessops core/agent_bridge.py
  source_project: runops
classification:
  capability: role_scoped_agent_bridge
  failure_class: project_feedback_interface_too_broad
links:
  eval_case:
  issue_url: https://github.com/Nkzono99/harnessops/issues/12
  issue_repo: Nkzono99/harnessops
---

# FB0003: Project-side feedback-source repositories need a role-scoped interface

## 概要

runops project directories initialize HarnessOps with profile=runops-project, which is feedback-source mode and writes harness-feedback/. In that role agents mainly need feedback capture/export plus lifecycle checks, but the generic agent bridge exposes broader harness-lab/eval/propose commands that belong to target or meta repositories. This blurs the boundary between project-side private feedback capture and upstream adoption decisions.

## 再現

In runops, runo init delegates to hops init --profile runops-project --with-agent-bridge. The runops-project profile is mode=feedback-source with path=harness-feedback, while the generated HarnessOps bridge lists lab capture/dossier/investigate/classify/new-eval-case/propose/eval/decide commands as general guidance.

## 期待する上流変更

HarnessOps should provide a project-side minimal interface or role-scoped bridge for feedback-source repositories, exposing init/doctor/update-harness/migrate and feedback commands while keeping lab/eval/propose/decide guidance scoped to upstream-lab or meta-lab repositories.
