---
name: hops-add-failure
description: プロジェクト失敗、ハーネス摩擦、ローカル回避策、上流フィードバック候補を HarnessOps 経由で記録するときに使う。
---

HarnessOps を使う。`hops doctor --check-overlay` を実行し、`.harnessops/`、`harness-feedback/`、`harness-lab/` の構造を直接組み替えない。`hops add-failure`、`hops route`、`hops feedback export --sanitize` を呼び出す。

プロジェクト発展は `research/` または `notes/` に残し、ターゲットまたはメタへの昇格前に非公開文脈をサニタイズする。
