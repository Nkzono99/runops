---
name: harnessops-bridge
description: プロジェクト失敗の記録、上流フィードバックのルーティング、HarnessOps 改善ワークフローの実行時に使う。
---

このリポジトリは HarnessOps にリンクされています。

ハーネス状態の正本は `hops` CLI です。まず `.harnessops/project.toml` を読み、profile、overlay mode、overlay path を確認してください。
PATH に `hops` がない環境では `uvx --from harnessops hops <command>` を使います。

`.harnessops/`、`harness-feedback/`、`harness-lab/` の構造を直接組み替えないでください。レコード作成、ルーティング、エクスポート/インポート、ラボ評価、採用判断は CLI に委譲します。

- `hops doctor --check-overlay`
- `hops add-failure`
- `hops route`
- `hops add-feedback`
- `hops feedback export --sanitize`
- `hops feedback import <bundle-path>`
- `hops lab capture --title <title> --summary <summary> --expected-change <expected>`
- `hops lab dossier --from <FBid>`
- `hops lab investigate --from <IMPid> --summary <summary>`
- `hops lab classify --from <IMPid>`
- `hops lab new-eval-case --from <FBid>`
- `hops propose --from <Eid>`
- `hops eval --case <Eid> --manual`
- `hops decide --from <id> --status <status>`
- `hops update-harness`
- `hops migrate --check`

外部共有前にサニタイズ済みバンドルを確認し、ローカルパス、非公開語、未公開研究の文脈を残さないでください。
