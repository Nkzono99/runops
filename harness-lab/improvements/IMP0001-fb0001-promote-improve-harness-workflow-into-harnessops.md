---
id: IMP0001
record_type: improvement_dossier
created_at: '2026-05-13T17:57:54+09:00'
updated_at: '2026-05-13T17:59:47+09:00'
status: active
source_type: codebase-and-local-friction
scope: harnessops-core
maturity: investigated
relation: extends
promotion_level: target-lab-case
source_feedback: FB0001
eval_cases:
- E0001
hypotheses:
- H0001
decisions: []
research_scans:
- RS0001
classification:
  capability: harness_improvement_capture
  failure_class: missing_proactive_harness_lab_capture
guard:
  status: candidate
  path: hops-update-harness conflict review and generated-view drop warning
investigation:
- created_at: '2026-05-13T17:58:32+09:00'
  kind: codebase
  summary: 'Recent runops onboarding fixes show this capability must capture implementation-time friction, not only issue triage: setup-runops guidance had to account for skills being distributed only after init/setup, agent-owned doctor checks, baseline commit guidance, PyPI-style update notices, gh auth preflight before file writes, and test-speed guard fixtures.'
  evidence_ref: src/runops/templates/skills/setup-runops/SKILL.md; src/runops/cli/update_notice.py; src/runops/cli/init/github_auth.py; tests/conftest.py; tests/test_cli/test_init_github_auth.py; tests/test_cli/test_update_notice.py
- created_at: '2026-05-13T17:58:39+09:00'
  kind: risk
  summary: The HOPS update generated a .new view that would have replaced an existing imported-feedback entry with an empty view. Manual review prevented data loss, suggesting update-harness conflict handling should preserve record-derived views or surface a stronger warning when a generated view drops known records.
  evidence_ref: harness-lab/views/imported-feedback.md; .agents/skills/hops-update-harness/SKILL.md
links:
  issue_url:
---

# IMP0001: FB0001: Promote improve_harness workflow into HarnessOps

## Status

- status: active
- maturity: investigated
- source_type: codebase-and-local-friction
- scope: harnessops-core
- relation: extends
- promotion_level: target-lab-case
- source_feedback: `FB0001`
- linked_records: `FB0001`, `RS0001`, `E0001`, `H0001`

## Source Observation

Source: `harness-lab/records/feedback/FB0001-promote-improve-harness-workflow-into-harnessops.md`

# FB0001: Promote improve_harness workflow into HarnessOps

## 概要

runops の harness 改善で、runo init が tools/runops を editable install する前提を外し、Agent guide を .runops/knowledge/runops/ に生成するよう整理した。この過程で、issue 経由ではない harness 改善の判断・設計・検証が HarnessOps lab に記録されにくいことが分かった。さらに runops 側の improve_harness skill は、実質的には特定 target に閉じない「ハーネス監査・改善・drift 点検・upstream feedback 化」の汎用ワークフローであり、HarnessOps 側の skill/capability として持つ方が自然に見える。

## 再現

runops で tools/runops editable install を廃止する修正中、Agent が improve-harness skill を使って設計・実装・docs/tests 更新を進めた。変更は有用な harness 改善経験だったが、GitHub issue 起点ではないため、HarnessOps の feedback/lab ループへ自然には入らなかった。

## 期待する上流変更

HarnessOps に improve-harness 相当の汎用 skill/capability を追加し、target repo の harness 改善作業を issue 化前に lab capture する流れを標準化する。理想的には、今回のような init/bootstrap/harness/generated knowledge の整理が行われた時点で、HOPS 側から「これは lab に残すべき改善経験ではないか」と提案できる。

## Target Capability

- capability: harness_improvement_capture
- failure_class: missing_proactive_harness_lab_capture

## Investigation

