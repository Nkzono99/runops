---
name: hops-research-improvements
description: HarnessOps core、または HarnessOps を導入した target/project repository で、既に出たハーネス改善案を evidence、既存 dossier/feedback、外部事例、比較評価、park/reject、hops lab/feedback workflow へ接続するときに使う。発散的な最初の発想だけが目的なら hops-open-meta-scan を先に使い、この skill は raw ideas を選別・調査・記録候補化する selection/routing lane として使う。
---
Use `uvx --from harnessops hops <command>` for CLI invocations in target/project repos; do not rely on `hops` being on PATH.

`hops doctor --check-overlay` を実行する。`.harnessops/project.toml` を読み、現在の repo が HarnessOps core、target repository、project repository のどれかを確認する。`.harnessops/`、`harness-feedback/`、`harness-lab/` の構造を直接組み替えない。

この skill は、作業中の30秒 `メタ仮説スキャン` と `hops-open-meta-scan` の open invention lane とは別の、意図的な調査・選別モードとして使う。ユーザーが「改善案を調査したい」「外部知見も含めて比較したい」「この raw idea を lab に載せるべきか見たい」と言ったとき、release 前、同じ摩擦が複数回出た後、既存判断への反例が見えた後、または target/project repo で harness の改善候補を証拠化したいときに使う。

repo 役割ごとの扱い:

- HarnessOps core または target repository（`harness-lab/` を持つ repo）では、改善調査を `hops lab research-scan`、`hops lab investigate`、`hops lab classify`、必要なら `hops lab capture`、`hops lab new-eval-case`、`hops propose` へ進める。
- project repository（`harness-feedback/` を持つ repo）では、上流改善の採用判断や `harness-lab/` 作成をしない。観測した失敗や改善候補を `hops add-failure`、`hops route`、`hops add-feedback`、`hops feedback export --sanitize` へ進め、target/HarnessOps 側で import/eval/propose できる形にする。
- 役割が曖昧な場合は、`hops detect` と `.harnessops/project.toml` を確認し、target repo と project repo のどちらの workflow が適切かを決めてから記録する。

## 調査手順

0. raw idea がまだない場合は、まず `hops-open-meta-scan` 相当の open scan を短く行い、Raw Ideas と Counterframes を出してからこの selection/routing lane に戻る。発散前に record 化しない。
1. 調査スコープを1文で置く。repo 役割、対象 capability、疑っている failure class、既存 dossier/feedback に足す調査か新規候補探索かを決める。
2. `rg` でコード、docs、tests、skills、`harness-lab/views/*.md`、`harness-feedback/records/*.md` を調べる。存在しない overlay は無理に作らない。既存 dossier、feedback、判断、ガード、未解決 open question があれば優先する。
3. 外部比較が判断を変えそうな場合だけ web 調査する。検索語にローカルパス、非公開語、未公開研究の文脈を入れない。一次情報、公式 docs、論文、標準実務を優先し、URL を evidence として残す。
4. 観測を「local evidence」「codebase evidence」「external benchmark」「risk / counterexample」に分ける。
5. 記録や issue 化の前に anti-myopia strategy pass を必ず行う。候補観測を horizon（immediate bugfix / workflow design / evaluation methodology / cross-project harness principle）と generalization（`local-only` / `repeated-pattern` / `cross-project` / `strategic`）で分類し、最大1件の systemic candidate に合成する。最新の小さな摩擦を、そのまま新規 record にしない。
6. local-only な候補は `park` または `reject as local` にする。ただし、より広い failure class の evidence や guardrail になる場合だけ systemic candidate の根拠として残す。
7. target/meta lab repo で既存テーマに入るなら新規 capture せず、`hops lab investigate` と `hops lab classify` で追記する。新しい failure class や cross-project pattern で、少なくとも2つの target/project repo に効く説明ができるなら `hops lab capture` または `hops lab research-scan` に進める。
8. project repo で観測した改善候補は、上流へ戻す feedback として記録・ルーティング・サニタイズする。project repo 内で `hops lab capture` や `hops propose` を実行しない。
9. target/meta lab repo で実装可能な systemic candidate だけ `hops lab new-eval-case` と `hops propose` に進める。仮説には mechanism、minimal implementation、alternative、evaluation plan、kill criteria を入れる。

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
hops add-failure --target <target> --title "<title>" --summary "<observed failure>"
hops route --record F0001
hops add-feedback --from F0001 --target <target>
hops feedback export --target <target> --sanitize
```

## 出力フォーマット

調査結果は短くまとめる。

- Scope: 対象 capability / failure class / 既存 dossier。
- Raw Ideas Considered: open scan から持ち込んだ案と、捨てた案。
- Evidence: local path、コード上の根拠、外部URL、反例。
- Candidate Horizon: 各観測の horizon、generalization、`local-only`/`park` 判断、systemic candidate への接続。
- Candidates: 改善候補、既存テーマとの relation、推奨コマンド。systemic candidate は最大1件に絞る。
- Recommendation: note、classify、capture、propose、park、reject、local-only のどれにするか。

複数候補があり、target/meta lab repo で後からルーティングや比較評価に戻りそうな場合は、回答だけで終えず `hops lab research-scan` を使う。`--local-evidence`、`--codebase-evidence`、`--external-benchmark`、`--risk` は `summary|ref`、`--candidate` は `title|relation|recommendation|next command` の形で渡す。project repo では research-scan ではなく、failure/feedback/export の結果と推奨 next command を短く報告する。

## 判断基準

- target/meta lab repo で既存の `IMP` に足せるものは `hops lab investigate` に留める。
- open scan の Raw Ideas をそのまま採用しない。この skill は発想を狭めるためではなく、発想後に evidence と routing を与えるために使う。
- target/meta lab repo の新規 capture は、将来の agent 行動、評価方法、移行方針、公開/非公開境界、複数 target/project に影響する場合だけにする。
- 新規 capture / research-scan / GitHub issue の前に、観測が広い capability と failure class を表しているか、少なくとも2つの target/project repo で意味を持つかを短く確認する。
- 複数の小さな摩擦がある場合は、個別に昇格させず、共通メカニズムへ synthesis する。例: CLI traceback、`.new` の混乱、repo role context 欠落は、別々の issue ではなく「candidate selection needs a horizon/generalization guard」として扱い、個別観測は evidence または park にする。
- project repo では上流採用判断を作らず、観測した失敗・回避策・改善候補を `harness-feedback` から sanitize/export できる形にする。
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
- project repo で `harness-lab/` を作らない。target/meta lab repo で project 固有の非公開文脈を正本 lab に混ぜない。
- newest friction を広いメカニズムや評価ギャップへ一般化できない場合は、新規 record を作らず `local-only` として park する。
