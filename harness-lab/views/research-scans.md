<!-- harnessops により生成; source records が正本 -->
# Research scans

- `RS0001` captured harness_improvement_capture missing_proactive_harness_lab_capture scope=harnessops-core recommendation=classify
- `RS0002` captured lab_classification_metadata missing_import_taxonomy_gate scope=harnessops-core recommendation=classify existing IMP0009 and queue taxonomy gating before manual scoring
- `RS0003` captured steward_lane_handoff transient_lane_artifact_loss scope=harnessops-core recommendation=Queue for priority review as a workflow-design research candidate; do not implement until schema, expiry, and promotion rules are evaluated.
- `RS0004` captured steward_validation repo_role_validation_blindspot scope=harnessops-core recommendation=Queue for later priority review; prefer target-owned health signal contracts over baking runops checks into HOPS core.
- `RS0005` captured target_intent_context steward_target_context_inference scope=harnessops-core recommendation=Queue as a workflow-design research candidate; priority lane should evaluate a read-only context contract before any implementation.