- 2026-05-13T17:58:32+09:00 [codebase] Recent runops onboarding fixes show this capability must capture implementation-time friction, not only issue triage: setup-runops guidance had to account for skills being distributed only after init/setup, agent-owned doctor checks, baseline commit guidance, PyPI-style update notices, gh auth preflight before file writes, and test-speed guard fixtures. (evidence: src/runops/templates/skills/setup-runops/SKILL.md; src/runops/cli/update_notice.py; src/runops/cli/init/github_auth.py; tests/conftest.py; tests/test_cli/test_init_github_auth.py; tests/test_cli/test_update_notice.py)
- 2026-05-13T17:58:39+09:00 [risk] The HOPS update generated a .new view that would have replaced an existing imported-feedback entry with an empty view. Manual review prevented data loss, suggesting update-harness conflict handling should preserve record-derived views or surface a stronger warning when a generated view drops known records. (evidence: harness-lab/views/imported-feedback.md; .agents/skills/hops-update-harness/SKILL.md)

## Research Scans

### RS0001: RS0001: Runops onboarding/update friction extends harness improvement capture


Source: `harness-lab/records/research-scans/RS0001-runops-onboarding-update-friction-extends-harness-improvement-capture.md`


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


## Evaluation

### E0001: E0001: FB0001-promote-improve-harness-workflow-into-harnessops を評価


- source: `harness-lab/records/eval-cases/E0001-fb0001-promote-improve-harness-workflow-into-harnessops.md`

- capability: harness_improvement_capture

- failure_class: missing_proactive_harness_lab_capture

- manual_eval: 未実施


## Hypotheses

### H0001: H0001: E0001-fb0001-promote-improve-harness-workflow-into-harnessops の仮説


Source: `harness-lab/records/hypotheses/H0001-e0001-fb0001-promote-improve-harness-workflow-into-harnessops.md`


# H0001: E0001-fb0001-promote-improve-harness-workflow-into-harnessops の仮説

## 仮説

HarnessOps に improve-harness 相当の汎用 skill/capability を置くと、target repo 内で起きた非 issue 起点の harness 改善を、実装中または完了直後に lab feedback として捕捉しやすくなる。

## メカニズム

HOPS が target harness の変更差分、生成 template、agent skills、policy/rules、docs drift を点検する標準ワークフローを提供し、改善作業の終盤で lab capture 候補を明示する。target 側 skill は薄い bridge にし、分類・capture・eval/proposal は HOPS 側へ委譲する。

## 最小実装

HarnessOps 側に improve-harness skill を追加する。手順は doctor/check-overlay、target harness drift scan、変更分類、lab capture prompt、必要なら new-eval-case/propose まで。runops 側の improve-harness は HOPS bridge を呼ぶ形へ縮小する。

## 代替案: 削除または統合

各 target repo が独自に improve_harness skill を持ち続ける。ただし経験が target ごとに分散し、HarnessOps が横断的に改善提案する材料が残りにくい。

## 期待される利点

issue 化されない改善過程も harness-lab に残り、HOPS が将来の target harness 改善を能動提案できる材料になる。runops 以外の target にも再利用できる。

## 想定される欠点

HOPS 側 skill が抽象化しすぎると、target 固有の実装知識が薄くなる。target bridge skill との責務境界を明確にする必要がある。

## 評価計画

1. HOPS 側に improve-harness skill を作る。2. runops の今回の editable install 廃止ケースを fixture/eval case にする。3. target repo で harness/template/skill/rules の大きな差分が出たときに lab capture 候補を提案できるか手動評価する。

## 中止基準

HOPS 側へ寄せることで target 固有の修正判断が曖昧になり、既存 target skill より作業品質が下がる場合は採用しない。lab capture がノイズ化して有用な改善経験を埋もれさせる場合も中止する。


## Evidence

評価結果はまだありません。

## Guard

- status: candidate
- path: hops-update-harness conflict review and generated-view drop warning

## Links

- issue_url: 未設定

## Open Questions And Next Action

次の実装または評価ステップは、この dossier と紐づく正規化レコードを更新してから再生成してください。

## Decision Log

判断レコードはまだありません。
