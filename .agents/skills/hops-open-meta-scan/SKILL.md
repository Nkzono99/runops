---
name: hops-open-meta-scan
description: HarnessOps core、target repository、project repository を meta 的に眺め、発散的な改善案、構造的な違和感、逆張り仮説、未言語化のテーマを出すときに使う。ユーザーが「meta的な視点で改善案はある？」「発想を広げたい」「普通に眺めて違和感を出して」「まだ記録や評価はしないで」と頼んだときに使う。lab record、research-scan、GitHub issue、採用判断へ進める前の invention lane として使い、証拠化や routing が必要になったら hops-research-improvements へ渡す。
---
Use `uvx --from harnessops hops <command>` for CLI invocations in target/project repos; do not rely on `hops` being on PATH.

`hops doctor --check-overlay` を実行し、`.harnessops/project.toml` を読んで repo 役割を確認する。`.harnessops/`、`harness-feedback/`、`harness-lab/` の構造を直接組み替えない。

この skill は発想のための open scan であり、管理のための workflow ではない。デフォルトでは `hops lab capture`、`hops lab research-scan`、`hops lab new-eval-case`、`hops propose`、GitHub Issue 作成を実行しない。ユーザーが記録・評価・実装を求めたら、出た idea を `hops-research-improvements` または `hops-run-lab` に渡す。

## 進め方

1. まず broad outside reviewer として見る。既存 lab records や failure class に早く寄せず、「この system が変だとしたらどこか」を探す。
2. `rg` で README、docs、skills、tests、CLI、recent lab views を軽く読む。完全な棚卸しではなく、違和感を見つけるための薄い横断にする。
3. Raw Ideas を発散する。workflow、skill design、evaluation、memory、privacy、operator burden、release/update、cross-project promotion、削除/統合の観点を混ぜる。
4. Anti-fixation pass を行う。今見えている既存 skill、record、issue に引っ張られすぎていないか、別フレーミングを最低1つ出す。
5. Ideas をまだ採用しない。各 idea に rough horizon（now / next / later）、novelty、possible evidence、risk を短く付ける。
6. 最後に Routing Hints として、後段で `hops-research-improvements` に渡すならどの idea から調査するかだけを書く。

## 出力

短く、発散と収束を分ける。

- Open Scan: 外部レビュワー視点の違和感。
- Raw Ideas: まだ failure class に固定しない改善案。3-7件。
- Counterframes: 別の見方、逆張り、削除/統合案。
- Routing Hints: 記録するならどれを `hops-research-improvements` へ渡すか。
- Do Not Record Yet: まだ lab record にしない理由。

## 判断基準

- 発想を recordable にしすぎない。最初から capability、failure class、next command を埋めようとしない。
- 一番新しい摩擦だけに寄らない。設計思想、誘因、責務分離、評価不能性、管理過多を見る。
- 管理のためのチェックリストは gate として使い、generator にしない。
- 「良さそう」だけで実装しない。実装や lab 化は後段で evidence、evaluation、guard を持たせる。
- privacy と external sharing は守る。未サニタイズ情報を web 検索語、Issue、PR へ出さない。
- project repo で `harness-lab/` を作らない。target/meta lab repo で project 固有の非公開文脈を正本 lab に混ぜない。

## 次の橋渡し

ユーザーが「記録して」「調査して」「実装して」と言ったら、Raw Ideas のうち最大1-2件を選んで `hops-research-improvements` へ渡す。その時点で evidence、relation、park/reject、research-scan、capture、eval/propose を扱う。
