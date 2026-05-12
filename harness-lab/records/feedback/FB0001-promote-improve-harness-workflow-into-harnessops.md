---
id: FB0001
record_type: imported_feedback
created_at: '2026-05-12T23:32:08+09:00'
status: triaged
source:
  type: local-capture
  original_id: 'runops working-tree: remove tools/runops editable init and generated
    agent guide refactor'
  source_project: runops
classification:
  capability: harness_improvement_capture
  failure_class: missing_proactive_harness_lab_capture
links:
  eval_case:
  issue_url:
---

# FB0001: Promote improve_harness workflow into HarnessOps

## 概要

runops の harness 改善で、runo init が tools/runops を editable install する前提を外し、Agent guide を .runops/knowledge/runops/ に生成するよう整理した。この過程で、issue 経由ではない harness 改善の判断・設計・検証が HarnessOps lab に記録されにくいことが分かった。さらに runops 側の improve_harness skill は、実質的には特定 target に閉じない「ハーネス監査・改善・drift 点検・upstream feedback 化」の汎用ワークフローであり、HarnessOps 側の skill/capability として持つ方が自然に見える。

## 再現

runops で tools/runops editable install を廃止する修正中、Agent が improve-harness skill を使って設計・実装・docs/tests 更新を進めた。変更は有用な harness 改善経験だったが、GitHub issue 起点ではないため、HarnessOps の feedback/lab ループへ自然には入らなかった。

## 期待する上流変更

HarnessOps に improve-harness 相当の汎用 skill/capability を追加し、target repo の harness 改善作業を issue 化前に lab capture する流れを標準化する。理想的には、今回のような init/bootstrap/harness/generated knowledge の整理が行われた時点で、HOPS 側から「これは lab に残すべき改善経験ではないか」と提案できる。
