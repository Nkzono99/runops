---
id: H0001
record_type: hypothesis
created_at: '2026-05-12T23:33:05+09:00'
status: proposed
target_capability: harness_improvement_capture
source_eval_case: E0001
---

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
