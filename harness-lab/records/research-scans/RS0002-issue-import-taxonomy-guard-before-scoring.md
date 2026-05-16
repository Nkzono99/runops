---
id: RS0002
record_type: research_scan
created_at: '2026-05-17T04:17:24+09:00'
status: captured
scope: harnessops-core
existing_dossier: IMP0009
classification:
  capability: lab_classification_metadata
  failure_class: missing_import_taxonomy_gate
evidence:
  local:
  - summary: 'Issue lane imported #84-#88 as FB0010-FB0014 and created IMP0010-IMP0014; all five remain unclassified before evaluator scoring'
    ref: harness-lab/views/improvements.md
  codebase:
  - summary: lab review queue prioritizes IMP0010-IMP0014 for manual eval/decisions while capability and failure_class are unclassified
    ref: hops lab review queue --json
  external: []
  risk:
  - summary: Scoring five related GitHub Flow records before taxonomy and relation are clear can fragment evaluator effort and hide the shared delegated-finalization capability
    ref: harness-lab/records/feedback/FB0010-hops-github-flow-pr-label.md; harness-lab/records/feedback/FB0011-hops-github-flow-pr-view-checks-watch.md; harness-lab/records/feedback/FB0013-hops-github-flow-merge-merge-strategy.md; harness-lab/records/feedback/FB0014-hops-github-flow-merge-json-post-merge.md
candidates:
- title: Issue-import classification gate
  relation: extends IMP0009
  recommendation: Require import/propose flow to capture capability/failure_class before manual eval queue, or mark records blocked for classification
  next_command: hops lab classify/backfill or import taxonomy option
- title: Bundle related github-flow records
  relation: queued_for_later
  recommendation: Classify FB0010-FB0014 under a common GitHub Flow finalization capability before evaluator decides each separately
  next_command: hops lab investigate/classify related IMP0010-IMP0014
recommendation: classify existing IMP0009 and queue taxonomy gating before manual scoring
---

# RS0002: Issue import taxonomy guard before scoring

## Scope

- scope: harnessops-core
- existing_dossier: IMP0009
- capability: lab_classification_metadata
- failure_class: missing_import_taxonomy_gate

## Evidence

### Local

- Issue lane imported #84-#88 as FB0010-FB0014 and created IMP0010-IMP0014; all five remain unclassified before evaluator scoring (ref: harness-lab/views/improvements.md)

### Codebase

- lab review queue prioritizes IMP0010-IMP0014 for manual eval/decisions while capability and failure_class are unclassified (ref: hops lab review queue --json)

### External

- なし

### Risk And Counterexample

- Scoring five related GitHub Flow records before taxonomy and relation are clear can fragment evaluator effort and hide the shared delegated-finalization capability (ref: harness-lab/records/feedback/FB0010-hops-github-flow-pr-label.md; harness-lab/records/feedback/FB0011-hops-github-flow-pr-view-checks-watch.md; harness-lab/records/feedback/FB0013-hops-github-flow-merge-merge-strategy.md; harness-lab/records/feedback/FB0014-hops-github-flow-merge-json-post-merge.md)

## Candidates

| candidate | relation | recommendation | next_command |
|---|---|---|---|
| Issue-import classification gate | extends IMP0009 | Require import/propose flow to capture capability/failure_class before manual eval queue, or mark records blocked for classification | hops lab classify/backfill or import taxonomy option |
| Bundle related github-flow records | queued_for_later | Classify FB0010-FB0014 under a common GitHub Flow finalization capability before evaluator decides each separately | hops lab investigate/classify related IMP0010-IMP0014 |

## Recommendation

classify existing IMP0009 and queue taxonomy gating before manual scoring

## Next Commands

- `hops lab classify/backfill or import taxonomy option`
- `hops lab investigate/classify related IMP0010-IMP0014`
