---
name: hops-run-lab
description: harness-lab で評価ケース、仮説、判断を扱うときに使う。
---

`hops doctor --check-overlay` を実行する。`.harnessops/`、`harness-feedback/`、`harness-lab/` の構造を直接組み替えない。

非自明なローカル改善、issue化前の観測、HarnessOps 自身の改善は、実装前または遅くともrelease前に `hops lab capture` で `FB` レコードにする。

```bash
hops lab capture --title "<title>" --summary "<summary>" --expected-change "<expected>"
```

その後、`hops lab new-eval-case`、`hops propose --manual-template`、`hops eval --manual`、`hops decide` を使う。

ガードレール:

- 評価証拠なしに採用を勧めない。
- 仮説にはメカニズム、評価計画、中止基準を含める。
- 新しいワークフロー面を追加する前に、削除または統合を優先する。
- 採用済み判断には、証拠、回帰リスク、ガードパスを含める。
- ホールドアウトケースや非公開プロジェクト文脈を露出しない。
