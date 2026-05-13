---
name: hops-research-improvements
description: HarnessOps のメタ改善案を調査するときに使う。コードベース調査、既存 dossier 確認、web/外部事例調査、比較評価、改善仮説候補の分類、hops lab investigate/classify/capture/propose への接続を行う。
---

`hops doctor --check-overlay` を実行する。`.harnessops/`、`harness-feedback/`、`harness-lab/` の構造を直接組み替えない。

この skill は、作業中の30秒 `メタ仮説スキャン` とは別の、意図的な調査モードとして使う。ユーザーが「改善案を調査したい」「meta改善を探したい」「外部知見も含めて比較したい」と言ったとき、または release 前、同じ摩擦が複数回出た後、既存判断への反例が見えた後に使う。

## 調査手順

1. 調査スコープを1文で置く。対象 capability、疑っている failure class、既存 dossier に足す調査か新規候補探索かを決める。
2. `rg` でコード、docs、tests、skills、`harness-lab/views/*.md` を調べる。既存 dossier、判断、ガード、未解決 open question があれば優先する。
3. 外部比較が判断を変えそうな場合だけ web 調査する。検索語にローカルパス、非公開語、未公開研究の文脈を入れない。一次情報、公式 docs、論文、標準実務を優先し、URL を evidence として残す。
4. 観測を「local evidence」「codebase evidence」「external benchmark」「risk / counterexample」に分ける。
5. 既存テーマに入るなら新規 capture せず、`hops lab investigate` と `hops lab classify` で追記する。新しい failure class や cross-project pattern なら `hops lab capture` する。
6. 実装可能な候補だけ `hops lab new-eval-case` と `hops propose` に進める。仮説には mechanism、minimal implementation、alternative、evaluation plan、kill criteria を入れる。

## 使うコマンド

```bash
hops lab investigate --from IMP0001 --kind external-benchmark --summary "<比較結果>" --evidence-ref "<url-or-path>"
hops lab classify --from IMP0001 --source-type external-benchmark --scope harnessops-core --maturity investigated --relation extends
hops lab research-scan --title "<title>" --scope "<scope>" --capability "<capability>" --failure-class "<failure>" --candidate "<candidate>|<relation>|<recommendation>|<next command>" --recommendation "<recommendation>"
hops lab capture --title "<title>" --summary "<observation>" --expected-change "<expected>"
hops lab new-eval-case --from FB0001
hops lab memory lint --warn-only
hops lab compact --force
hops propose --from E0001 --hypothesis "<hypothesis>" --mechanism "<mechanism>" --minimal-implementation "<minimal>"
```

## 出力フォーマット

調査結果は短くまとめる。

- Scope: 対象 capability / failure class / 既存 dossier。
- Evidence: local path、コード上の根拠、外部URL、反例。
- Candidates: 改善候補、既存テーマとの relation、推奨コマンド。
- Recommendation: note、classify、capture、propose、park、reject のどれにするか。

複数候補があり、後からルーティングや比較評価に戻りそうな場合は、回答だけで終えず `hops lab research-scan` を使う。`--local-evidence`、`--codebase-evidence`、`--external-benchmark`、`--risk` は `summary|ref`、`--candidate` は `title|relation|recommendation|next command` の形で渡す。

## 判断基準

- 既存の `IMP` に足せるものは `hops lab investigate` に留める。
- 新規 capture は、将来の agent 行動、評価方法、移行方針、公開/非公開境界、複数 target/project に影響する場合だけにする。
- 外部実務を輸入するときは、そのまま一般ルールにせず、HarnessOps の失敗クラス、能力、ガードへ写像する。
- 「良さそう」だけで採用しない。評価ケース、比較ベースライン、ガード、または中止基準が作れないものは `park` する。
- skill や rule を増やすより、既存 workflow への統合、削除、migration、`update-harness` で整理できないかを先に見る。
- 既存 dossier が多くなり調査の入口が重い場合は、records を削除せず `hops lab memory lint --warn-only` で発火基準を確認する。`hops lab compact` は source ID へ戻れる deterministic snapshot として使い、抽象化が必要なら `hops-compact-lab-memory` skill に渡す。

## ガードレール

- 調査を長文化しない。候補は最大5件に絞る。
- web 由来の知見は必ず URL または出典名を残す。
- 未サニタイズ情報を外部検索語、Issue本文、PR本文へ出さない。
- リモート Issue 作成や外部共有は人間の明示なしに行わない。
- 採用済み改善への反例や拡張は、孤立レコードにせず `relation=contradicts` または `relation=extends` で既存 dossier に接続する。
